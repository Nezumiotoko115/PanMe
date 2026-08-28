"""STEP4のAPI連携順序と安全停止を実機なしで確認します。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from integration_services import ApiAuthorizedLockerService, EventService


class FakeApi:
    def __init__(self, online=True):
        self.online = online
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        if not self.online:
            from api_client import PanMeApiError
            raise PanMeApiError("API_ERROR", "offline")
        return [{"locker_id": "A-01", "locker_status": "LOCKED"}]

    def post(self, path, payload):
        self.calls.append(("POST", path))
        if path.endswith("/unlock"):
            return {"transaction_id": "tx-001", "authorized": True}
        return {}


class FakeLocalManager:
    def __init__(self):
        self.calls = []
        self.status = "LOCKED"

    def get_locker_status(self, locker_id):
        return {
            "success": True, "locker_id": locker_id,
            "status": self.status, "enabled": True,
        }

    def get_all_locker_status(self):
        return {"A-01": self.status}

    def unlock_locker(self, locker_id):
        self.calls.append(("UNLOCK", locker_id))
        self.status = "UNLOCKED"
        return {"success": True, "locker_id": locker_id, "status": self.status}

    def lock_locker(self, locker_id):
        self.calls.append(("LOCK", locker_id))
        self.status = "LOCKED"
        return {"success": True, "locker_id": locker_id, "status": self.status}

    def set_locker_status(self, locker_id, status):
        self.status = status
        return {"success": True, "locker_id": locker_id, "status": status}


class Step4IntegrationTest(unittest.TestCase):
    def _context(self):
        return (
            {"user_id": "1", "auth_token": "token"},
            {"product_id": "7", "locker_id": "A-01", "reservation_id": None},
        )

    def test_api_permission_is_requested_before_local_unlock(self):
        api = FakeApi()
        local = FakeLocalManager()
        service = ApiAuthorizedLockerService(local, api, EventService(api))
        user, product = self._context()
        service.begin_usage(user, product)

        result = service.unlock_locker("A-01")

        self.assertTrue(result["success"])
        unlock_api_index = api.calls.index(("POST", "/lockers/A-01/unlock"))
        event_api_index = api.calls.index(("POST", "/events"))
        self.assertLess(unlock_api_index, event_api_index)
        self.assertEqual(local.calls[0], ("UNLOCK", "A-01"))

    def test_offline_mode_never_moves_servo(self):
        api = FakeApi(online=False)
        local = FakeLocalManager()
        service = ApiAuthorizedLockerService(local, api, EventService(api))
        user, product = self._context()
        service.begin_usage(user, product)

        result = service.unlock_locker("A-01")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "API_ERROR")
        self.assertEqual(local.calls, [])

    def test_lock_then_complete_are_sent_after_physical_lock(self):
        api = FakeApi()
        local = FakeLocalManager()
        service = ApiAuthorizedLockerService(local, api, EventService(api))
        user, product = self._context()
        service.begin_usage(user, product)
        self.assertTrue(service.unlock_locker("A-01")["success"])
        self.assertTrue(service.mark_product_taken("A-01")["success"])

        result = service.lock_locker("A-01")

        self.assertTrue(result["success"])
        self.assertIn(("LOCK", "A-01"), local.calls)
        lock_index = api.calls.index(("POST", "/lockers/A-01/lock"))
        complete_index = api.calls.index(("POST", "/lockers/A-01/complete"))
        self.assertLess(lock_index, complete_index)


if __name__ == "__main__":
    unittest.main()
