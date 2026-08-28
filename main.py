"""PanMe IoTロッカー STEP2 CLIプログラム。"""

import pprint
import sys
import time

import config
import logging_utils as logger
from errors import PanMeHardwareError
from hardware import PCA9685Controller, ServoController
from locker_manager import CLOSED, OPEN, LockerManager


HELP_TEXT = """
使用できるコマンド:
  unlock A-01             指定ロッカーを解錠
  lock A-01               指定ロッカーを施錠
  status A-01             指定ロッカーの詳細を表示
  status all              16室を4×4で表示
  set_status A-01 OPEN    扉状態を手動変更
  set_status A-01 CLOSED  扉状態を手動変更
  disable A-01            メンテナンス無効化
  enable A-01             有効化してLOCKEDへ戻す
  reset_error A-01        機器確認後にERRORを解除
  initialize all          確認後、16室を順番に施錠位置へ移動
  test all                確認後、16室を順番に解錠・施錠
  test channel            確認後、CH0～15を順番に確認
  queue                   操作キューの状態を表示
  help                    この説明を表示
  exit                    キュー完了後、安全停止して終了
""".strip()


def format_locker_grid(statuses):
    """ロッカー状態を物理配置と同じ4×4の表に整形します。"""
    width = 12
    top = "┌" + "┬".join("─" * width for _ in range(4)) + "┐"
    middle = "├" + "┼".join("─" * width for _ in range(4)) + "┤"
    bottom = "└" + "┴".join("─" * width for _ in range(4)) + "┘"
    lines = [top]
    locker_ids = list(config.LOCKER_CHANNELS)
    for row_index in range(4):
        row_ids = locker_ids[row_index * 4:(row_index + 1) * 4]
        lines.append("│" + "│".join(f" {item:<10}" for item in row_ids) + "│")
        lines.append(
            "│" + "│".join(f" {statuses[item]:<10}" for item in row_ids) + "│"
        )
        lines.append(bottom if row_index == 3 else middle)
    return "\n".join(lines)


class PanMeCLI:
    """ターミナル入力をLockerManagerの公開APIへ変換します。"""

    def __init__(self, manager, servo, input_function=input):
        self.manager = manager
        self.servo = servo
        self.input = input_function

    @staticmethod
    def _show(result):
        pprint.pprint(result, sort_dicts=False)

    def _confirm(self, message):
        answer = self.input(f"{message} (yes/no): ").strip().lower()
        if answer != "yes":
            print("キャンセルしました。")
            return False
        return True

    def initialize_all(self):
        if not self._confirm("16個のロッカーを順番に施錠位置へ初期化します。実行しますか？"):
            return
        for result in self.manager.initialize_all_lockers():
            self._show(result)

    def test_all_lockers(self):
        if not self._confirm("16個のロッカーを順番にテストします。実行しますか？"):
            return
        for locker_id in config.LOCKER_CHANNELS:
            print(f"\n--- {locker_id} ---")
            unlocked = self.manager.unlock_locker(locker_id)
            self._show(unlocked)
            if unlocked["success"]:
                time.sleep(config.ALL_TEST_INTERVAL_SECONDS)
                self._show(self.manager.lock_locker(locker_id))
            time.sleep(config.ALL_TEST_INTERVAL_SECONDS)
        print("16ロッカー一括テストが終了しました。")

    def test_channels(self):
        if not self._confirm("CH0～15を順番に動かします。実行しますか？"):
            return
        print("PCA9685チャンネルテストを開始します。")
        for channel in range(16):
            print(f"\n--- Channel {channel} ---")
            # 配線確認仕様どおり LOCK → UNLOCK の順で動かします。
            self.servo.lock_servo(channel)
            time.sleep(config.ALL_TEST_INTERVAL_SECONDS)
            self.servo.unlock_servo(channel)
            time.sleep(config.ALL_TEST_INTERVAL_SECONDS)
        print("PCA9685チャンネルテストが終了しました。")

    def execute(self, command_line):
        """1行のコマンドを解析し、終了時だけFalseを返します。"""
        parts = command_line.strip().split()
        if not parts:
            return True
        command = parts[0].lower()
        logger.info(f"Command: {command_line.strip()}")

        if command == "exit" and len(parts) == 1:
            return False
        if command == "help" and len(parts) == 1:
            print(HELP_TEXT)
        elif command == "queue" and len(parts) == 1:
            self._show(self.manager.queue_status())
        elif command == "status" and len(parts) == 2 and parts[1].lower() == "all":
            print(format_locker_grid(self.manager.get_all_locker_status()))
        elif command == "status" and len(parts) == 2:
            self._show(self.manager.get_locker_status(parts[1].upper()))
        elif command == "unlock" and len(parts) == 2:
            self._show(self.manager.unlock_locker(parts[1].upper()))
        elif command == "lock" and len(parts) == 2:
            self._show(self.manager.lock_locker(parts[1].upper()))
        elif command == "set_status" and len(parts) == 3:
            self._show(
                self.manager.set_locker_status(parts[1].upper(), parts[2].upper())
            )
        elif command == "disable" and len(parts) == 2:
            self._show(self.manager.disable_locker(parts[1].upper()))
        elif command == "enable" and len(parts) == 2:
            self._show(self.manager.enable_locker(parts[1].upper()))
        elif command == "reset_error" and len(parts) == 2:
            self._show(self.manager.reset_error(parts[1].upper()))
        elif command == "initialize" and len(parts) == 2 and parts[1].lower() == "all":
            self.initialize_all()
        elif command == "test" and len(parts) == 2 and parts[1].lower() == "all":
            self.test_all_lockers()
        elif command == "test" and len(parts) == 2 and parts[1].lower() == "channel":
            self.test_channels()
        else:
            print("コマンド形式が正しくありません。helpで確認してください。")
        return True


def run_cli():
    print("PanMe IoT Locker Control STEP2")
    logger.info("PanMe IoT Locker System Start")
    logger.info(f"Mode: {'MOCK' if config.MOCK_MODE else 'HARDWARE'}")

    pca = PCA9685Controller()
    manager = None
    try:
        pca.initialize()
        servo = ServoController(pca)
        manager = LockerManager(servo)
        cli = PanMeCLI(manager, servo)
        print(HELP_TEXT)
        while True:
            try:
                if not cli.execute(input("\n> ")):
                    break
            except PanMeHardwareError as exc:
                logger.error(f"{exc.code}: {exc.message}")
            except (EOFError, KeyboardInterrupt):
                print()
                break
    except PanMeHardwareError as exc:
        logger.error(f"{exc.code}: {exc.message}")
    finally:
        if manager is not None:
            manager.close()
        logger.info("全サーボのPWMを停止して終了します")
        pca.close()


if __name__ == "__main__":
    # STEP3では `python main.py` でUI、`python main.py --cli` で保守CLIを起動します。
    if "--check" in sys.argv:
        from hardware import run_diagnostics

        raise SystemExit(run_diagnostics())
    elif "--cli" in sys.argv:
        run_cli()
    else:
        from ui_main import run_ui

        raise SystemExit(run_ui())
