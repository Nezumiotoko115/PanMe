"""STEP2の16ロッカー管理を実機なしで確認します。"""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from errors import PanMeHardwareError
from hardware import ServoController
from locker_manager import (
    CLOSED,
    DISABLED,
    ERROR,
    LOCKED,
    OPEN,
    UNLOCKED,
    LockerManager,
)
from logging_utils import OperationLogger


class FakePCA9685:
    """I2C機器の代わりにPWM命令を記録するモックです。"""

    def __init__(self):
        self.pulses = []
        self.released = []
        self.healthy = True

    def set_pulse_us(self, channel, pulse_us):
        self.pulses.append((channel, pulse_us))

    def release_channel(self, channel):
        self.released.append(channel)

    def health_check(self):
        return self.healthy


class BlockingServo:
    """重複キュー投入を確実に試すため、解除されるまで動作を止めます。"""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def move_locker(self, locker_id, channel, action):
        self.started.set()
        self.release.wait(2)
        return config.UNLOCK_ANGLE if action == "UNLOCK" else config.LOCK_ANGLE

    def health_check(self):
        return True


class RecordingServo:
    """FIFO順と同時動作数を記録するモックサーボです。"""

    def __init__(self):
        self.order = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def move_locker(self, locker_id, channel, action):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.order.append(locker_id)
        time.sleep(0.005)
        with self.lock:
            self.active -= 1
        return config.UNLOCK_ANGLE

    def health_check(self):
        return True


