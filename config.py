"""PanMe IoT Demo Systemの共通設定。

デモ当日に変更する値は、原則として同じフォルダーの.envへ記述します。
"""

import os
import platform
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv(Path(__file__).resolve().parent / ".env")


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    value = os.getenv(name)
    return int(value) if value is not None else default


def _running_on_raspberry_pi():
    """Raspberry Pi実機では、明示設定がなくてもハードウェアを使用します。"""
    try:
        model = Path("/proc/device-tree/model").read_text(
            encoding="utf-8", errors="ignore"
        )
        return "raspberry pi" in model.lower()
    except OSError:
        return platform.system() == "Linux" and "raspberrypi" in platform.node().lower()


# PCA9685 / Raspberry Pi I2C設定
PCA9685_ADDRESS = int(os.getenv("PANME_PCA9685_ADDRESS", "0x40"), 0)
I2C_BUS_NUMBER = _env_int("PANME_I2C_BUS_NUMBER", 1)
I2C_SDA_PIN = 3       # Raspberry Pi 物理ピン3 / GPIO2 (SDA1)
I2C_SCL_PIN = 5       # Raspberry Pi 物理ピン5 / GPIO3 (SCL1)

# SG90の設定
LOCK_ANGLE = 0
UNLOCK_ANGLE = 45
SERVO_MIN_PULSE = 500      # マイクロ秒。実機に合わせて慎重に調整
SERVO_MAX_PULSE = 2400     # マイクロ秒。実機に合わせて慎重に調整
SERVO_FREQUENCY = 50       # SG90で一般的な50Hz
SERVO_MOVE_SECONDS = 0.7   # 角度を変えた後に待つ時間
SERVO_HOLD_ENABLED = False # Falseなら移動後にPWMを止めて発熱を抑える

# 同じサーボを短時間に連続操作しないための待機時間
MIN_OPERATION_INTERVAL_SECONDS = 1.0
# キュー内の次のサーボ操作へ進む前の電源負荷軽減時間
SERVO_ACTION_DELAY = 0.5
# 一括テストで次のロッカーへ進むまでの待機時間
ALL_TEST_INTERVAL_SECONDS = 1.0

# ロッカーごとの角度補正。未登録ロッカーは共通角度を使います。
# 例: "A-01": {"lock": 5, "unlock": 85}
LOCKER_ANGLES = {}

# 操作ログ。プロジェクトフォルダーからの相対パスです。
OPERATION_LOG_PATH = "logs/locker_operations.jsonl"
OPERATION_LOG_ENABLED = True

# 実機なしのPCではTrue、Raspberry Pi実機ではFalseへ変更します。
# 環境変数が最優先です。未設定の場合はRaspberry Pi実機だけハードウェア
# モード、それ以外のPCでは安全のためモックモードになります。
MOCK_MODE = _env_bool("PANME_MOCK_MODE", not _running_on_raspberry_pi())
DEBUG_MODE = _env_bool("PANME_DEBUG_MODE", True)

# STEP3 タッチスクリーンUI設定
DEMO_MODE = _env_bool("PANME_DEMO_MODE", True)
# Trueならデモ認証中でも商品・在庫・利用履歴はWeb APIを使用します。
USE_API = _env_bool("PANME_USE_API", False)
# コンテスト時だけ使う明示的な退避設定。API起動確認に失敗した場合にデモ商品へ戻します。
DEMO_API_FALLBACK = _env_bool("PANME_DEMO_API_FALLBACK", True)
# Falseならデモ商品の在庫を減らさず、同じ撮影を何度でも繰り返せます。
DEMO_DECREASE_STOCK = _env_bool("PANME_DEMO_DECREASE_STOCK", False)
DEMO_USER_ID = os.getenv("PANME_DEMO_USER_ID", "001")
DEMO_USER_NAME = os.getenv("PANME_DEMO_USER_NAME", "大崎　蒼")
DEMO_STUDENT_ID = os.getenv("PANME_DEMO_STUDENT_ID", "123456")
FULLSCREEN = _env_bool("PANME_FULLSCREEN", True)
SCREEN_TIMEOUT = _env_int("PANME_SCREEN_TIMEOUT", 60)
WELCOME_DISPLAY_SECONDS = 2.5
DEMO_AUTH_SECONDS = 3.0
COMPLETE_DISPLAY_SECONDS = 4.0
UI_TITLE = "PanMe"
UI_FONT_FAMILY = "Noto Sans CJK JP"
UI_BACKGROUND = "#FFF8ED"
UI_PRIMARY = "#F06B3B"
UI_SECONDARY = "#1F6F78"
UI_ACCENT = "#F6C453"
UI_TEXT = "#24323D"
UI_MUTED = "#6C7A80"
UI_CARD = "#FFFFFF"
UI_ERROR = "#B83A3A"
UI_LOG_PATH = "logs/ui_events.jsonl"

# STEP4 VPS / Web API設定
API_BASE_URL = os.getenv("PANME_API_BASE_URL", "").rstrip("/")
API_KEY = os.getenv("PANME_API_KEY", "")
DEVICE_ID = os.getenv("PANME_DEVICE_ID", "")
DEVICE_NAME = os.getenv("PANME_DEVICE_NAME", "PanMe Locker")
SOFTWARE_VERSION = os.getenv("PANME_SOFTWARE_VERSION", "4.0.0")
PRODUCTION_USER_ID = _env_int("PANME_USER_ID", 0)
AUTHENTICATION_METHOD = os.getenv("PANME_AUTHENTICATION_METHOD", "STEP4_DEMO")
CONNECT_TIMEOUT = float(os.getenv("PANME_API_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("PANME_API_READ_TIMEOUT", "10"))
MAX_RETRIES = max(1, min(3, _env_int("PANME_API_MAX_RETRIES", 3)))
HEARTBEAT_INTERVAL = max(30, _env_int("PANME_HEARTBEAT_INTERVAL", 30))
VERIFY_TLS = _env_bool("PANME_VERIFY_TLS", True)
CA_BUNDLE = os.getenv("PANME_CA_BUNDLE", "")


def validate_production_settings():
    missing = []
    if not API_BASE_URL:
        missing.append("PANME_API_BASE_URL")
    if not API_KEY or API_KEY.startswith("CHANGE_ME"):
        missing.append("PANME_API_KEY")
    if not DEVICE_ID:
        missing.append("PANME_DEVICE_ID")
    if PRODUCTION_USER_ID <= 0:
        missing.append("PANME_USER_ID")
    if missing:
        raise RuntimeError("本番モード設定が不足しています: " + ", ".join(missing))

# ロッカーIDとPCA9685チャンネルの対応表
LOCKER_CHANNELS = {
    "A-01": 0,
    "A-02": 1,
    "A-03": 2,
    "A-04": 3,
    "B-01": 4,
    "B-02": 5,
    "B-03": 6,
    "B-04": 7,
    "C-01": 8,
    "C-02": 9,
    "C-03": 10,
    "C-04": 11,
    "D-01": 12,
    "D-02": 13,
    "D-03": 14,
    "D-04": 15,
}
