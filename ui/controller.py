"""画面遷移とロッカー利用フローを管理するUI非依存コントローラー。"""

import threading

from locker_manager import CLOSED, ERROR, LOCKED, OPEN, UNLOCKED

IDLE = "IDLE"
AUTH = "AUTH"
WELCOME = "WELCOME"
PRODUCT_LIST = "PRODUCT_LIST"
PRODUCT_DETAIL = "PRODUCT_DETAIL"
LOCKER_CONFIRM = "LOCKER_CONFIRM"
UNLOCKING = "UNLOCKING"
UNLOCKED_SCREEN = "UNLOCKED"
TAKE_PRODUCT = "TAKE_PRODUCT"
CLOSE_LOCKER = "CLOSE_LOCKER"
LOCKING = "LOCKING"
COMPLETE = "COMPLETE"
ERROR_SCREEN = "ERROR"

UNSAFE_TIMEOUT_STATES = {
    UNLOCKING,
    UNLOCKED_SCREEN,
    TAKE_PRODUCT,
    CLOSE_LOCKER,
    LOCKING,
}


class PanMeController:
    """Tkinterを知らず、状態と業務ルールだけを扱います。"""

    def __init__(
        self,
        locker_manager,
        authentication_service,
        product_service,
        event_logger,
        schedule=None,
        background_runner=None,
    ):
        self.locker_manager = locker_manager
        self.authentication_service = authentication_service
        self.product_service = product_service
        self.event_logger = event_logger
        self.schedule = schedule or (lambda _delay, callback: callback())
        self.background_runner = background_runner or self._thread_runner
        self.state = IDLE
        self.user = None
        self.selected_product = None
        self.error_code = None
        self.on_change = lambda _controller: None

    @staticmethod
    def _thread_runner(job):
        threading.Thread(target=job, daemon=True).start()

    def _change(self, state):
        self.state = state
        self.on_change(self)

    def start(self):
        self.event_logger.write("APP_STARTED")
        self._change(IDLE)

    def begin(self):
        if self.state == IDLE:
            self._change(AUTH)

    def authenticate(self):
        try:
            self.user = self.authentication_service.authenticate()
        except Exception as exc:
            self.event_logger.write("AUTH_FAILED", error_code="AUTH_ERROR")
            self.show_error("AUTH_ERROR", str(exc))
            return
        self.event_logger.write(
            "AUTH_SUCCESS",
            user_id=self.user["user_id"],
            authentication_method=self.user["authentication_method"],
        )
        self._change(WELCOME)

    def show_products(self):
        self._change(PRODUCT_LIST)

    def products(self):
        try:
            return self.product_service.get_products()
        except Exception:
            return []

    def product_availability(self, product):
        locker = self.locker_manager.get_locker_status(product["locker_id"])
        if not locker["success"]:
            return False, "利用不可"
        if product["stock"] <= 0 or product["status"] == "SOLD_OUT":
            return False, "売り切れ"
        if not locker["enabled"] or locker["status"] == "DISABLED":
            return False, "メンテナンス中"
        if locker["status"] == ERROR:
            return False, "利用不可"
        if locker["status"] != LOCKED:
            return False, "使用中"
        return True, "利用できます"

    def select_product(self, product):
        available, _label = self.product_availability(product)
        if not available:
            return False
        self.selected_product = dict(product)
        self.event_logger.write(
            "PRODUCT_SELECTED",
            product_id=product["product_id"],
            locker_id=product["locker_id"],
        )
        self._change(PRODUCT_DETAIL)
        return True

    def confirm_product(self):
        if self.selected_product:
            self.event_logger.write(
                "LOCKER_SELECTED",
                locker_id=self.selected_product["locker_id"],
            )
            self._change(LOCKER_CONFIRM)

    def back(self):
        if self.state == PRODUCT_LIST:
            self.cancel_to_idle()
        elif self.state == PRODUCT_DETAIL:
            self._change(PRODUCT_LIST)
        elif self.state == LOCKER_CONFIRM:
            self._change(PRODUCT_DETAIL)

    def unlock(self):
        if self.state != LOCKER_CONFIRM or not self.selected_product:
            return
        locker_id = self.selected_product["locker_id"]
        begin_usage = getattr(self.locker_manager, "begin_usage", None)
        if begin_usage:
            begin_usage(self.user, self.selected_product)
        self.event_logger.write("UNLOCK_STARTED", locker_id=locker_id)
        self._change(UNLOCKING)

        def job():
            result = self.locker_manager.unlock_locker(locker_id)
            self.schedule(0, lambda: self._unlock_finished(result))

        self.background_runner(job)

    def _unlock_finished(self, result):
        if result["success"]:
            self.event_logger.write(
                "UNLOCK_SUCCESS",
                locker_id=self.selected_product["locker_id"],
            )
            self._change(UNLOCKED_SCREEN)
        else:
            self.show_error(result.get("error_code", "LOCKER_ERROR"), "解錠に失敗しました")

    def continue_to_take_product(self):
        if self.state == UNLOCKED_SCREEN:
            # センサーがないため、画面操作を扉OPENの代替入力にします。
            result = self.locker_manager.set_locker_status(
                self.selected_product["locker_id"], OPEN
            )
            if result["success"]:
                self._change(TAKE_PRODUCT)
            else:
                self.show_error(result.get("error_code"), "扉状態を更新できませんでした")

    def product_received(self):
        if self.state == TAKE_PRODUCT:
            marker = getattr(self.locker_manager, "mark_product_taken", None)
            if marker:
                result = marker(self.selected_product["locker_id"])
                if not result["success"]:
                    self.show_error(
                        result.get("error_code", "API_ERROR"),
                        "商品受取をサーバーへ記録できませんでした",
                    )
                    return
            self.event_logger.write(
                "PRODUCT_RECEIVED",
                product_id=self.selected_product["product_id"],
                locker_id=self.selected_product["locker_id"],
            )
            self._change(CLOSE_LOCKER)

    def close_and_lock(self):
        if self.state != CLOSE_LOCKER:
            return
        locker_id = self.selected_product["locker_id"]
        closed = self.locker_manager.set_locker_status(locker_id, CLOSED)
        if not closed["success"]:
            self.show_error(closed.get("error_code"), "扉状態を更新できませんでした")
            return
        self.event_logger.write("LOCK_STARTED", locker_id=locker_id)
        self._change(LOCKING)

        def job():
            result = self.locker_manager.lock_locker(locker_id)
            self.schedule(0, lambda: self._lock_finished(result))

        self.background_runner(job)

    def _lock_finished(self, result):
        if result["success"]:
            updated_product = self.product_service.decrease_stock(
                self.selected_product["product_id"]
            )
            self.event_logger.write(
                "INVENTORY_UPDATED",
                product_id=self.selected_product["product_id"],
                locker_id=self.selected_product["locker_id"],
                stock=(updated_product or {}).get("stock"),
            )
            self.event_logger.write(
                "LOCK_SUCCESS",
                locker_id=self.selected_product["locker_id"],
            )
            self.event_logger.write(
                "TRANSACTION_COMPLETED",
                user_id=self.user["user_id"],
                product_id=self.selected_product["product_id"],
                locker_id=self.selected_product["locker_id"],
                result="SUCCESS",
            )
            self._change(COMPLETE)
        else:
            self.show_error(result.get("error_code", "LOCKER_ERROR"), "施錠に失敗しました")

    def show_error(self, code, message):
        self.error_code = code
        self.event_logger.write(
            "ERROR",
            error_code=code,
            message=message,
            locker_id=(
                self.selected_product["locker_id"] if self.selected_product else None
            ),
        )
        self._change(ERROR_SCREEN)

    def cancel_to_idle(self):
        if self.state in UNSAFE_TIMEOUT_STATES:
            return False
        self.user = None
        self.selected_product = None
        self.error_code = None
        self._change(IDLE)
        return True

    def handle_timeout(self):
        """解錠後の危険な状態ではタイムアウトを無視します。"""
        if self.state == IDLE or self.state in UNSAFE_TIMEOUT_STATES:
            return False
        return self.cancel_to_idle()
