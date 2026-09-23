Crypto Index ETF Demo

A safety-first Python framework for simulating an ETF-like portfolio that replicates a precomputed cryptocurrency index using the Binance Spot Demo environment.

The project separates index construction from portfolio execution. It receives a portfolio composition generated externally, calculates the ETF rebalance required to track that composition, validates market constraints, executes controlled Demo orders, reconciles actual exchange fills, maintains its own accounting ledger, and measures execution quality.

Important: This project is an engineering and research demonstration. It is not a registered ETF, investment fund, brokerage system, or production trading platform.

Project Goals

The system is designed to demonstrate how an index-tracking portfolio can be operated safely and audibly.

The core objectives are:

Replicate an externally calculated crypto index portfolio.

Maintain an independent ETF accounting ledger.

Use Binance Spot Demo for execution testing.

Separate ETF ownership from global Binance account balances.

Prevent accidental or duplicate execution.

Reconcile orders using actual Binance fills.

Record commissions using the actual commission asset.

Measure NAV and NAV per share.

Detect stale portfolio feeds.

Prevent the same portfolio cutoff from being rebalanced twice.

Persist pre-trade execution benchmarks.

Measure spread, slippage, fees, and implementation shortfall.

Support a protected weekly automation workflow.

Architecture

External Index Engine
        |
        | portfolio JSON
        v
+---------------------------+
| Portfolio Feed Validator  |
+---------------------------+
        |
        v
+---------------------------+
| Rebalance Planner         |
|                           |
| - target weights          |
| - current ETF positions   |
| - Binance symbol rules    |
| - minimum notionals       |
| - step sizes              |
+---------------------------+
        |
        v
+---------------------------+
| Funding Layer             |
|                           |
| - current ETF cash        |
| - estimated SELL proceeds |
| - BUY prioritization      |
| - partial valid buys      |
| - unfunded signals        |
+---------------------------+
        |
        v
+---------------------------+
| Execution Safety Layer    |
|                           |
| - stale-feed protection   |
| - duplicate cutoff guard  |
| - order preflight         |
| - BNB fee reserve         |
| - explicit execution gate |
+---------------------------+
        |
        v
+---------------------------+
| Binance Spot Demo         |
|                           |
| RESERVED                  |
| -> benchmark              |
| -> POST                   |
| -> reconciliation         |
| -> ACCOUNTED              |
+---------------------------+
        |
        v
+---------------------------+
| ETF Accounting            |
|                           |
| - cash ledger             |
| - positions               |
| - fills                   |
| - fees                    |
| - NAV                     |
| - NAV/share               |
+---------------------------+
        |
        v
+---------------------------+
| Execution Analytics       |
|                           |
| - bid / ask / mid         |
| - spread cost             |
| - slippage                |
| - fee valuation           |
| - implementation          |
|   shortfall               |
+---------------------------+

Safety Model

Execution is intentionally disabled by default.

Two independent environment switches control automated trading:

BINANCE_TRADING_ENABLED=false
ETF_WEEKLY_AUTOMATION_ENABLED=false

A full automated rebalance requires both switches to be enabled and the corresponding CLI execution flag.

The project also uses several independent protections.

Demo Environment Guard

The exchange client verifies that order execution is configured for the Binance Demo endpoint before allowing an order to be submitted.

Explicit Execution Flag

A normal invocation of the rebalance script is always a dry run.

python scripts/execute_full_rebalance.py

Actual Demo execution additionally requires:

python scripts/execute_full_rebalance.py --execute-full-rebalance

ETF Order Namespace

ETF orders use dedicated client order IDs:

IDXETF_R000002_03_BTC

This allows ETF orders to be distinguished from other strategies using the same Binance Demo account.

No Blind Retry

If an order submission returns an uncertain result, the system does not blindly submit another order.

The local order is moved to a recoverable state and Binance is queried using the existing clientOrderId.

Recoverable Order Protection

A new rebalance cannot begin while unresolved ETF orders exist.

Duplicate Portfolio Protection

A portfolio identified by the same cutoff_utc cannot successfully complete twice.

This protection exists at both the application and database levels.

Stale Feed Protection

Portfolio feeds older than the configured maximum age are blocked.

Default:

index_feed:
  max_age_hours: 192

This represents an eight-day maximum age for a weekly portfolio process.

ETF Accounting Model

The ETF does not determine ownership from the Binance account's global balances.

Instead, ownership is maintained in an independent SQLite ledger.

This is especially important when multiple strategies share the same Binance Demo account.

The ledger tracks:

