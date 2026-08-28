"""16個のロッカー情報、状態遷移、操作キューを一元管理します。"""

import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import RLock
from typing import Optional

import config
import logging_utils as logger
from errors import (
    ALREADY_LOCKED,
    ALREADY_UNLOCKED,
    INVALID_LOCKER,
    LOCKER_BUSY,
    LOCKER_DISABLED,
    LOCKER_ERROR,
    PanMeHardwareError,
    failure,
    success,
)
from logging_utils import OperationLogger

LOCKED = "LOCKED"
UNLOCKED = "UNLOCKED"
OPEN = "OPEN"
CLOSED = "CLOSED"
ERROR = "ERROR"
DISABLED = "DISABLED"

VALID_STATES = (LOCKED, UNLOCKED, OPEN, CLOSED, ERROR, DISABLED)


def now_text():
    """人が読みやすく、JSONにも保存しやすいローカル日時を返します。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Locker:
    locker_id: str
    channel: int
    status: str = LOCKED
    enabled: bool = True
    last_action: str = "INITIALIZE_SOFTWARE"
    last_action_time: str = ""
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class OperationTicket:
    """キュー投入結果を後から受け取るための小さなチケットです。"""

    operation_id: int
    locker_id: str
    action: str
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[dict] = None

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            return failure(LOCKER_BUSY, "操作の完了待ちがタイムアウトしました", self.locker_id)
        return self.result


class LockerOperationQueue:
    """1本のワーカースレッドだけが操作関数を実行します。"""

    def __init__(self, handler):
        self._handler = handler
        self._queue = queue.Queue()
        self._pending_lockers = set()
        self._lock = threading.Lock()
        self._next_id = 1
        self._stopping = False
        self._worker = threading.Thread(
            target=self._run,
            name="panme-servo-worker",
            daemon=True,
        )
        self._worker.start()

    def submit(self, locker_id, action, wait=True):
        with self._lock:
            if locker_id in self._pending_lockers:
                return failure(
                    LOCKER_BUSY,
                    "同じロッカーの操作が待機中または実行中です",
                    locker_id,
                )
            ticket = OperationTicket(self._next_id, locker_id, action)
            self._next_id += 1
            self._pending_lockers.add(locker_id)
            self._queue.put(ticket)
        return ticket.wait() if wait else ticket

    def _run(self):
        while True:
            ticket = self._queue.get()
            if ticket is None:
                self._queue.task_done()
                break
            try:
                ticket.result = self._handler(ticket.locker_id, ticket.action)
            except Exception as exc:
                ticket.result = failure(
                    "LOCKER_ERROR",
                    f"操作キュー内で予期しないエラーが発生しました: {exc}",
                    ticket.locker_id,
                )
            finally:
                time.sleep(config.SERVO_ACTION_DELAY)
                with self._lock:
                    self._pending_lockers.discard(ticket.locker_id)
                ticket.done.set()
                self._queue.task_done()

    def snapshot(self):
        with self._lock:
            pending = sorted(self._pending_lockers)
        return {
            "pending_count": len(pending),
            "pending_lockers": pending,
            "unfinished_tasks": self._queue.unfinished_tasks,
        }

    def wait_until_empty(self):
        self._queue.join()

    def close(self):
        if self._stopping:
            return
        self._stopping = True
        self._queue.put(None)
        self._worker.join()

LOCKER_UNLOCKED = "LOCKER_UNLOCKED"
LOCKER_LOCKED = "LOCKER_LOCKED"
LOCKER_ERROR_EVENT = "LOCKER_ERROR"
LOCKER_DISABLED = "LOCKER_DISABLED"
LOCKER_ENABLED = "LOCKER_ENABLED"
LOCKER_STATUS_CHANGED = "LOCKER_STATUS_CHANGED"


class LockerManager:
    """将来のUIやAPIから呼び出す、ロッカー制御の中心クラスです。"""

    def __init__(self, servo_controller, operation_logger=None):
        self.servo = servo_controller
        # config.pyの記載順が、そのまま4×4の物理配置順になります。
        self._lockers = {
            locker_id: Locker(locker_id=locker_id, channel=channel)
            for locker_id, channel in config.LOCKER_CHANNELS.items()
        }
        self._state_lock = RLock()
        self._subscribers = []
        self.operation_logger = operation_logger or OperationLogger()
        self.operation_queue = LockerOperationQueue(self._execute_queued_operation)

    def locker_exists(self, locker_id):
        return locker_id in self._lockers

    def subscribe(self, callback):
        """将来のUI/APIがイベントを受け取る関数を登録できます。"""
        self._subscribers.append(callback)

    def _emit(self, event_name, locker, result):
        event = {
            "event": event_name,
            "timestamp": now_text(),
            "locker": locker.to_dict(),
            "result": result,
        }
        for callback in tuple(self._subscribers):
            try:
                callback(event)
            except Exception as exc:
                logger.error(f"イベント受信側でエラーが発生しました: {exc}")

    def _invalid_locker(self, locker_id):
        message = f"ロッカーIDが存在しません: {locker_id}"
        logger.error(message)
        return failure(INVALID_LOCKER, message, locker_id)

    def _angle_for(self, locker_id, action):
        angles = config.LOCKER_ANGLES.get(locker_id, {})
        if action in ("LOCK", "INITIALIZE"):
            return angles.get("lock", config.LOCK_ANGLE)
        return angles.get("unlock", config.UNLOCK_ANGLE)

    def _record(self, locker, action, before, angle, result):
        error_code = result.get("error_code")
        self.operation_logger.write(
            locker_id=locker.locker_id,
            action=action,
            status_before=before,
            status_after=locker.status,
            channel=locker.channel,
            angle=angle,
            result="SUCCESS" if result["success"] else "ERROR",
            error=error_code,
        )

    def _reject(self, locker, action, before, code, message, angle=None):
        result = failure(code, message, locker.locker_id)
        locker.last_action = action
        locker.last_action_time = now_text()
        locker.error = code if code not in (
            ALREADY_LOCKED,
            ALREADY_UNLOCKED,
            LOCKER_BUSY,
        ) else locker.error
        self._record(locker, action, before, angle, result)
        return result

    def _execute_queued_operation(self, locker_id, action):
        """キューワーカーだけが呼ぶ、実際のサーボ操作です。"""
        locker = self._lockers[locker_id]
        with self._state_lock:
            before = locker.status
            if not locker.enabled or locker.status == DISABLED:
                return self._reject(
                    locker, action, before, LOCKER_DISABLED,
                    "ロッカーはメンテナンスのため無効です",
                )
            if locker.status == ERROR:
                return self._reject(
                    locker, action, before, LOCKER_ERROR,
                    "ERRORを復旧してから操作してください",
                )

            if action == "UNLOCK":
                if locker.status == UNLOCKED:
                    return self._reject(
                        locker, action, before, ALREADY_UNLOCKED,
                        "ロッカーはすでに解錠されています",
                    )
                if locker.status != LOCKED:
                    return self._reject(
                        locker, action, before, LOCKER_BUSY,
                        f"{locker.status}状態のため解錠できません",
                    )
            elif action == "LOCK":
                if locker.status == LOCKED:
                    return self._reject(
                        locker, action, before, ALREADY_LOCKED,
                        "ロッカーはすでに施錠されています",
                    )
                if locker.status == OPEN:
                    return self._reject(
                        locker, action, before, LOCKER_ERROR,
                        "扉がOPENのため施錠できません",
                    )
                if locker.status not in (UNLOCKED, CLOSED):
                    return self._reject(
                        locker, action, before, LOCKER_BUSY,
                        f"{locker.status}状態のため施錠できません",
                    )
            elif action != "INITIALIZE":
                return self._reject(
                    locker, action, before, LOCKER_ERROR,
                    f"不正な操作です: {action}",
                )

            angle = self._angle_for(locker_id, action)
            logger.info(f"{action} {locker_id} → CH{locker.channel} / {angle}度")
            try:
                servo_action = "LOCK" if action == "INITIALIZE" else action
                self.servo.move_locker(locker_id, locker.channel, servo_action)
                locker.status = UNLOCKED if action == "UNLOCK" else LOCKED
                locker.last_action = action
                locker.last_action_time = now_text()
                locker.error = None
                result = success(
                    locker_id=locker_id,
                    channel=locker.channel,
                    status=locker.status,
                )
                self._record(locker, action, before, angle, result)
                self._emit(
                    LOCKER_UNLOCKED if action == "UNLOCK" else LOCKER_LOCKED,
                    locker,
                    result,
                )
                return result
            except PanMeHardwareError as exc:
                locker.status = ERROR
                locker.last_action = action
                locker.last_action_time = now_text()
                locker.error = exc.code
                result = failure(exc.code, exc.message, locker_id)
                self._record(locker, action, before, angle, result)
                self._emit(LOCKER_ERROR_EVENT, locker, result)
                return result

    def enqueue_unlock(self, locker_id):
        """UI向け非同期API。操作チケットまたは即時エラー辞書を返します。"""
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        return self.operation_queue.submit(locker_id, "UNLOCK", wait=False)

    def enqueue_lock(self, locker_id):
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        return self.operation_queue.submit(locker_id, "LOCK", wait=False)

    def unlock_locker(self, locker_id):
        """CLI向け同期API。内部では必ず操作キューを経由します。"""
        ticket = self.enqueue_unlock(locker_id)
        return ticket.wait() if isinstance(ticket, OperationTicket) else ticket

    def lock_locker(self, locker_id):
        ticket = self.enqueue_lock(locker_id)
        return ticket.wait() if isinstance(ticket, OperationTicket) else ticket

    def initialize_all_lockers(self):
        """明示的に呼ばれた場合だけ、16室を順番に施錠位置へ動かします。"""
        results = []
        for locker_id in self._lockers:
            submitted = self.operation_queue.submit(locker_id, "INITIALIZE", wait=True)
            results.append(submitted)
        return results

    def get_locker_status(self, locker_id):
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        with self._state_lock:
            return success(**self._lockers[locker_id].to_dict())

    def get_locker_info(self, locker_id):
        return self.get_locker_status(locker_id)

    def get_all_locker_status(self):
        with self._state_lock:
            return {
                locker_id: locker.status
                for locker_id, locker in self._lockers.items()
            }

    def get_all_locker_info(self):
        with self._state_lock:
            return [locker.to_dict() for locker in self._lockers.values()]

    def set_locker_status(self, locker_id, status):
        """扉センサーがない間、OPEN/CLOSEDを手動入力します。"""
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        if status not in VALID_STATES:
            return failure(LOCKER_ERROR, f"不正な状態です: {status}", locker_id)
        if status in (DISABLED, ERROR):
            return failure(
                LOCKER_ERROR,
                "DISABLEDはdisable_locker()、ERRORは実エラー検出で設定します",
                locker_id,
            )

        with self._state_lock:
            locker = self._lockers[locker_id]
            before = locker.status
            allowed = {
                LOCKED: (LOCKED,),
                UNLOCKED: (UNLOCKED, OPEN, CLOSED),
                OPEN: (OPEN, CLOSED),
                CLOSED: (CLOSED,),
            }
            if locker.status not in allowed or status not in allowed[locker.status]:
                return self._reject(
                    locker, "SET_STATUS", before, LOCKER_ERROR,
                    f"不正な状態遷移です: {before} → {status}",
                )
            locker.status = status
            locker.last_action = "SET_STATUS"
            locker.last_action_time = now_text()
            result = success(locker_id=locker_id, status=status)
            self._record(locker, "SET_STATUS", before, None, result)
            self._emit(LOCKER_STATUS_CHANGED, locker, result)
            return result

    def disable_locker(self, locker_id):
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        if locker_id in self.operation_queue.snapshot()["pending_lockers"]:
            return failure(LOCKER_BUSY, "操作中のロッカーは無効化できません", locker_id)
        with self._state_lock:
            locker = self._lockers[locker_id]
            before = locker.status
            if locker.status != LOCKED:
                return self._reject(
                    locker, "DISABLE", before, LOCKER_ERROR,
                    "安全のためLOCKED状態でのみ無効化できます",
                )
            locker.enabled = False
            locker.status = DISABLED
            locker.last_action = "DISABLE"
            locker.last_action_time = now_text()
            result = success(locker_id=locker_id, status=DISABLED)
            self._record(locker, "DISABLE", before, None, result)
            self._emit(LOCKER_DISABLED, locker, result)
            return result

    def enable_locker(self, locker_id):
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        with self._state_lock:
            locker = self._lockers[locker_id]
            before = locker.status
            if locker.enabled and locker.status != DISABLED:
                return self._reject(
                    locker, "ENABLE", before, LOCKER_ERROR,
                    "ロッカーはすでに有効です",
                )
            locker.enabled = True
            locker.status = LOCKED
            locker.error = None
            locker.last_action = "ENABLE"
            locker.last_action_time = now_text()
            result = success(locker_id=locker_id, status=LOCKED)
            self._record(locker, "ENABLE", before, None, result)
            self._emit(LOCKER_ENABLED, locker, result)
            return result

    def reset_error(self, locker_id):
        """PCA9685接続確認後にだけERRORをソフトウェア上で解除します。"""
        if not self.locker_exists(locker_id):
            return self._invalid_locker(locker_id)
        with self._state_lock:
            locker = self._lockers[locker_id]
            before = locker.status
            if locker.status != ERROR:
                return self._reject(
                    locker, "RESET_ERROR", before, LOCKER_ERROR,
                    "ロッカーはERROR状態ではありません",
                )
            if not self.servo.health_check():
                return self._reject(
                    locker, "RESET_ERROR", before, LOCKER_ERROR,
                    "PCA9685の接続確認に失敗したため復旧できません",
                )
            locker.status = LOCKED
            locker.enabled = True
            locker.error = None
            locker.last_action = "RESET_ERROR"
            locker.last_action_time = now_text()
            result = success(locker_id=locker_id, status=LOCKED)
            self._record(locker, "RESET_ERROR", before, None, result)
            return result

    def queue_status(self):
        return self.operation_queue.snapshot()

    def close(self):
        """終了前にキューの処理を完了し、ワーカーを停止します。"""
        self.operation_queue.wait_until_empty()
        self.operation_queue.close()
