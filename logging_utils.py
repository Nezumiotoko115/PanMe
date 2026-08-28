"""ターミナル・ロッカー操作・UIイベントのログ機能をまとめます。"""

import json
from datetime import datetime
from pathlib import Path
from threading import Lock

import config


def info(message):
    if config.DEBUG_MODE:
        print(f"[INFO] {message}")


def mock(message):
    if config.DEBUG_MODE:
        print(f"[MOCK] {message}")


def error(message):
    print(f"[ERROR] {message}")


class OperationLogger:
    """ロッカー操作を追記専用のJSON Lines形式で保存します。"""

    def __init__(self, path=None, enabled=None):
        base = Path(__file__).resolve().parent
        configured = path or config.OPERATION_LOG_PATH
        self.path = Path(configured)
        if not self.path.is_absolute():
            self.path = base / self.path
        self.enabled = config.OPERATION_LOG_ENABLED if enabled is None else enabled
        self._lock = Lock()

    def write(
        self,
        locker_id,
        action,
        status_before,
        status_after,
        channel,
        angle,
        result,
        error=None,
    ):
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "locker_id": locker_id,
            "action": action,
            "status_before": status_before,
            "status_after": status_after,
            "channel": channel,
            "angle": angle,
            "result": result,
            "error": error,
        }
        if not self.enabled:
            return record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


class UIEventLogger:
    """画面操作を利用分析へ渡せるJSON Lines形式で保存します。"""

    def __init__(self, path=None):
        base = Path(__file__).resolve().parent
        self.path = Path(path or config.UI_LOG_PATH)
        if not self.path.is_absolute():
            self.path = base / self.path
        self._lock = Lock()

    def write(self, event, **details):
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            **details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
