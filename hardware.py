"""PCA9685・サーボ制御と起動前診断をまとめます。"""

import time
from threading import Lock

import config
import logging_utils as logger
from errors import (
    I2C_ERROR,
    INVALID_ANGLE,
    INVALID_CHANNEL,
    PCA9685_ERROR,
    SERVO_ERROR,
    PanMeHardwareError,
)


class PCA9685Controller:
    """ServoKitの初期化と、各チャンネルへの出力を管理します。"""

    CHANNELS = 16

    def __init__(self):
        self.kit = None
        self.i2c = None
        self.initialized = False

    def initialize(self):
        logger.info("ServoKitを初期化します")
        logger.info(f"PCA9685 Address: 0x{config.PCA9685_ADDRESS:02X}")

        if config.MOCK_MODE:
            self.initialized = True
            logger.mock("ServoKit initialized")
            return

        try:
            import board
            from adafruit_servokit import ServoKit

            self.i2c = board.I2C()
            self.kit = ServoKit(
                channels=self.CHANNELS,
                i2c=self.i2c,
                address=config.PCA9685_ADDRESS,
            )
            for channel in range(self.CHANNELS):
                self.kit.servo[channel].set_pulse_width_range(
                    config.SERVO_MIN_PULSE,
                    config.SERVO_MAX_PULSE,
                )
            self.initialized = True
            logger.info("ServoKitの初期化に成功しました")
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            raise PanMeHardwareError(
                PCA9685_ERROR,
                f"ServoKitを初期化できません: {exc}",
            ) from exc

    @staticmethod
    def _validate_channel(channel):
        if not isinstance(channel, int) or not 0 <= channel < 16:
            raise PanMeHardwareError(
                INVALID_CHANNEL,
                f"チャンネルは0～15で指定してください: {channel}",
            )

    def _ensure_initialized(self):
        if not self.initialized:
            raise PanMeHardwareError(
                PCA9685_ERROR,
                "ServoKitが初期化されていません",
            )

    def set_servo_angle(self, channel, angle):
        self._validate_channel(channel)
        self._ensure_initialized()

        if config.MOCK_MODE:
            logger.mock(f"Servo Channel: {channel}")
            logger.mock(f"Angle: {angle}")
            return

        try:
            self.kit.servo[channel].angle = angle
        except (OSError, ValueError, RuntimeError) as exc:
            raise PanMeHardwareError(
                I2C_ERROR,
                f"サーボ角度の書き込みに失敗しました: {exc}",
            ) from exc

    def set_pulse_us(self, channel, pulse_us):
        pulse_range = config.SERVO_MAX_PULSE - config.SERVO_MIN_PULSE
        if pulse_range <= 0:
            raise PanMeHardwareError(
                PCA9685_ERROR,
                "SERVO_MAX_PULSEはSERVO_MIN_PULSEより大きくしてください",
            )
        angle = (pulse_us - config.SERVO_MIN_PULSE) / pulse_range * 180
        self.set_servo_angle(channel, max(0, min(180, angle)))

    def release_channel(self, channel):
        self._validate_channel(channel)
        self._ensure_initialized()

        if config.MOCK_MODE:
            logger.mock(f"Release Channel: {channel}")
            return

        try:
            self.kit.servo[channel].angle = None
        except (OSError, ValueError, RuntimeError) as exc:
            raise PanMeHardwareError(
                I2C_ERROR,
                f"サーボ出力の停止に失敗しました: {exc}",
            ) from exc

    def close(self):
        if not self.initialized:
            return
        for channel in range(self.CHANNELS):
            try:
                self.release_channel(channel)
            except PanMeHardwareError as exc:
                logger.error(exc.message)
        self.kit = None
        if self.i2c is not None and hasattr(self.i2c, "deinit"):
            self.i2c.deinit()
        self.i2c = None
        self.initialized = False

    def health_check(self):
        if not self.initialized:
            return False
        if config.MOCK_MODE:
            return True
        if self.i2c is None:
            return False
        try:
            if not self.i2c.try_lock():
                return False
            try:
                return config.PCA9685_ADDRESS in self.i2c.scan()
            finally:
                self.i2c.unlock()
        except (OSError, ValueError, RuntimeError):
            return False


