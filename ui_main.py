"""PanMe UIをデモモードまたはWeb API連携モードで起動します。"""

import tkinter as tk

import config
import logging_utils as logger
from api_client import PanMeApiClient
from integration_services import (
    ApiAuthenticationService,
    ApiAuthorizedLockerService,
    ApiProductService,
    CompositeEventLogger,
    DemoApiAuthenticationService,
    DeviceStatusService,
    EventService,
)
from errors import PanMeHardwareError
from hardware import PCA9685Controller, ServoController
from locker_manager import LockerManager
from logging_utils import UIEventLogger
from ui.app import PanMeUI
from ui.services import DemoAuthentication, DemoProductService


def _build_services(local_manager, pca):
    """認証方式、データ取得元、実機制御を独立して組み立てます。"""
    local_events = UIEventLogger()
    if not config.USE_API:
        if not config.DEMO_MODE:
            raise RuntimeError("本番モードではPANME_USE_API=trueが必要です")
        local_events.write("API_DISABLED", mode="DEMO_DATA")
        return (
            local_manager,
            DemoAuthentication(),
            DemoProductService(),
            local_events,
            None,
        )

    import config as settings

    try:
        settings.validate_production_settings()
        api = PanMeApiClient()
        events = EventService(api)
        locker_service = ApiAuthorizedLockerService(local_manager, api, events)
        if not locker_service.api_online:
            raise RuntimeError("PanMe Web APIへ接続できません")
        local_events.write("API_CONNECTED", base_url=settings.API_BASE_URL)
        status_service = DeviceStatusService(api, pca, events)
        authentication = (
            DemoApiAuthenticationService(api)
            if config.DEMO_MODE
            else ApiAuthenticationService(api)
        )
        return (
            locker_service,
            authentication,
            ApiProductService(api),
            CompositeEventLogger(local_events, events),
            status_service,
        )
    except RuntimeError as exc:
        if not (config.DEMO_MODE and config.DEMO_API_FALLBACK):
            raise
        # 明示的に許可されたコンテスト用退避。DB更新は行われません。
        local_events.write("API_FALLBACK", error=str(exc))
        logger.error(f"APIを使用できないためデモデータへ切り替えます: {exc}")
        return (
            local_manager,
            DemoAuthentication(),
            DemoProductService(),
            local_events,
            None,
        )


def run_ui():
    pca = PCA9685Controller()
    local_manager = None
    status_service = None
    root = None
    exit_code = 0
    startup_log = UIEventLogger()
    try:
        startup_log.write(
            "APP_STARTING",
            demo_mode=config.DEMO_MODE,
            use_api=config.USE_API,
            mock_mode=config.MOCK_MODE,
        )
        logger.info(
            "PanMe IoT Demo System Start "
            f"(DEMO={config.DEMO_MODE}, API={config.USE_API}, MOCK={config.MOCK_MODE})"
        )
        pca.initialize()
        servo = ServoController(pca)
        local_manager = LockerManager(servo)
        manager, auth, products, event_logger, status_service = _build_services(
            local_manager, pca
        )
        if status_service:
            status_service.start()

        root = tk.Tk()
        PanMeUI(root, manager, auth, products, event_logger)
        root.mainloop()
    except tk.TclError as exc:
        startup_log.write("STARTUP_ERROR", error_code="UI_ERROR", message=str(exc))
        logger.error(f"画面を開始できません: {exc}")
        logger.error("デスクトップ環境またはDISPLAY設定を確認してください")
        exit_code = 1
    except PanMeHardwareError as exc:
        startup_log.write("STARTUP_ERROR", error_code=exc.code, message=exc.message)
        logger.error(f"{exc.code}: {exc.message}")
        exit_code = 1
    except (RuntimeError, ValueError) as exc:
        startup_log.write("STARTUP_ERROR", error_code="CONFIG_ERROR", message=str(exc))
        logger.error(f"起動設定エラー: {exc}")
        exit_code = 1
    finally:
        if status_service:
            status_service.stop()
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        if local_manager is not None:
            local_manager.close()
        pca.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_ui())
