"""FINAL DEMOのモード分離と繰り返し撮影設定を確認します。"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from api_client import PanMeApiError
from integration_services import (
    ApiAuthorizedLockerService,
    ApiProductService,
    DemoApiAuthenticationService,
)
from ui.services import DemoAuthentication, DemoProductService
from ui_main import _build_services


class FakeApi:
    def __init__(self, online=True):
        self.online = online

    def get(self, path):
        if not self.online:
            raise PanMeApiError("API_ERROR", "offline")
        if path == "/lockers":
            return [
                {"locker_id": locker_id, "locker_status": "LOCKED"}
                for locker_id in config.LOCKER_CHANNELS
            ]
        return {}

    def post(self, _path, _payload):
        return {}


class FinalDemoModeTest(unittest.TestCase):
    def test_demo_auth_can_use_api_products_and_api_authorized_hardware(self):
        with (
            patch.object(config, "DEMO_MODE", True),
            patch.object(config, "USE_API", True),
            patch.object(config, "DEMO_API_FALLBACK", False),
            patch("config.validate_production_settings"),
            patch("ui_main.PanMeApiClient", return_value=FakeApi()),
        ):
            manager, auth, products, _events, status = _build_services(
                object(), object()
            )

        self.assertIsInstance(manager, ApiAuthorizedLockerService)
        self.assertIsInstance(auth, DemoApiAuthenticationService)
        self.assertIsInstance(products, ApiProductService)
        self.assertIsNotNone(status)

    def test_api_startup_failure_falls_back_only_when_explicitly_enabled(self):
        with (
            patch.object(config, "DEMO_MODE", True),
            patch.object(config, "USE_API", True),
            patch.object(config, "DEMO_API_FALLBACK", True),
            patch("config.validate_production_settings"),
            patch("ui_main.PanMeApiClient", return_value=FakeApi(online=False)),
        ):
            manager, auth, products, _events, status = _build_services(
                "local-manager", object()
            )

        self.assertEqual(manager, "local-manager")
        self.assertIsInstance(auth, DemoAuthentication)
        self.assertIsInstance(products, DemoProductService)
        self.assertIsNone(status)

    def test_demo_stock_can_be_kept_for_repeated_recording(self):
        with patch.object(config, "DEMO_DECREASE_STOCK", False):
            service = DemoProductService()
            before = service.get_products()[0]["stock"]
            service.decrease_stock("P001")
            after = service.get_products()[0]["stock"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
