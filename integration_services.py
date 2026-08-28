"""STEP4のAPI認証・商品・ロッカー・利用・イベントサービス。"""

import socket
import threading
import uuid
from datetime import datetime

import config
import config as settings
from api_client import PanMeApiError
from errors import failure
from ui.services import AuthenticationService, ProductService


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ApiAuthenticationService(AuthenticationService):
    def __init__(self, api_client):
        self.api = api_client

    def authenticate(self):
        return self.api.post(
            "/auth/verify",
            {
                "user_id": settings.PRODUCTION_USER_ID,
                "authentication_method": settings.AUTHENTICATION_METHOD,
            },
        )


class DemoApiAuthenticationService(ApiAuthenticationService):
    """APIで利用許可を得つつ、画面には固定デモユーザーを表示します。"""

    def authenticate(self):
        user = super().authenticate()
        user["user_name"] = config.DEMO_USER_NAME
        user["student_id"] = config.DEMO_STUDENT_ID
        user["authentication_method"] = "DEMO"
        return user


class ApiProductService(ProductService):
    def __init__(self, api_client):
        self.api = api_client
        self._products = []

    def get_products(self):
        rows = self.api.get("/products")
        self._products = [
            {
                "locker_id": row["locker_id"],
                "product_id": str(row["product_id"]),
                "product_name": row["product_name"],
                "category": row.get("category") or "商品",
                "stock": int(row["stock_quantity"]),
                "status": row["product_status"],
                "image": row.get("product_image"),
                "description": row.get("description") or "",
                "vendor_id": row.get("vendor_id"),
                "vendor_name": row.get("vendor_name"),
                "reservation_id": row.get("reservation_id"),
            }
            for row in rows
        ]
        return [dict(product) for product in self._products]

    def decrease_stock(self, product_id):
        # 在庫の正本はAPI側です。画面キャッシュだけを更新します。
        for product in self._products:
            if str(product["product_id"]) == str(product_id):
                product["stock"] = max(0, product["stock"] - 1)
                if product["stock"] == 0:
                    product["status"] = "SOLD_OUT"
                return dict(product)
        return None


class EventService:
    def __init__(self, api_client):
        self.api = api_client

    def send(
        self,
        event_type,
        transaction_id=None,
        user_id=None,
        locker_id=None,
        product_id=None,
        reservation_id=None,
        result=None,
        error_code=None,
        payload=None,
    ):
        event = {
            "event_id": str(uuid.uuid4()),
            "device_id": settings.DEVICE_ID,
            "event_type": event_type,
            "transaction_id": transaction_id,
            "user_id": user_id,
            "locker_id": locker_id,
            "product_id": product_id,
            "reservation_id": reservation_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
            "error_code": error_code,
            "payload": payload,
        }
        return self.api.post("/events", event)


class CompositeEventLogger:
    """既存UIログを残しながら、同じ操作をAPIイベントへ転送します。"""

    EVENT_MAP = {
        "AUTH_SUCCESS": "AUTH_SUCCESS",
        "AUTH_FAILED": "AUTH_FAILED",
        "PRODUCT_SELECTED": "PRODUCT_SELECTED",
        "ERROR": "ERROR",
    }

    def __init__(self, local_logger, event_service):
        self.local = local_logger
        self.events = event_service

    def write(self, event, **details):
        record = self.local.write(event, **details)
        remote_type = self.EVENT_MAP.get(event)
        if remote_type:
            try:
                self.events.send(remote_type, payload=details)
            except PanMeApiError:
                # UI操作を止めず、ローカルログを再送元として残します。
                pass
        return record


