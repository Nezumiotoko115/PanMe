"""認証と商品取得をUIから分離するサービス。"""

import json
from abc import ABC, abstractmethod
from pathlib import Path

import config


class AuthenticationService(ABC):
    """将来DemoAuthenticationをNFCAuthenticationへ交換する境界です。"""

    @abstractmethod
    def authenticate(self):
        raise NotImplementedError


class DemoAuthentication(AuthenticationService):
    def authenticate(self):
        return {
            "user_id": config.DEMO_USER_ID,
            "user_name": config.DEMO_USER_NAME,
            "student_id": config.DEMO_STUDENT_ID,
            "authentication_method": "DEMO",
        }


class ProductService(ABC):
    """商品取得元をJSONから将来のPanMe APIへ交換する境界です。"""

    @abstractmethod
    def get_products(self):
        raise NotImplementedError

    @abstractmethod
    def decrease_stock(self, product_id):
        raise NotImplementedError


class DemoProductService(ProductService):
    def __init__(self, data_path=None):
        path = data_path or Path(__file__).resolve().parents[1] / "data" / "demo_products.json"
        self.data_path = Path(path)
        self._products = None

    def get_products(self):
        if self._products is None:
            with self.data_path.open(encoding="utf-8") as file:
                self._products = json.load(file)
        # UIが元データを直接書き換えないよう辞書をコピーします。
        return [dict(product) for product in self._products]

    def decrease_stock(self, product_id):
        if not config.DEMO_DECREASE_STOCK:
            # コンテスト撮影では同じ商品を繰り返し選べるよう、メモリ上の在庫も維持します。
            return next(
                (
                    dict(product)
                    for product in (self._products or self.get_products())
                    if product["product_id"] == product_id
                ),
                None,
            )
        if self._products is None:
            self.get_products()
        for product in self._products:
            if product["product_id"] == product_id:
                product["stock"] = max(0, product["stock"] - 1)
                if product["stock"] == 0:
                    product["status"] = "SOLD_OUT"
                return dict(product)
        return None
