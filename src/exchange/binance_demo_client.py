from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


load_dotenv()

class BinanceAPIError(RuntimeError):

    def __init__(
        self,
        *,
        status_code: int,
        code: int | None,
        message: str,
        body: str,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.body = body

        super().__init__(
            f"Binance API error "
            f"HTTP={status_code} "
            f"code={code} "
            f"message={message}"
        )

class BinanceDemoClient:
    """
    Minimal Binance Spot Demo REST client.

    Current capabilities:
    - Public market data
    - Exchange information
    - Account information
    - Open-order inspection

    No order placement methods are implemented yet.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: int = 10,
    ):
        self.base_url = (
            base_url
            or os.getenv("BINANCE_DEMO_BASE_URL")
            or "https://demo-api.binance.com/api"
        ).rstrip("/")

        self.api_key = api_key or os.getenv("BINANCE_API_KEY")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET")
        self.timeout = timeout

        trading_flag = os.getenv(
            "BINANCE_TRADING_ENABLED",
            "false",
        ).strip().lower()

        self.trading_enabled = (
            trading_flag
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        if not self.api_key:
            raise RuntimeError(
                "BINANCE_API_KEY is not configured."
            )

        if not self.api_secret:
            raise RuntimeError(
                "BINANCE_API_SECRET is not configured."
            )

        self.session = requests.Session()

        self.session.headers.update(
            {
                "X-MBX-APIKEY": self.api_key,
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:

        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout,
        )

        try:
            payload = response.json()

        except ValueError:
            payload = None

        if not response.ok:

            if isinstance(
                payload,
                dict,
            ):
                code = payload.get("code")
                message = payload.get(
                    "msg",
                    response.text,
                )

            else:
                code = None
                message = response.text

            raise BinanceAPIError(
                status_code=response.status_code,
                code=code,
                message=str(message),
                body=response.text,
            )

        return payload

    def get_server_time(self) -> int:
        data = self._request(
            "GET",
            "/v3/time",
        )

        return int(data["serverTime"])

    def get_exchange_info(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v3/exchangeInfo",
        )

    def _signed_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        signed_params = dict(params or {})

        signed_params.setdefault(
            "recvWindow",
            5000,
        )

        signed_params["timestamp"] = self.get_server_time()

        query_string = urlencode(signed_params)

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signed_params["signature"] = signature

        return self._request(
            method,
            path,
            params=signed_params,
        )

    def get_account(
        self,
        omit_zero_balances: bool = True,
    ) -> dict[str, Any]:
        return self._signed_request(
            "GET",
            "/v3/account",
            params={
                "omitZeroBalances": str(
                    omit_zero_balances
                ).lower(),
            },
        )

    def get_open_orders(
        self,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {}

        if symbol:
            params["symbol"] = symbol.upper()

        return self._signed_request(
            "GET",
            "/v3/openOrders",
            params=params,
        )
    
    def get_book_ticker(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v3/ticker/bookTicker",
            params={
                "symbol": symbol.upper(),
            },
        )

    def test_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        compute_commission_rates: bool = True,
    ) -> dict[str, Any]:

        side = side.upper()

        if side not in {"BUY", "SELL"}:
            raise ValueError(
                f"Unsupported side: {side}"
            )

        if (
            (quantity is None)
            == (quote_order_qty is None)
        ):
            raise ValueError(
                "Provide exactly one of "
                "quantity or quote_order_qty."
            )

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "computeCommissionRates": str(
                compute_commission_rates
            ).lower(),
        }

        if quantity is not None:
            params["quantity"] = quantity

        if quote_order_qty is not None:
            params["quoteOrderQty"] = (
                quote_order_qty
            )

        return self._signed_request(
            "POST",
            "/v3/order/test",
            params=params,
        )

    def assert_execution_ready(self) -> None:
        """
        Hard safety gate for order execution.
        """

        expected_demo_url = (
            "https://demo-api.binance.com/api"
        )

        if self.base_url != expected_demo_url:
            raise RuntimeError(
                "Order execution blocked: "
                "base URL is not Binance Demo."
            )

        if not self.trading_enabled:
            raise RuntimeError(
                "Order execution blocked: "
                "BINANCE_TRADING_ENABLED=false"
            )

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        client_order_id: str,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
    ) -> dict[str, Any]:

        self.assert_execution_ready()

        side = side.upper()
        symbol = symbol.upper()

        if side not in {
            "BUY",
            "SELL",
        }:
            raise ValueError(
                f"Unsupported side: {side}"
            )

        if not client_order_id.startswith(
            "IDXETF_"
        ):
            raise ValueError(
                "ETF order ID must start "
                "with IDXETF_."
            )

        if (
            (quantity is None)
            == (quote_order_qty is None)
        ):
            raise ValueError(
                "Provide exactly one of "
                "quantity or quote_order_qty."
            )

        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "newClientOrderId": (
                client_order_id
            ),
            "newOrderRespType": "FULL",
        }

        if quantity is not None:
            params["quantity"] = quantity

        if quote_order_qty is not None:
            params["quoteOrderQty"] = (
                quote_order_qty
            )

        return self._signed_request(
            "POST",
            "/v3/order",
            params=params,
        )

    def get_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any]:

        return self._signed_request(
            "GET",
            "/v3/order",
            params={
                "symbol": symbol.upper(),
                "origClientOrderId":
                    client_order_id,
            },
        )

    def get_order_if_exists(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any] | None:

        try:
            return self.get_order(
                symbol=symbol,
                client_order_id=client_order_id,
            )

        except BinanceAPIError as exc:

            if exc.code == -2013:
                return None

            raise

    def get_my_trades(
        self,
        *,
        symbol: str,
        order_id: int,
    ) -> list[dict[str, Any]]:

        return self._signed_request(
            "GET",
            "/v3/myTrades",
            params={
                "symbol": symbol.upper(),
                "orderId": order_id,
            },
        )