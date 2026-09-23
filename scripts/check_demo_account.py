import hashlib
import hmac
import os
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("BINANCE_DEMO_BASE_URL")
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")


def validate_environment():
    required = {
        "BINANCE_DEMO_BASE_URL": BASE_URL,
        "BINANCE_API_KEY": API_KEY,
        "BINANCE_API_SECRET": API_SECRET,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}"
        )


def get_server_time():
    response = requests.get(
        f"{BASE_URL}/v3/time",
        timeout=10,
    )
    response.raise_for_status()

    return response.json()["serverTime"]


def sign_params(params):
    query_string = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature


def get_account():
    server_time = get_server_time()

    params = {
        "omitZeroBalances": "true",
        "recvWindow": 5000,
        "timestamp": server_time,
    }

    params["signature"] = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    response = requests.get(
        f"{BASE_URL}/v3/account",
        headers=headers,
        params=params,
        timeout=10,
    )

    if not response.ok:
        print("Binance error:")
        print(response.status_code)
        print(response.text)
        response.raise_for_status()

    return response.json()


def main():
    validate_environment()

    account = get_account()

    print("Binance Demo authenticated connection: OK")
    print()
    print(f"Can trade: {account.get('canTrade')}")
    print(f"Can deposit: {account.get('canDeposit')}")
    print(f"Can withdraw: {account.get('canWithdraw')}")
    print()

    print("Commission rates:")
    print(account.get("commissionRates"))
    print()

    print("Non-zero balances:")

    balances = account.get("balances", [])

    if not balances:
        print("No non-zero balances found.")
        return

    for balance in balances:
        asset = balance["asset"]
        free = balance["free"]
        locked = balance["locked"]

        print(
            f"{asset:10} "
            f"free={free:>20} "
            f"locked={locked:>20}"
        )


if __name__ == "__main__":
    main()
