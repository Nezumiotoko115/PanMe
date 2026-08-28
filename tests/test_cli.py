"""CLIの4×4表示と安全確認をテストします。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from main import PanMeCLI, format_locker_grid


class FakeManager:
    def __init__(self):
        self.test_called = 0

    def get_all_locker_status(self):
        return {locker_id: "LOCKED" for locker_id in config.LOCKER_CHANNELS}

    def unlock_locker(self, locker_id):
        self.test_called += 1
        return {"success": True, "locker_id": locker_id}

    def lock_locker(self, locker_id):
        return {"success": True, "locker_id": locker_id}


class FakeServo:
    pass


class CLITest(unittest.TestCase):
    def test_grid_has_four_rows_and_all_ids(self):
        statuses = {locker_id: "LOCKED" for locker_id in config.LOCKER_CHANNELS}
        grid = format_locker_grid(statuses)
        self.assertEqual(16, sum(grid.count(locker_id) for locker_id in statuses))
        self.assertIn("A-01", grid)
        self.assertIn("D-04", grid)

    def test_all_requires_exact_yes(self):
        manager = FakeManager()
        cli = PanMeCLI(manager, FakeServo(), input_function=lambda _prompt: "no")
        cli.test_all_lockers()
        self.assertEqual(0, manager.test_called)

    def test_all_runs_all_16_after_yes(self):
        old_interval = config.ALL_TEST_INTERVAL_SECONDS
        config.ALL_TEST_INTERVAL_SECONDS = 0
        try:
            manager = FakeManager()
            cli = PanMeCLI(manager, FakeServo(), input_function=lambda _prompt: "yes")
            cli.test_all_lockers()
            self.assertEqual(16, manager.test_called)
        finally:
            config.ALL_TEST_INTERVAL_SECONDS = old_interval


if __name__ == "__main__":
    unittest.main()
