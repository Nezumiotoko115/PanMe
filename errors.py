"""PanMe内で使用するエラーコードと例外。"""

PCA9685_ERROR = "PCA9685_ERROR"
I2C_ERROR = "I2C_ERROR"
INVALID_LOCKER = "INVALID_LOCKER"
INVALID_CHANNEL = "INVALID_CHANNEL"
INVALID_ANGLE = "INVALID_ANGLE"
SERVO_ERROR = "SERVO_ERROR"
LOCKER_ERROR = "LOCKER_ERROR"
LOCKER_BUSY = "LOCKER_BUSY"
ALREADY_LOCKED = "ALREADY_LOCKED"
ALREADY_UNLOCKED = "ALREADY_UNLOCKED"
LOCKER_DISABLED = "LOCKER_DISABLED"


class PanMeHardwareError(Exception):
    """画面やCLIへエラーコードを渡しやすくする独自例外です。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def success(**values):
    """成功結果を表す辞書を作ります。"""
    result = {"success": True}
    result.update(values)
    return result


def failure(code, message, locker_id=None):
    """失敗結果を統一形式の辞書で作ります。"""
    result = {
        "success": False,
        "error_code": code,
        "message": message,
    }
    if locker_id is not None:
        result["locker_id"] = locker_id
    return result
