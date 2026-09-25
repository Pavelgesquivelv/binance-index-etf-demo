from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


from src.dashboard.data import (
    load_dashboard_snapshot,
)


ZERO = Decimal("0")

DISPLAY_TIMEZONE = (
    "America/Mexico_City"
)


def local_timestamp(
    value,
) -> str:

    if not value:
        return "N/A"

    timestamp = pd.to_datetime(
        value,
        format="mixed",
        utc=True,
    )

    timestamp = (
        timestamp.tz_convert(
            DISPLAY_TIMEZONE
        )
    )

    return timestamp.strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def age_label(
    minutes,
) -> str:

    if minutes is None:
        return "No snapshot"

    if minutes < 1:
        return "<1 min ago"

    if minutes < 60:
        return (
            f"{minutes:.0f} min ago"
        )

    hours = minutes / 60

    if hours < 24:
        return (
            f"{hours:.1f} h ago"
        )

    days = hours / 24

    return (
        f"{days:.1f} d ago"
    )


st.set_page_config(
    page_title="Crypto Index ETF Demo",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def money(
    value,
    decimals: int = 2,
) -> str:

    if value is None:
        return "N/A"

    return (
        f"{float(value):,.{decimals}f}"
    )


def pct(
    value,
    decimals: int = 2,
) -> str:

    if value is None:
        return "N/A"

    return (
        f"{float(value):,.{decimals}f}%"
    )


def bool_status(
    enabled: bool,
) -> str:

    return (
        "ENABLED"
        if enabled
        else "DISABLED"
    )


@st.cache_data(
    ttl=15,
    show_spinner=False,
)
def load_data():

    return load_dashboard_snapshot(
        ROOT
    )


with st.sidebar:

    st.title(
        "Crypto Index ETF"
    )

    st.caption(
        "Binance Demo · Read-only monitoring"
    )

    if st.button(
        "↻ Refresh",
        width="stretch",
    ):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    st.caption(
        "Dashboard does not submit orders "
        "or mutate the ETF ledger."
    )


try:

    data = load_data()

except Exception as exc:

    st.error(
        "Dashboard data load failed."
    )

    st.exception(exc)

    st.stop()


st.title(
    "Crypto Index ETF Demo"
)

st.caption(
    "Indicative live valuation + "
    "authoritative ETF SQLite ledger"
)


if data["live_error"]:

    st.warning(
        "Binance live data is unavailable. "
        "SQLite historical data is still "
        "available."
    )

    st.code(
        data["live_error"]
    )


# ======================================================
# Status strip
# ======================================================

status_cols = st.columns(6)

with status_cols[0]:

    if data[
        "current_feed_processed"
    ]:

        st.success(
            "✓ Index portfolio processed"
        )

    else:

        st.warning(
            "Index portfolio pending"
        )


with status_cols[1]:

    if data[
        "physical_backing_ok"
    ]:

        st.success(
            "✓ Physical backing OK"
        )

    else:

        st.error(
            "Physical backing issue"
        )


with status_cols[2]:

    if (
        data["recoverable_orders"]
        == 0
    ):

        st.success(
            "✓ Recoverable orders: 0"
        )

    else:

        st.error(
            f"Recoverable orders: "
            f"{data['recoverable_orders']}"
        )


with status_cols[3]:

    latest_contribution = (
        data["latest_contribution"]
    )

    if latest_contribution:

        st.info(
            "Contribution: "
            + latest_contribution[
                "status"
            ]
        )

    else:

        st.info(
            "Contribution: NOT STARTED"
        )


with status_cols[4]:

    age_minutes = (
        data[
            "valuation_age_minutes"
        ]
    )

    if age_minutes is None:

        st.warning(
            "Valuation: NO DATA"
        )

    elif age_minutes <= 90:

        st.success(
            "✓ Valuation fresh"
        )

    elif age_minutes <= 180:

        st.warning(
            "Valuation getting stale"
        )

    else:

        st.error(
            "Valuation stale"
        )


with status_cols[5]:

    if any(
        data["flags"].values()
    ):

        st.warning(
            "Automation / trading enabled"
        )

    else:

        st.success(
            "🔒 Execution disabled"
        )


st.caption(
    "Last persisted valuation: "
    + (
        local_timestamp(
            data[
                "latest_valuation_at_utc"
            ]
        )
        if data[
            "latest_valuation_at_utc"
        ]
        else "No snapshot"
    )
    + " · "
    + age_label(
        data[
            "valuation_age_minutes"
        ]
    )
)


tabs = st.tabs(
    [
        "Overview",
        "Portfolio",
        "Contributions",
        "Rebalances",
        "Execution",
        "Safety",
    ]
)


# ======================================================
# OVERVIEW
# ======================================================

with tabs[0]:

    st.subheader(
        "Fund overview"
    )

    metric_top = st.columns(3)

    metric_top[0].metric(
        "Live NAV (USDC)",
        money(
            data["live_nav"],
            2,
        ),
    )

    metric_top[1].metric(
        "Live NAV / share (USDC)",
        money(
            data[
                "live_nav_per_share"
            ],
            4,
        ),
    )

    metric_top[2].metric(
        "Market value (USDC)",
        money(
            data[
                "live_market_value"
            ],
            2,
        ),
    )

    metric_bottom = st.columns(3)

    metric_bottom[0].metric(
        "ETF cash (USDC)",
        money(
            data["cash"],
            4,
        ),
    )

    metric_bottom[1].metric(
        "Shares outstanding",
        money(
            data["shares"],
            4,
        ),
    )

    metric_bottom[2].metric(
        "Index level",
        money(
            data["index_level"],
            6,
        ),
    )

    st.divider()

    left, right = st.columns(
        [2, 1]
    )

    with left:

        st.subheader(
            "Performance history"
        )

        control_left, control_right = (
            st.columns([2, 1])
        )

        with control_left:

            metric_choice = st.radio(
                "Metric",
                [
                    "NAV / share",
                    "NAV",
                ],
                horizontal=True,
                label_visibility="collapsed",
            )

        with control_right:

            range_choice = st.selectbox(
                "Range",
                [
                    "1D",
                    "7D",
                    "30D",
                    "ALL",
                ],
                index=1,
                label_visibility="collapsed",
            )

        valuation_rows = list(
            data[
                "valuation_history"
            ]
        )

        # Add the current live valuation
        # as an ephemeral endpoint.
        # It is NOT written to SQLite here.
        if (
            data["live_nav"]
            is not None
            and data[
                "live_nav_per_share"
            ]
            is not None
        ):

            valuation_rows.append(
                {
                    "captured_at_utc":
                        pd.Timestamp.now(
                            tz="UTC"
                        ).isoformat(),

                    "nav_usdc":
                        str(
                            data[
                                "live_nav"
                            ]
                        ),

                    "nav_per_share_usdc":
                        str(
                            data[
                                "live_nav_per_share"
                            ]
                        ),

                    "valuation_source":
                        "LIVE_DASHBOARD",
                }
            )

        if valuation_rows:

            valuation_df = (
                pd.DataFrame(
                    valuation_rows
                )
            )

            valuation_df[
                "captured_at_utc"
            ] = pd.to_datetime(
                valuation_df[
                    "captured_at_utc"
                ],
                format="mixed",
                utc=True,
            )

            valuation_df[
                "captured_at_local"
            ] = (
                valuation_df[
                    "captured_at_utc"
                ]
                .dt.tz_convert(
                    DISPLAY_TIMEZONE
                )
            )

            valuation_df[
                "nav_usdc"
            ] = pd.to_numeric(
                valuation_df[
                    "nav_usdc"
                ]
            )

            valuation_df[
                "nav_per_share_usdc"
            ] = pd.to_numeric(
                valuation_df[
                    "nav_per_share_usdc"
                ]
            )

            valuation_df = (
                valuation_df
                .sort_values(
                    "captured_at_utc"
                )
                .drop_duplicates(
                    subset=[
                        "captured_at_utc"
                    ],
                    keep="last",
                )
            )

            now_utc = pd.Timestamp.now(
                tz="UTC"
            )

            if range_choice == "1D":
                cutoff_chart = (
                    now_utc
                    - pd.Timedelta(
                        days=1
                    )
                )

            elif range_choice == "7D":
                cutoff_chart = (
                    now_utc
                    - pd.Timedelta(
                        days=7
                    )
                )

            elif range_choice == "30D":
                cutoff_chart = (
                    now_utc
                    - pd.Timedelta(
                        days=30
                    )
                )

            else:
                cutoff_chart = None

            if cutoff_chart is not None:

                valuation_df = (
                    valuation_df[
                        valuation_df[
                            "captured_at_utc"
                        ]
                        >= cutoff_chart
                    ]
                )

            if metric_choice == (
                "NAV / share"
            ):

                y_column = (
                    "nav_per_share_usdc"
                )

                y_label = (
                    "NAV / share (USDC)"
                )

            else:

                y_column = (
                    "nav_usdc"
                )

                y_label = (
                    "NAV (USDC)"
                )

            fig = px.line(
                valuation_df,
                x="captured_at_local",
                y=y_column,
                markers=True,
                labels={
                    "captured_at_local":
                        "CDMX time",
                    y_column:
                        y_label,
                },
            )

            fig.update_layout(
                margin=dict(
                    l=0,
                    r=0,
                    t=10,
                    b=0,
                ),
                showlegend=False,
            )

            st.plotly_chart(
                fig,
                width="stretch",
            )

            st.caption(
                "Hourly indicative valuations "
                "use ETF ledger quantities and "
                "Binance Demo mid prices. "
                "The final point is the current "
                "live dashboard valuation."
            )

        else:

            st.info(
                "No indicative valuation "
                "history yet."
            )

    with right:

        st.subheader(
            "Current index"
        )

        st.metric(
            "Completed run",
            (
                data["completed_run_id"]
                if data[
                    "completed_run_id"
                ]
                is not None
                else "Pending"
            ),
        )

        st.write(
            "**Portfolio cutoff · CDMX**"
        )

        st.code(
            local_timestamp(
                data[
                    "feed_cutoff_utc"
                ]
            )
        )

        st.write(
            "**Completed at · CDMX**"
        )

        st.code(
            (
                local_timestamp(
                    data[
                        "completed_at_utc"
                    ]
                )
                if data[
                    "completed_at_utc"
                ]
                else "Pending"
            )
        )

        st.write(
            "**Feed age**"
        )

        st.write(
            f"{data['feed_age_hours']:.1f} hours"
        )

        if data[
            "current_feed_processed"
        ]:

            st.caption(
                "Old feed age is informational "
                "because this cutoff has already "
                "been successfully processed."
            )


# ======================================================
# PORTFOLIO
# ======================================================

with tabs[1]:

    st.subheader(
        "ETF portfolio"
    )

    portfolio_rows = []

    for row in data["portfolio"]:

        portfolio_rows.append(
            {
                "Asset":
                    row["asset"],

                "Quantity":
                    float(
                        row["quantity"]
                    ),

                "Avg Cost":
                    float(
                        row[
                            "average_cost_usdc"
                        ]
                    ),

                "Live Price":
                    (
                        float(
                            row[
                                "mid_price_usdc"
                            ]
                        )
                        if row[
                            "mid_price_usdc"
                        ]
                        is not None
                        else None
                    ),

                "Market Value":
                    (
                        float(
                            row[
                                "market_value_usdc"
                            ]
                        )
                        if row[
                            "market_value_usdc"
                        ]
                        is not None
                        else None
                    ),

                "Current Weight":
                    (
                        float(
                            row[
                                "current_weight_pct"
                            ]
                        )
                        if row[
                            "current_weight_pct"
                        ]
                        is not None
                        else None
                    ),

                "Target Weight":
                    float(
                        row[
                            "target_weight_pct"
                        ]
                    ),

                "Drift":
                    (
                        float(
                            row[
                                "weight_drift_pct"
                            ]
                        )
                        if row[
                            "weight_drift_pct"
                        ]
                        is not None
                        else None
                    ),
            }
        )

    portfolio_df = pd.DataFrame(
        portfolio_rows
    )

    st.dataframe(
        portfolio_df.style.format(
            {
                "Quantity":
                    "{:,.8f}",
                "Avg Cost":
                    "{:,.4f}",
                "Live Price":
                    "{:,.4f}",
                "Market Value":
                    "{:,.2f}",
                "Current Weight":
                    "{:,.2f}%",
                "Target Weight":
                    "{:,.2f}%",
                "Drift":
                    "{:+,.2f}%",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    if not portfolio_df.empty:

        weight_df = (
            portfolio_df[
                [
                    "Asset",
                    "Current Weight",
                    "Target Weight",
                ]
            ]
            .melt(
                id_vars="Asset",
                var_name="Weight Type",
                value_name="Weight",
            )
        )

        fig = px.bar(
            weight_df,
            x="Asset",
            y="Weight",
            color="Weight Type",
            barmode="group",
            labels={
                "Weight":
                    "Weight (%)",
            },
        )

        fig.update_layout(
            margin=dict(
                l=0,
                r=0,
                t=20,
                b=0,
            )
        )

        st.plotly_chart(
            fig,
            width="stretch",
        )

    st.caption(
        "Current weights use ETF ledger "
        "quantities and live Binance Demo "
        "mid prices. They do not infer ETF "
        "ownership from exchange balances."
    )


# ======================================================
# CONTRIBUTIONS
# ======================================================

with tabs[2]:

    st.subheader(
        "Cash contributions"
    )

    schedule = data["schedule"]

    if schedule:

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Frequency",
            schedule.get(
                "frequency",
                "N/A",
            ),
        )

        c2.metric(
            "Schedule",
            (
                f"{schedule.get('weekday', '')} "
                f"{schedule.get('time_local', '')}"
            ),
        )

        c3.metric(
            "Timezone",
            schedule.get(
                "timezone",
                "N/A",
            ),
        )

    if not data["contributions"]:

        st.info(
            "No weekly cash contribution "
            "has been accepted yet."
        )

    else:

        contribution_df = (
            pd.DataFrame(
                data["contributions"]
            )
        )

        preferred = [
            "id",
            "period_id",
            "scheduled_at_utc",
            "expected_amount",
            "detected_amount",
            "accepted_amount",
            "shares_issued",
            "status",
            "accepted_at_utc",
            "completed_at_utc",
        ]

        preferred = [
            column
            for column in preferred
            if column
            in contribution_df.columns
        ]

        st.dataframe(
            contribution_df[
                preferred
            ],
            width="stretch",
            hide_index=True,
        )


# ======================================================
# REBALANCES
# ======================================================

with tabs[3]:

    st.subheader(
        "Index rebalances"
    )

    if not data["rebalances"]:

        st.info(
            "No rebalance runs."
        )

    else:

        rebalance_df = pd.DataFrame(
            data["rebalances"]
        )

        st.dataframe(
            rebalance_df,
            width="stretch",
            hide_index=True,
        )


# ======================================================
# EXECUTION
# ======================================================

with tabs[4]:

    st.subheader(
        "Order execution"
    )

    if not data["orders"]:

        st.info(
            "No ETF orders."
        )

    else:

        execution_df = pd.DataFrame(
            data["orders"]
        )

        preferred = [
            "id",
            "owner_type",
            "client_order_id",
            "symbol",
            "side",
            "requested_quote_quantity",
            "exchange_status",
            "executed_quantity",
            "cumulative_quote_quantity",
            "local_status",
            "fill_count",
            "benchmark_mid",
            "spread_bps",
            "created_at_utc",
        ]

        st.dataframe(
            execution_df[
                preferred
            ],
            width="stretch",
            hide_index=True,
        )

    if data["fees"]:

        st.subheader(
            "Recorded commissions"
        )

        fees_df = pd.DataFrame(
            data["fees"]
        )

        st.dataframe(
            fees_df,
            width="stretch",
            hide_index=True,
        )


# ======================================================
# SAFETY
# ======================================================

with tabs[5]:

    st.subheader(
        "Safety & physical backing"
    )

    flag_cols = st.columns(3)

    names = [
        "BINANCE_TRADING_ENABLED",
        "ETF_WEEKLY_AUTOMATION_ENABLED",
        "ETF_CONTRIBUTION_EXECUTION_ENABLED",
    ]

    for column, name in zip(
        flag_cols,
        names,
    ):

        enabled = (
            data["flags"][name]
        )

        column.metric(
            name,
            bool_status(enabled),
        )

    if any(
        data["flags"].values()
    ):

        st.warning(
            "At least one execution or "
            "automation gate is enabled."
        )

    else:

        st.success(
            "All execution and automation "
            "gates are disabled."
        )

    st.divider()

    st.subheader(
        "Physical backing"
    )

    if data["physical_backing"]:

        backing_rows = [
            {
                "Asset":
                    row["asset"],

                "Required":
                    float(
                        row["required"]
                    ),

                "Binance Free":
                    float(
                        row[
                            "exchange_free"
                        ]
                    ),

                "Surplus":
                    float(
                        row["surplus"]
                    ),

                "Backed":
                    (
                        "YES"
                        if row[
                            "is_backed"
                        ]
                        else "NO"
                    ),
            }
            for row in data[
                "physical_backing"
            ]
        ]

        backing_df = pd.DataFrame(
            backing_rows
        )

        st.dataframe(
            backing_df.style.format(
                {
                    "Required":
                        "{:,.8f}",
                    "Binance Free":
                        "{:,.8f}",
                    "Surplus":
                        "{:+,.8f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    else:

        st.warning(
            "Physical backing could not "
            "be evaluated."
        )

    st.divider()

    st.subheader(
        "Operational state"
    )

    s1, s2, s3 = st.columns(3)

    s1.metric(
        "Recoverable orders",
        data[
            "recoverable_orders"
        ],
    )

    s2.metric(
        "Index processed",
        (
            "YES"
            if data[
                "current_feed_processed"
            ]
            else "NO"
        ),
    )

    s3.metric(
        "Physical backing",
        (
            "OK"
            if data[
                "physical_backing_ok"
            ]
            else "CHECK"
        ),
    )