cash_ledger
positions
position_ledger
fee_ledger
rebalance_runs
orders
order_lifecycle
fills
nav_snapshots
execution_benchmarks

The ETF therefore treats Binance as the execution venue while its own database remains the authoritative source for ETF ownership.

Portfolio Feed

Index construction is intentionally outside this repository.

The ETF receives a precomputed portfolio JSON containing the target constituents and weights.

A sample file is available at:

examples/portfolio.example.json

Runtime portfolio files belong under:

data/

For example:

data/portfolio_seed.json

The execution engine primarily uses:

asset
target_weight_pct
cutoff_utc
index_level

The theoretical index quantity contained in the upstream portfolio is not used to determine ETF execution quantities.

ETF quantities are calculated independently using the ETF's own NAV and Binance market data.

Rebalance Logic

For every constituent:

target value
=
ETF NAV
×
target portfolio weight

The planner compares the target value with the current ETF-owned position.

This produces one of the following actions:

BUY
SELL
HOLD
DUST

The funding layer may additionally convert a theoretical BUY into:

UNFUNDED

when the ETF does not have enough buying power to place a valid Binance order.

SELL proceeds may fund subsequent BUY orders.

The execution sequence is designed as:

SELLs
  ->
BNB BUY if required
  ->
remaining BUYs

Before every real BUY, the system rechecks the actual available quote balance.

Binance Market Constraints

The system reads Binance exchange information and respects symbol-specific constraints such as:

LOT_SIZE
MARKET_LOT_SIZE
NOTIONAL / MIN_NOTIONAL
stepSize
minimum quantity
quote precision
quoteOrderQty support

Orders are validated through Binance's order-test endpoint before execution.

Commission Accounting

Actual commissions are taken from exchange fills rather than estimated locally.

The accounting engine supports commissions charged in:

USDC
the purchased asset
BNB

When Binance charges the BUY commission in the purchased asset, the ETF records the net quantity received.

Example:

Gross BNB bought     0.03100000
BNB commission      -0.00002208
--------------------------------
ETF BNB position     0.03097792

The ETF never assumes that all BNB in the Binance account belongs to this strategy.

Execution Benchmarks

Immediately before submitting an order, the system persists:

timestamp
bid
ask
mid
spread
spread in basis points
BNB/USDC mid price

The benchmark is committed before the exchange POST.

This means the reference price survives even if the subsequent submission result becomes uncertain.

Execution analytics can then calculate:

For BUY orders:

spread cost
=
(ask - mid) × executed quantity

slippage beyond ask
=
(average fill - ask) × executed quantity

For SELL orders:

spread cost
=
(mid - bid) × executed quantity

slippage beyond bid
=
(bid - average fill) × executed quantity

Implementation shortfall is approximated as:

execution cost versus benchmark mid
+
commission valued in USDC

Negative slippage represents price improvement.

Weekly Runner

The weekly supervisor is:

scripts/weekly_runner.py

It evaluates the current portfolio feed and returns operational states such as:

NO_ACTION_ALREADY_COMPLETED
NO_ACTION_STALE_FEED
BLOCKED_RECOVERY_REQUIRED
BLOCKED_EXISTING_RUN
READY

A normal invocation performs observation only:

python scripts/weekly_runner.py

A safe preview of a new portfolio can be requested with:

python scripts/weekly_runner.py --preview-if-ready

This invokes the actual rebalance engine in dry-run mode.

Automatic execution additionally requires:

python scripts/weekly_runner.py --execute-if-ready

as well as:

ETF_WEEKLY_AUTOMATION_ENABLED=true
BINANCE_TRADING_ENABLED=true

The runner also uses a filesystem lock to prevent concurrent instances from executing simultaneously.

Project Structure

