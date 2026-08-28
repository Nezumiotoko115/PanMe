"""PanMe PHP APIへ接続する、タイムアウト・リトライ付きクライアント。"""

import time

try:
    import requests
except ImportError:
    requests = None

import config as settings


class PanMeApiError(Exception):
    def __init__(self, code, message, status_code=0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class PanMeApiClient:
    def __init__(self, session=None, sleep=time.sleep):
        if session is None and requests is None:
            raise RuntimeError(
                "API連携にはrequestsが必要です。pip install -r requirements.txt を実行してください。"
            )
        self.session = session or requests.Session()
        self.sleep = sleep
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Device-ID": settings.DEVICE_ID,
                "X-API-Key": settings.API_KEY,
            }
        )

    @property
    def verify(self):
        return settings.CA_BUNDLE or settings.VERIFY_TLS

    def request(self, method, path, payload=None):
        url = settings.API_BASE_URL + "/api/iot" + path
        last_error = None
        for attempt in range(settings.MAX_RETRIES):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=payload,
                    timeout=(settings.CONNECT_TIMEOUT, settings.READ_TIMEOUT),
                    verify=self.verify,
                )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise PanMeApiError(
                        "API_ERROR", "API response was not JSON", response.status_code
                    ) from exc
                if 200 <= response.status_code < 300 and body.get("success"):
                    return body.get("data")
                error = body.get("error") or {}
                api_error = PanMeApiError(
                    error.get("code", "API_ERROR"),
                    error.get("message", "API request failed"),
                    response.status_code,
                )
                # 認証・入力・競合エラーは再送しても改善しないため即時終了します。
                if response.status_code < 500:
                    raise api_error
                last_error = api_error
            except (
                (requests.Timeout, requests.ConnectionError)
                if requests is not None
                else (TimeoutError, ConnectionError)
            ) as exc:
                last_error = PanMeApiError("API_ERROR", str(exc))
            if attempt + 1 < settings.MAX_RETRIES:
                self.sleep(0.5 * (2 ** attempt))
        raise last_error or PanMeApiError("API_ERROR", "API request failed")

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, payload):
        return self.request("POST", path, payload)

    def health_check(self):
        try:
            return self.get("/status")
        except PanMeApiError:
            return None
