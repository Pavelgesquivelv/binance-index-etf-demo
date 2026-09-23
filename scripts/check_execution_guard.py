from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)


def main():
    client = BinanceDemoClient()

    print("=" * 70)
    print("ETF EXECUTION SAFETY CHECK")
    print("=" * 70)

    print()
    print(
        f"Base URL        : "
        f"{client.base_url}"
    )

    print(
        f"Trading enabled : "
        f"{client.trading_enabled}"
    )

    print()

    try:
        client.assert_execution_ready()

    except RuntimeError as exc:

        print("Execution status : BLOCKED")
        print(f"Reason           : {exc}")

        print()
        print(
            "Safety guard: OK"
        )

        print(
            "No order request was sent."
        )

        return

    print(
        "Execution status : ENABLED"
    )

    print()
    print(
        "WARNING: order execution "
        "is currently enabled."
    )


if __name__ == "__main__":
    main()