class ApiAuthorizedLockerService:
    """API許可を得てからだけSTEP2 LockerManagerを動かします。"""

    def __init__(self, local_manager, api_client, event_service):
        self.local = local_manager
        self.api = api_client
        self.events = event_service
        self._server_lockers = {}
        self._context = None
        self._transactions = {}
        self.api_online = False
        self.refresh()

    def refresh(self):
        try:
            lockers = self.api.get("/lockers")
            self._server_lockers = {row["locker_id"]: row for row in lockers}
            self.api_online = True
        except PanMeApiError:
            self.api_online = False
        return self.api_online

    def system_status(self):
        return "ONLINE" if self.api_online else "OFFLINE"

    def begin_usage(self, user, product):
        self._context = {"user": dict(user), "product": dict(product)}

    def get_locker_status(self, locker_id):
        local = self.local.get_locker_status(locker_id)
        server = self._server_lockers.get(locker_id)
        if not server:
            return local
        status = server["locker_status"]
        local.update(
            {
                "status": status,
                "enabled": status not in ("DISABLED", "MAINTENANCE", "ERROR"),
            }
        )
        return local

    def get_all_locker_status(self):
        return {
            locker_id: self.get_locker_status(locker_id)["status"]
            for locker_id in config.LOCKER_CHANNELS
        }

    def unlock_locker(self, locker_id):
        if not self.api_online or not self._context:
            return failure("API_ERROR", "APIへ接続できないため解錠できません", locker_id)
        user = self._context["user"]
        product = self._context["product"]
        idempotency_key = str(uuid.uuid4())
        try:
            authorization = self.api.post(
                f"/lockers/{locker_id}/unlock",
                {
                    "idempotency_key": idempotency_key,
                    "auth_token": user["auth_token"],
                    "user_id": int(user["user_id"]),
                    "product_id": int(product["product_id"]),
                    "reservation_id": product.get("reservation_id")
                    or user.get("reservation_id"),
                },
            )
            transaction_id = authorization["transaction_id"]
            self._transactions[locker_id] = transaction_id
            self.events.send(
                "UNLOCK_REQUESTED",
                transaction_id=transaction_id,
                user_id=user["user_id"],
                locker_id=locker_id,
                product_id=product["product_id"],
                reservation_id=product.get("reservation_id"),
                result="SUCCESS",
            )
            result = self.local.unlock_locker(locker_id)
            if result["success"]:
                self.events.send(
                    "UNLOCK_SUCCESS",
                    transaction_id=transaction_id,
                    user_id=user["user_id"],
                    locker_id=locker_id,
                    product_id=product["product_id"],
                    reservation_id=product.get("reservation_id"),
                    result="SUCCESS",
                )
                self._server_lockers.setdefault(locker_id, {})["locker_status"] = "UNLOCKED"
                return result
            self.events.send(
                "UNLOCK_FAILED",
                transaction_id=transaction_id,
                user_id=user["user_id"],
                locker_id=locker_id,
                product_id=product["product_id"],
                result="FAILED",
                error_code=result.get("error_code"),
            )
            return result
        except (PanMeApiError, KeyError, ValueError) as exc:
            code = getattr(exc, "code", "API_ERROR")
            return failure(code, str(exc), locker_id)

    def set_locker_status(self, locker_id, status):
        result = self.local.set_locker_status(locker_id, status)
        if result["success"]:
            self._server_lockers.setdefault(locker_id, {})["locker_status"] = status
        return result

    def mark_product_taken(self, locker_id):
        """利用者が受取完了を押した時点をサーバーへ記録します。"""
        transaction_id = self._transactions.get(locker_id)
        if not transaction_id:
            return failure("LOCKER_ERROR", "利用中の取引がありません", locker_id)
        try:
            product = self._context["product"]
            self.events.send(
                "PRODUCT_TAKEN",
                transaction_id=transaction_id,
                user_id=self._context["user"]["user_id"],
                locker_id=locker_id,
                product_id=product["product_id"],
                result="SUCCESS",
            )
            return {"success": True, "locker_id": locker_id}
        except PanMeApiError as exc:
            return failure(exc.code, exc.message, locker_id)

    def lock_locker(self, locker_id):
        transaction_id = self._transactions.get(locker_id)
        if not transaction_id:
            return failure("LOCKER_ERROR", "利用中の取引がありません", locker_id)
        result = self.local.lock_locker(locker_id)
        try:
            self.events.send(
                "LOCK_REQUESTED",
                transaction_id=transaction_id,
                locker_id=locker_id,
                result="SUCCESS",
            )
        except PanMeApiError:
            pass
        if not result["success"]:
            try:
                self.events.send(
                    "LOCK_FAILED",
                    transaction_id=transaction_id,
                    locker_id=locker_id,
                    result="FAILED",
                    error_code=result.get("error_code"),
                )
            except PanMeApiError:
                pass
            return result
        try:
            self.api.post(
                f"/lockers/{locker_id}/lock",
                {"transaction_id": transaction_id},
            )
            self.events.send(
                "LOCK_SUCCESS",
                transaction_id=transaction_id,
                locker_id=locker_id,
                result="SUCCESS",
            )
            self.api.post(
                f"/lockers/{locker_id}/complete",
                {"transaction_id": transaction_id},
            )
            self.events.send(
                "TRANSACTION_COMPLETED",
                transaction_id=transaction_id,
                user_id=self._context["user"]["user_id"],
                locker_id=locker_id,
                product_id=self._context["product"]["product_id"],
                result="SUCCESS",
            )
            self._server_lockers.setdefault(locker_id, {})["locker_status"] = "LOCKED"
            del self._transactions[locker_id]
            return result
        except PanMeApiError as exc:
            return failure(exc.code, exc.message, locker_id)


class DeviceStatusService:
    def __init__(self, api_client, pca_controller, event_service):
        self.api = api_client
        self.pca = pca_controller
        self.events = event_service
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _ip_address():
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None

    def report(self, status="ONLINE", error_message=None):
        return self.api.post(
            "/device/status",
            {
                "device_id": settings.DEVICE_ID,
                "device_name": settings.DEVICE_NAME,
                "status": status,
                "software_version": settings.SOFTWARE_VERSION,
                "ip_address": self._ip_address(),
                "pca9685_status": "OK" if self.pca.health_check() else "ERROR",
                "wifi_status": "ONLINE",
                "api_status": "ONLINE" if status == "ONLINE" else "OFFLINE",
                "error_message": error_message,
                "last_seen_at": _timestamp(),
            },
        )

    def start(self):
        try:
            self.report("ONLINE")
            self.events.send("DEVICE_STARTED", result="SUCCESS")
            self.events.send("DEVICE_ONLINE", result="SUCCESS")
        except PanMeApiError:
            # 起動時にAPIが停止中でも、UIを表示してハートビートで復旧を試します。
            pass

        def heartbeat():
            while not self._stop.wait(settings.HEARTBEAT_INTERVAL):
                try:
                    self.report("ONLINE")
                except PanMeApiError:
                    pass

        self._thread = threading.Thread(target=heartbeat, name="panme-heartbeat", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            self.events.send("DEVICE_OFFLINE", result="SUCCESS")
            self.report("OFFLINE")
        except PanMeApiError:
            pass
