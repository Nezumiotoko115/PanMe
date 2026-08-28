"""画面状態機械をTkinterや実機なしで確認します。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.controller import (
    AUTH,
    CLOSE_LOCKER,
    COMPLETE,
    ERROR_SCREEN,
    IDLE,
    LOCKER_CONFIRM,
    LOCKING,
    PRODUCT_DETAIL,
    PRODUCT_LIST,
    TAKE_PRODUCT,
    UNLOCKED_SCREEN,
    UNLOCKING,
    WELCOME,
    PanMeController,
)
from ui.services import DemoAuthentication


class FakeEventLogger:
    def __init__(self):
        self.events = []

    def write(self, event, **details):
        self.events.append({"event": event, **details})


class FakeProductService:
    def __init__(self):
        self.items = [
            {
                "locker_id": "A-01",
                "product_id": "P001",
                "product_name": "チョコパン",
                "category": "パン",
                "stock": 3,
                "status": "AVAILABLE",
                "image": None,
            },
            {
                "locker_id": "A-02",
                "product_id": "P002",
                "product_name": "売り切れパン",
                "category": "パン",
                "stock": 0,
                "status": "SOLD_OUT",
                "image": None,
            },
            {
                "locker_id": "A-03",
                "product_id": "P003",
                "product_name": "停止中商品",
                "category": "パン",
                "stock": 2,
                "status": "AVAILABLE",
                "image": None,
            },
        ]

    def get_products(self):
        return [dict(item) for item in self.items]

    def decrease_stock(self, product_id):
        for item in self.items:
            if item["product_id"] == product_id:
                item["stock"] -= 1
                return dict(item)


class FakeLockerManager:
    def __init__(self):
        self.states = {
            "A-01": {"status": "LOCKED", "enabled": True},
            "A-02": {"status": "LOCKED", "enabled": True},
            "A-03": {"status": "DISABLED", "enabled": False},
        }
        self.unlock_result = {
            "success": True,
            "locker_id": "A-01",
            "status": "UNLOCKED",
        }

    def get_locker_status(self, locker_id):
        state = self.states[locker_id]
        return {"success": True, "locker_id": locker_id, **state}

    def unlock_locker(self, locker_id):
        if self.unlock_result["success"]:
            self.states[locker_id]["status"] = "UNLOCKED"
        return dict(self.unlock_result)

    def set_locker_status(self, locker_id, status):
        self.states[locker_id]["status"] = status
        return {"success": True, "locker_id": locker_id, "status": status}

    def lock_locker(self, locker_id):
        self.states[locker_id]["status"] = "LOCKED"
        return {"success": True, "locker_id": locker_id, "status": "LOCKED"}


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.manager = FakeLockerManager()
        self.products = FakeProductService()
        self.events = FakeEventLogger()
        self.background_jobs = []
        self.controller = PanMeController(
            self.manager,
            DemoAuthentication(),
            self.products,
            self.events,
            schedule=lambda _delay, callback: callback(),
            background_runner=lambda job: job(),
        )

    def go_to_confirm(self):
        self.controller.start()
        self.controller.begin()
        self.controller.authenticate()
        self.controller.show_products()
        self.controller.select_product(self.products.items[0])
        self.controller.confirm_product()
        self.assertEqual(LOCKER_CONFIRM, self.controller.state)

    def test_complete_demo_flow_and_return_to_idle(self):
        self.controller.start()
        self.assertEqual(IDLE, self.controller.state)
        self.controller.begin()
        self.assertEqual(AUTH, self.controller.state)
        self.controller.authenticate()
        self.assertEqual(WELCOME, self.controller.state)
        self.controller.show_products()
        self.assertEqual(PRODUCT_LIST, self.controller.state)
        self.assertTrue(self.controller.select_product(self.products.items[0]))
        self.assertEqual(PRODUCT_DETAIL, self.controller.state)
        self.controller.confirm_product()
        self.controller.unlock()
        self.assertEqual(UNLOCKED_SCREEN, self.controller.state)
        self.controller.continue_to_take_product()
        self.assertEqual(TAKE_PRODUCT, self.controller.state)
        self.controller.product_received()
        self.assertEqual(CLOSE_LOCKER, self.controller.state)
        self.controller.close_and_lock()
        self.assertEqual(COMPLETE, self.controller.state)
        self.assertEqual(2, self.products.items[0]["stock"])
        self.assertTrue(self.controller.cancel_to_idle())
        self.assertEqual(IDLE, self.controller.state)

    def test_sold_out_and_disabled_products_cannot_be_selected(self):
        self.controller.start()
        self.controller.begin()
        self.controller.authenticate()
        self.controller.show_products()
        self.assertFalse(self.controller.select_product(self.products.items[1]))
        self.assertFalse(self.controller.select_product(self.products.items[2]))
        self.assertEqual(PRODUCT_LIST, self.controller.state)

    def test_unlock_failure_opens_error_screen(self):
        self.go_to_confirm()
        self.manager.unlock_result = {
            "success": False,
            "error_code": "SERVO_ERROR",
        }
        self.controller.unlock()
        self.assertEqual(ERROR_SCREEN, self.controller.state)
        self.assertEqual("SERVO_ERROR", self.controller.error_code)

    def test_timeout_returns_from_safe_screen(self):
        self.controller.start()
        self.controller.begin()
        self.assertTrue(self.controller.handle_timeout())
        self.assertEqual(IDLE, self.controller.state)

    def test_timeout_is_ignored_after_unlock(self):
        self.go_to_confirm()
        self.controller.unlock()
        self.assertEqual(UNLOCKED_SCREEN, self.controller.state)
        self.assertFalse(self.controller.handle_timeout())
        self.assertEqual(UNLOCKED_SCREEN, self.controller.state)

    def test_unlock_returns_immediately_to_loading_state(self):
        controller = PanMeController(
            self.manager,
            DemoAuthentication(),
            self.products,
            self.events,
            schedule=lambda _delay, callback: callback(),
            background_runner=self.background_jobs.append,
        )
        controller.start()
        controller.begin()
        controller.authenticate()
        controller.show_products()
        controller.select_product(self.products.items[0])
        controller.confirm_product()
        controller.unlock()
        self.assertEqual(UNLOCKING, controller.state)
        self.assertEqual(1, len(self.background_jobs))
        self.background_jobs[0]()
        self.assertEqual(UNLOCKED_SCREEN, controller.state)


if __name__ == "__main__":
    unittest.main()