class LockerManagerTest(unittest.TestCase):
    def setUp(self):
        self.old_values = (
            config.SERVO_MOVE_SECONDS,
            config.MIN_OPERATION_INTERVAL_SECONDS,
            config.SERVO_ACTION_DELAY,
        )
        config.SERVO_MOVE_SECONDS = 0
        config.MIN_OPERATION_INTERVAL_SECONDS = 0
        config.SERVO_ACTION_DELAY = 0
        self.pca = FakePCA9685()
        self.servo = ServoController(self.pca)
        self.manager = LockerManager(
            self.servo,
            operation_logger=OperationLogger(enabled=False),
        )

    def tearDown(self):
        self.manager.close()
        (
            config.SERVO_MOVE_SECONDS,
            config.MIN_OPERATION_INTERVAL_SECONDS,
            config.SERVO_ACTION_DELAY,
        ) = self.old_values

    def test_all_16_lockers_start_locked_without_servo_movement(self):
        self.assertEqual(16, len(self.manager.get_all_locker_status()))
        self.assertEqual(set(range(16)), set(config.LOCKER_CHANNELS.values()))
        self.assertTrue(
            all(value == LOCKED for value in self.manager.get_all_locker_status().values())
        )
        self.assertEqual([], self.pca.pulses)

    def test_unlock_and_lock_a01(self):
        unlocked = self.manager.unlock_locker("A-01")
        self.assertEqual(
            {"success": True, "locker_id": "A-01", "channel": 0, "status": UNLOCKED},
            unlocked,
        )
        self.assertEqual(UNLOCKED, self.manager.get_locker_status("A-01")["status"])
        locked = self.manager.lock_locker("A-01")
        self.assertTrue(locked["success"])
        self.assertEqual(LOCKED, self.manager.get_locker_status("A-01")["status"])

    def test_door_state_flow(self):
        self.manager.unlock_locker("B-02")
        self.assertTrue(self.manager.set_locker_status("B-02", OPEN)["success"])
        self.assertTrue(self.manager.set_locker_status("B-02", CLOSED)["success"])
        self.assertTrue(self.manager.lock_locker("B-02")["success"])

    def test_disable_enable_and_disabled_unlock(self):
        disabled = self.manager.disable_locker("C-03")
        self.assertEqual(DISABLED, disabled["status"])
        self.assertFalse(self.manager.unlock_locker("C-03")["success"])
        enabled = self.manager.enable_locker("C-03")
        self.assertEqual(LOCKED, enabled["status"])

    def test_duplicate_pending_command_is_rejected(self):
        self.manager.close()
        blocking = BlockingServo()
        self.manager = LockerManager(
            blocking,
            operation_logger=OperationLogger(enabled=False),
        )
        first = self.manager.enqueue_unlock("A-01")
        self.assertTrue(blocking.started.wait(1))
        duplicate = self.manager.enqueue_unlock("A-01")
        self.assertIsInstance(duplicate, dict)
        self.assertEqual("LOCKER_BUSY", duplicate["error_code"])
        blocking.release.set()
        self.assertTrue(first.wait(1)["success"])

    def test_queue_is_fifo_and_never_runs_two_servos_together(self):
        self.manager.close()
        servo = RecordingServo()
        self.manager = LockerManager(
            servo,
            operation_logger=OperationLogger(enabled=False),
        )
        tickets = [
            self.manager.enqueue_unlock("A-01"),
            self.manager.enqueue_unlock("A-02"),
            self.manager.enqueue_unlock("B-01"),
        ]
        self.assertTrue(all(ticket.wait(1)["success"] for ticket in tickets))
        self.assertEqual(["A-01", "A-02", "B-01"], servo.order)
        self.assertEqual(1, servo.max_active)

    def test_already_unlocked_and_already_locked(self):
        self.manager.unlock_locker("A-02")
        self.assertEqual(
            "ALREADY_UNLOCKED",
            self.manager.unlock_locker("A-02")["error_code"],
        )
        self.manager.lock_locker("A-02")
        self.assertEqual(
            "ALREADY_LOCKED",
            self.manager.lock_locker("A-02")["error_code"],
        )

    def test_initialize_all_moves_one_channel_at_a_time(self):
        results = self.manager.initialize_all_lockers()
        self.assertEqual(16, len(results))
        self.assertTrue(all(item["success"] for item in results))
        self.assertEqual(list(range(16)), [item[0] for item in self.pca.pulses])

    def test_reset_error_checks_hardware(self):
        locker = self.manager._lockers["D-04"]
        locker.status = ERROR
        locker.error = "SERVO_ERROR"
        self.pca.healthy = False
        failed = self.manager.reset_error("D-04")
        self.assertFalse(failed["success"])
        self.assertEqual(ERROR, locker.status)
        self.pca.healthy = True
        recovered = self.manager.reset_error("D-04")
        self.assertTrue(recovered["success"])
        self.assertEqual(LOCKED, locker.status)

    def test_event_is_emitted(self):
        events = []
        self.manager.subscribe(events.append)
        self.manager.unlock_locker("B-01")
        self.assertEqual("LOCKER_UNLOCKED", events[0]["event"])

    def test_invalid_locker_returns_error(self):
        result = self.manager.unlock_locker("Z-99")
        self.assertEqual("INVALID_LOCKER", result["error_code"])

    def test_open_door_cannot_be_locked(self):
        self.manager.unlock_locker("D-01")
        self.manager.set_locker_status("D-01", OPEN)
        result = self.manager.lock_locker("D-01")
        self.assertEqual("LOCKER_ERROR", result["error_code"])

    def test_operation_log_is_json_lines(self):
        self.manager.close()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.jsonl"
            self.manager = LockerManager(
                self.servo,
                operation_logger=OperationLogger(path=path, enabled=True),
            )
            self.manager.unlock_locker("A-04")
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("A-04", record["locker_id"])
            self.assertEqual("UNLOCK", record["action"])
            self.assertEqual("SUCCESS", record["result"])

    def test_angle_to_pulse(self):
        self.assertEqual(config.SERVO_MIN_PULSE, self.servo.angle_to_pulse(0))
        self.assertEqual(config.SERVO_MAX_PULSE, self.servo.angle_to_pulse(180))


if __name__ == "__main__":
    unittest.main()