class ServoController:
    """PCA9685Controllerを角度単位で安全に操作します。"""

    def __init__(self, pca_controller):
        self.pca = pca_controller
        self._angles = {}
        self._last_operated_at = {}
        self._operation_lock = Lock()

    @staticmethod
    def _validate_angle(angle):
        if (
            isinstance(angle, bool)
            or not isinstance(angle, (int, float))
            or not 0 <= angle <= 180
        ):
            raise PanMeHardwareError(
                INVALID_ANGLE,
                f"サーボ角度は0～180度で指定してください: {angle}",
            )

    @staticmethod
    def angle_to_pulse(angle):
        ServoController._validate_angle(angle)
        pulse_range = config.SERVO_MAX_PULSE - config.SERVO_MIN_PULSE
        return config.SERVO_MIN_PULSE + pulse_range * (angle / 180)

    def _wait_for_safe_interval(self, channel):
        last_time = self._last_operated_at.get(channel)
        if last_time is None:
            return
        elapsed = time.monotonic() - last_time
        remaining = config.MIN_OPERATION_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            logger.info(f"連続動作防止のため {remaining:.1f} 秒待機します")
            time.sleep(remaining)

    def set_servo_angle(self, channel, angle):
        self._validate_angle(angle)
        with self._operation_lock:
            self._wait_for_safe_interval(channel)
            logger.info(f"Servo Channel: {channel}")
            logger.info(f"Servo Angle: {angle}")
            try:
                if hasattr(self.pca, "set_servo_angle"):
                    self.pca.set_servo_angle(channel, angle)
                else:
                    self.pca.set_pulse_us(channel, self.angle_to_pulse(angle))
                time.sleep(config.SERVO_MOVE_SECONDS)
                self._angles[channel] = angle
                self._last_operated_at[channel] = time.monotonic()
                if not config.SERVO_HOLD_ENABLED:
                    self.pca.release_channel(channel)
            except PanMeHardwareError:
                raise
            except Exception as exc:
                raise PanMeHardwareError(
                    SERVO_ERROR,
                    f"サーボ制御に失敗しました: {exc}",
                ) from exc

    def lock_servo(self, channel):
        self.set_servo_angle(channel, config.LOCK_ANGLE)

    def unlock_servo(self, channel):
        self.set_servo_angle(channel, config.UNLOCK_ANGLE)

    def move_locker(self, locker_id, channel, action):
        angles = config.LOCKER_ANGLES.get(locker_id, {})
        if action == "LOCK":
            angle = angles.get("lock", config.LOCK_ANGLE)
        elif action == "UNLOCK":
            angle = angles.get("unlock", config.UNLOCK_ANGLE)
        else:
            raise PanMeHardwareError(
                SERVO_ERROR,
                f"不正なサーボ操作です: {action}",
            )
        self.set_servo_angle(channel, angle)
        return angle

    def health_check(self):
        return self.pca.health_check()

    def release_servo(self, channel):
        self.pca.release_channel(channel)

    def get_servo_angle(self, channel):
        return self._angles.get(channel)


def run_diagnostics():
    """サーボを動かさず、設定・API・PCA9685を確認します。"""
    print("PanMe IoT Demo System - 起動前診断")
    print(
        f"Mode: DEMO={config.DEMO_MODE} "
        f"API={config.USE_API} MOCK={config.MOCK_MODE}"
    )
    if config.MOCK_MODE:
        print("PCA9685: SKIP (MOCKモードでは実機へ出力しません)")
        print("Raspberry Piでは .env の PANME_MOCK_MODE=false を確認してください")
        return 1

    expected_ids = [
        f"{row}-{column:02d}"
        for row in "ABCD"
        for column in range(1, 5)
    ]
    mapping_ok = list(config.LOCKER_CHANNELS) == expected_ids
    channels_ok = sorted(config.LOCKER_CHANNELS.values()) == list(range(16))
    print(f"16ロッカーID: {'OK' if mapping_ok else 'ERROR'}")
    print(f"PCA9685 CH0～15: {'OK' if channels_ok else 'ERROR'}")
    for locker_id, channel in config.LOCKER_CHANNELS.items():
        print(f"  {locker_id} -> CH{channel}")
    if not (mapping_ok and channels_ok):
        return 1

    pca = PCA9685Controller()
    try:
        pca.initialize()
        if not pca.health_check():
            print("PCA9685: ERROR")
            return 1
        print(f"PCA9685: OK (0x{config.PCA9685_ADDRESS:02X})")
    except PanMeHardwareError as exc:
        print(f"PCA9685: {exc.code} - {exc.message}")
        return 1
    finally:
        pca.close()

    if config.USE_API:
        try:
            import config as settings
            from api_client import PanMeApiClient

            settings.validate_production_settings()
            status = PanMeApiClient().health_check()
            if not status:
                if config.DEMO_MODE and config.DEMO_API_FALLBACK:
                    print("PanMe API: WARNING（起動時はデモ商品へ退避します）")
                else:
                    print("PanMe API: ERROR")
                    return 1
            else:
                print(f"PanMe API: OK ({settings.API_BASE_URL})")
        except Exception as exc:
            if config.DEMO_MODE and config.DEMO_API_FALLBACK:
                print(f"PanMe API: WARNING - {exc}")
                print("起動時はデモ商品へ退避します")
            else:
                print(f"PanMe API: ERROR - {exc}")
                return 1
    else:
        print("PanMe API: SKIP (デモ商品モード)")

    print("診断結果: 起動可能")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_diagnostics())