binance-index-etf-demo/
|
|-- config/
|   `-- runtime.yaml
|
|-- data/
|   |-- .gitkeep
|   `-- README.md
|
|-- examples/
|   `-- portfolio.example.json
|
|-- logs/
|   |-- .gitkeep
|   `-- README.md
|
|-- scripts/
|   |-- audit_rebalance_run.py
|   |-- check_demo_account.py
|   |-- check_demo_connection.py
|   |-- check_etf_markets.py
|   |-- check_execution_guard.py
|   |-- execute_full_rebalance.py
|   |-- execute_single_bnb_demo.py
|   |-- init_etf_ledger.py
|   |-- inspect_portfolio_feed.py
|   |-- migrate_database.py
|   |-- preview_rebalance.py
|   |-- simulate_rebalance_transaction.py
|   |-- weekly_runner.py
|   `-- test_*.py
|
|-- src/
|   |-- accounting/
|   |-- exchange/
|   |-- execution/
|   |-- index/
|   |-- portfolio/
|   |-- rebalance/
|   `-- storage/
|
|-- .env.example
|-- .gitignore
|-- README.md
`-- requirements.txt

Installation

Python 3.11+ is recommended.

Create a virtual environment:

python -m venv .venv

Activate it.

Windows Git Bash:

source .venv/Scripts/activate

Linux:

source .venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Create the local environment file:

cp .env.example .env

Add Binance Demo credentials to .env.

Do not commit .env.

Initial Configuration

Create a runtime portfolio feed:

cp examples/portfolio.example.json data/portfolio_seed.json

The default fund configuration is located in:

config/runtime.yaml

Example:

fund:
  name: Crypto Index ETF Demo
  base_currency: USDC
  initial_capital: '5000'
  shares_outstanding: '50'
  order_prefix: IDXETF_

index_feed:
  portfolio_file: data/portfolio_seed.json
  max_age_hours: 192

storage:
  database: data/index_etf.db

environment:
  exchange: BINANCE
  mode: DEMO

Database Initialization

Create or migrate the database schema:

python scripts/migrate_database.py

Initialize the ETF ledger:

python scripts/init_etf_ledger.py

Initialization is idempotent and should not duplicate the initial capital.

Connectivity Checks

Check Binance Demo connectivity:

python scripts/check_demo_connection.py

Check the authenticated Demo account:

python scripts/check_demo_account.py

Validate required ETF markets:

python scripts/check_etf_markets.py

Check the execution safety gate:

python scripts/check_execution_guard.py

With the default configuration, execution should remain blocked.

Dry-Run Workflow

Inspect the portfolio feed:

python scripts/inspect_portfolio_feed.py

Preview the rebalance:

python scripts/preview_rebalance.py

Run the protected full rebalance engine without execution:

python scripts/execute_full_rebalance.py

No order should be sent unless both the environment safety gate and the explicit execution flag are enabled.

Tests

The repository includes focused tests for critical execution behavior.

Examples:

python scripts/test_order_lifecycle.py
python scripts/test_reconciler_not_found.py
python scripts/test_reconciler_accounted.py
python scripts/test_execution_benchmark.py
python scripts/test_execution_metrics.py

These cover:

order lifecycle persistence
unknown/nonexistent exchange orders
fill reconciliation
transactional accounting
commission handling
execution benchmark persistence
spread and slippage mathematics
implementation shortfall

Rebalance Audit

A completed rebalance can be audited using:

python scripts/audit_rebalance_run.py --run-id 2

The report includes:

order lifecycle
executed quantities
quote values
fill counts
raw commissions
benchmark coverage
spread cost
slippage
fee valuation
implementation shortfall

Historical runs created before benchmark capture intentionally report benchmark metrics as unavailable rather than attempting to reconstruct them from current market prices.

Runtime Files

The following files are intentionally excluded from Git:

.env
data/*.db
data/*.db-wal
data/*.db-shm
runtime portfolio JSON files
logs
lock files
local IDE settings

The repository should never contain live API credentials, account databases, execution logs, or operational portfolio feeds.

Current Development Status

The project has successfully validated the following workflow in Binance Spot Demo:

portfolio feed
-> validation
-> rebalance planning
-> market preflight
-> local order reservation
-> Demo MARKET execution
-> exchange reconciliation
-> fill accounting
-> BNB commission accounting
-> ETF position accounting
-> NAV calculation
-> post-rebalance audit

A complete ten-asset Demo portfolio initialization has been executed and reconciled successfully.

The project is currently transitioning from local development to isolated server deployment and scheduled weekly operation.

Production Considerations

This repository is intentionally designed around Binance Demo.

Using similar software with real capital would require additional controls beyond the current scope, including areas such as:

production credential management
exchange outage handling
operational monitoring
backup and disaster recovery
formal reconciliation
alerting
tax and accounting treatment
regulatory analysis
independent security review
change management
production deployment controls

Do not assume Demo behavior is identical to production exchange behavior.

Disclaimer

This software is provided for educational, engineering, research, and demonstration purposes.

It does not constitute financial advice, investment advice, portfolio management advice, or an offer to buy or sell financial instruments or digital assets.

Cryptocurrency markets involve significant risk.

The authors and contributors are not responsible for financial losses, exchange behavior, API changes, software defects, or use of this project outside its intended Demo and research environment.