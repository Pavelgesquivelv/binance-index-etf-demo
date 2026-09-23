from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.execution.execution_metrics import (
    calculate_execution_metrics,
    value_commission_usdc,
)


def main():

    # =====================================================
    # BUY example
    #
    # bid     = 100
    # ask     = 101
    # mid     = 100.5
    #
    # qty     = 2
    # avg fill= 101.2
    #
    # spread cost:
    # (101 - 100.5) * 2 = 1.0
    #
    # slippage:
    # (101.2 - 101) * 2 = 0.4
    #
    # execution vs mid:
    # (101.2 - 100.5) * 2 = 1.4
    #
    # fee = 0.5
    #
    # implementation shortfall = 1.9
    # =====================================================

    buy = calculate_execution_metrics(
        side="BUY",
        quantity=Decimal("2"),
        quote_quantity=Decimal(
            "202.4"
        ),
        bid=Decimal("100"),
        ask=Decimal("101"),
        mid=Decimal("100.5"),
        fee_cost_usdc=Decimal(
            "0.5"
        ),
    )

    assert (
        buy.average_fill_price
        == Decimal("101.2")
    )

    assert (
        buy.spread_cost_usdc
        == Decimal("1.0")
    )

    assert (
        buy.slippage_cost_usdc
        == Decimal("0.4")
    )

    assert (
        buy.execution_cost_vs_mid_usdc
        == Decimal("1.4")
    )

    assert (
        buy.implementation_shortfall_usdc
        == Decimal("1.9")
    )

    # =====================================================
    # SELL example
    #
    # bid = 100
    # ask = 101
    # mid = 100.5
    #
    # qty = 2
    # avg fill = 99.8
    #
    # spread cost:
    # (100.5 - 100) * 2 = 1.0
    #
    # slippage:
    # (100 - 99.8) * 2 = 0.4
    #
    # execution vs mid:
    # (100.5 - 99.8) * 2 = 1.4
    # =====================================================

    sell = calculate_execution_metrics(
        side="SELL",
        quantity=Decimal("2"),
        quote_quantity=Decimal(
            "199.6"
        ),
        bid=Decimal("100"),
        ask=Decimal("101"),
        mid=Decimal("100.5"),
        fee_cost_usdc=Decimal(
            "0.5"
        ),
    )

    assert (
        sell.average_fill_price
        == Decimal("99.8")
    )

    assert (
        sell.spread_cost_usdc
        == Decimal("1.0")
    )

    assert (
        sell.slippage_cost_usdc
        == Decimal("0.4")
    )

    assert (
        sell.execution_cost_vs_mid_usdc
        == Decimal("1.4")
    )

    assert (
        sell.implementation_shortfall_usdc
        == Decimal("1.9")
    )

    # =====================================================
    # Fee valuation
    # =====================================================

    bnb_fee = value_commission_usdc(
        commission=Decimal(
            "0.001"
        ),
        commission_asset="BNB",
        base_asset="BTC",
        quote_asset="USDC",
        benchmark_mid=Decimal(
            "87000"
        ),
        bnb_mid_usdc=Decimal(
            "800"
        ),
    )

    assert (
        bnb_fee
        == Decimal("0.8")
    )

    base_asset_fee = (
        value_commission_usdc(
            commission=Decimal(
                "0.00001"
            ),
            commission_asset="BTC",
            base_asset="BTC",
            quote_asset="USDC",
            benchmark_mid=Decimal(
                "87000"
            ),
            bnb_mid_usdc=Decimal(
                "800"
            ),
        )
    )

    assert (
        base_asset_fee
        == Decimal("0.87")
    )

    usdc_fee = value_commission_usdc(
        commission=Decimal(
            "0.25"
        ),
        commission_asset="USDC",
        base_asset="BTC",
        quote_asset="USDC",
        benchmark_mid=Decimal(
            "87000"
        ),
        bnb_mid_usdc=Decimal(
            "800"
        ),
    )

    assert (
        usdc_fee
        == Decimal("0.25")
    )

    print("=" * 80)
    print(
        "EXECUTION METRICS TEST"
    )
    print("=" * 80)

    print()
    print("BUY")
    print(
        f"Average fill          : "
        f"{buy.average_fill_price}"
    )
    print(
        f"Spread cost           : "
        f"{buy.spread_cost_usdc}"
    )
    print(
        f"Slippage beyond ask   : "
        f"{buy.slippage_cost_usdc}"
    )
    print(
        f"Execution vs mid      : "
        f"{buy.execution_cost_vs_mid_usdc}"
    )
    print(
        f"Fee cost              : "
        f"{buy.fee_cost_usdc}"
    )
    print(
        f"Implementation "
        f"shortfall : "
        f"{buy.implementation_shortfall_usdc}"
    )
    print(
        f"Shortfall bps         : "
        f"{buy.implementation_shortfall_bps}"
    )

    print()
    print("SELL")
    print(
        f"Average fill          : "
        f"{sell.average_fill_price}"
    )
    print(
        f"Spread cost           : "
        f"{sell.spread_cost_usdc}"
    )
    print(
        f"Slippage beyond bid   : "
        f"{sell.slippage_cost_usdc}"
    )
    print(
        f"Execution vs mid      : "
        f"{sell.execution_cost_vs_mid_usdc}"
    )
    print(
        f"Implementation "
        f"shortfall : "
        f"{sell.implementation_shortfall_usdc}"
    )

    print()
    print("FEE VALUATION")
    print(
        f"BNB fee  -> "
        f"{bnb_fee} USDC"
    )
    print(
        f"BTC fee  -> "
        f"{base_asset_fee} USDC"
    )
    print(
        f"USDC fee -> "
        f"{usdc_fee} USDC"
    )

    print()
    print(
        "EXECUTION METRICS: OK"
    )


if __name__ == "__main__":
    main()
