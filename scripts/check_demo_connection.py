import requests

BASE_URL = "https://demo-api.binance.com/api"


def main():
    ping = requests.get(
        f"{BASE_URL}/v3/ping",
        timeout=10,
    )
    ping.raise_for_status()

    server_time = requests.get(
        f"{BASE_URL}/v3/time",
        timeout=10,
    )
    server_time.raise_for_status()

    print("Binance Demo connection: OK")
    print("Ping response:", ping.json())
    print("Server time:", server_time.json())


if __name__ == "__main__":
    main()
