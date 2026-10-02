# Trading Lab

Trading Lab is a long-term Python project for researching cryptocurrency trading strategies and eventually running them in demo trading. It is also a learning environment for Python, data analysis, SQL, statistics, and quantitative analysis.

The long-term goal is to support historical market data, multiple independent strategies, a reusable backtesting engine, performance analysis and strategy comparison, multiple autonomous bot instances, centralized risk management, order management, PostgreSQL storage, per-bot and global dashboards, and Docker deployment.

## Current stage

**Stage 4.6 — Closed-Trade Returns & PnL (completed).**

- Stage 1 completed: reusable historical data collection and a validated BTCUSDT hourly snapshot.
- Stage 2 completed: statistical market analysis of returns, volatility, volume, extreme movements, and BTC buy-and-hold drawdown in `notebooks/01_data_exploration.ipynb`.
- Stage 3 completed: EMA20/EMA50 long-only signal research in `notebooks/02_ema_strategy.ipynb`.
- Stage 3.1 completed: a 50-candle warm-up, explicit `desired_position`, validated alternating entry/exit signals, and clarified signal availability.
- Stage 4.1 completed: the [backtesting execution contract](decisions/002_backtest_execution_contract.md) defines next-candle-OPEN fills, initial flat executed state, and final-candle behavior.
- Stage 4.2 completed: `src/trading_lab/backtest/execution.py` implements fill timing and executed state for supplied signals. Its 23 synthetic tests and all 13 existing market-data tests pass.
- Stage 4.3 completed: `src/trading_lab/strategies/ema_trend.py` provides the pure `generate_ema_signals` function, requiring only `timestamp` and `close`. The EMA notebook now uses it; 21 strategy tests bring the passing suite to 57 tests.
- Stage 4.4 completed: `src/trading_lab/backtest/pipeline.py` provides `run_ema_execution_pipeline`, requiring `timestamp`, `open`, and `close`. It composes the existing components with explicit alignment checks; 19 integration tests bring the passing suite to 76 tests.
- Stage 4.5 completed: `src/trading_lab/backtest/trades.py` provides `build_trade_ledger`, called separately after the pipeline. Its 25 tests bring the passing suite to 101 tests; the BTC snapshot has 77 CLOSED trades and one final OPEN trade.
- Stage 4.6 completed: `src/trading_lab/backtest/performance.py` provides `calculate_trade_results`, consuming the ledger to calculate quantity, CLOSED-trade returns, realized gross PnL, and compounded capital. Its 27 tests bring the passing suite to 128 tests.

The reusable strategy preserves the notebook's first 50 initialization-only candles; signals become eligible on candle 51 and use only completed candle data. `desired_position` is research intent, and `signal_time` is the candle timestamp plus one hour. Snapshot results remain 78 bullish/78 bearish crossovers, 78 entries/77 exits, and final desired state 1. Both EMA notebook charts and inspection tables remain available.

The independent execution helper consumes pre-generated signals, starts flat, and applies valid events at the next candle's OPEN. Execution time/price are recorded on the source signal row N; `executed_position` changes on row N+1. A valid final-candle signal has no fill, and invalid flat/long transitions raise `ValueError`.

The pipeline combines market, strategy, and execution columns after verifying equal row counts, indexes, timestamps, and chronological order. Strategy logic and execution logic remain in their own modules. `desired_position` is intent after a candle completes; `executed_position` is what is held during that candle, so they can differ on signal rows. Appending a next candle can give a formerly final signal its fill metadata without changing earlier results.

The separate ledger turns recorded execution fills into one row per trade: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, and `status`. CLOSED means an entry and exit actually executed; OPEN means an entry executed with no exit yet. An unexecuted final entry creates no trade, and an unexecuted final exit leaves a trade OPEN. The ledger uses recorded fill times/prices and never invents a terminal exit.

The accounting helper adds `capital_before`, `quantity`, `trade_return`, `gross_pnl`, and `capital_after`. It defaults to 10,000 USDT and deploys 100% of current capital into each long spot trade, with no leverage, fees, commissions, slippage, or quantity rounding. Quantity equals capital before divided by entry price. Each CLOSED trade's gross result compounds into the next trade. OPEN trades have capital before and quantity but missing realized return, PnL, and capital after; no unrealized valuation is calculated.

The BTC snapshot's 77 CLOSED trades leave realized capital of 9,641.111388344 USDT before its final OPEN entry, which holds quantity 0.1130341406801 BTC. This is closed-trade accounting under the stated zero-cost model, not a valuation of that open position or a candle-level equity curve. Full portfolio simulation, performance analytics, and demo trading remain future work.

The platform currently uses no real money. Public data collection requires no API key. Exchange trading and demo trading integration will be added later.

The first snapshot, `data/raw/BTCUSDT_1h.csv`, contains 8,760 hourly Bybit spot BTCUSDT candles from 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC. It contains only timestamp, open, high, low, close, and volume. See `data/README.md` for provenance and validation results.

## Directory guide

```text
Trading Lab/
├── AGENTS.md              # Instructions for future coding work
├── README.md              # Project overview
├── CHANGELOG.md           # Meaningful changes
├── PROJECT_STATE.md       # Current progress and next milestone
├── .gitignore             # Files excluded from Git
├── .env.example           # Empty credential variable examples
├── requirements.txt       # First-stage research dependencies
├── decisions/             # Important architecture decisions
├── notebooks/             # Exploration and experiments
├── data/
│   ├── raw/               # Original market data
│   ├── processed/         # Cleaned or transformed copies
│   └── proceseed/         # Existing misspelled directory, preserved
├── src/trading_lab/
│   ├── data/              # Reusable data loading and preprocessing
│   ├── strategies/        # Strategy signal generation
│   ├── backtest/          # Fill timing/state; future full simulation
│   ├── analytics/         # Future shared performance analysis
│   ├── exchange/          # Future exchange-specific adapters
│   ├── execution/         # Future order and execution management
│   ├── risk/              # Future centralized risk checks
│   ├── database/          # Future storage integration
│   └── config/            # Future application configuration
├── strategies/            # Existing Python placeholders, preserved
├── dashboard/             # Future dashboards; documentation only
├── results/               # Generated experiment and backtest output
├── tests/                 # Offline checks for reusable code
└── scripts/               # Future small command-line utilities
```

The data package contains `market_data.py`, the exchange package contains the public HTTP adapter `bybit_market_data.py`, the strategies package contains `ema_trend.py`, and the backtest package contains `execution.py`, `pipeline.py`, `trades.py`, and `performance.py`. Other application packages remain placeholders. Existing `.py` files in `notebooks/` and the top-level `strategies/` are preserved. New reusable strategy code belongs in `src/trading_lab/strategies/`.

## Research and reusable code

Use `notebooks/` to explore datasets, make plots, and try ideas. Use `src/trading_lab/` for stable Python code that can be reused in multiple notebooks or application workflows. Move research code there when it becomes useful and well understood; there is no need to build abstractions ahead of that point.

## Data and results

`data/raw/` contains original datasets and must never be manually edited. Read these files, then write cleaned or transformed copies to `data/processed/`. The existing `data/proceseed/` directory is retained; use the correctly spelled `processed/` for new work.

Store generated reports, plots, and backtest outputs in `results/`. Dataset and result contents are ignored by Git, while `.gitkeep` files preserve the intended empty directories. Document useful dataset provenance in `data/README.md`.

## Architecture

The planned flow is:

```text
Market Data → Strategy → Signal → Risk Manager → Execution Engine → Exchange
```

A strategy will produce BUY, SELL, or HOLD signals. The same strategy logic should eventually be usable in both historical backtesting and demo trading. Independent risk controls will govern position sizes and leverage. Exchange-specific code will stay in the exchange package. See `decisions/001_initial_architecture.md` for the boundaries.

## Research environment

`requirements.txt` lists pandas, NumPy, Matplotlib, JupyterLab, and requests. requests is the small HTTP library used to read the public API; no exchange SDK is needed. In the current workspace, the virtual environment lives one directory above this project:

```sh
source ../.venv/bin/activate
jupyter lab notebooks/01_data_exploration.ipynb
```

Select that virtual environment's Python kernel in a notebook-capable editor. The notebook adds `src/` to its import path, uses the reusable loader, and reads the local CSV when it already exists. It downloads only when the snapshot is absent, preserving consistent inputs for future research and backtests.

This project uses a `src/` layout without package installation configuration. To run the offline tests from this directory:

```sh
PYTHONPATH=src ../.venv/bin/python -m unittest discover -s tests -v
```

The loader supports Bybit's fixed minute-based intervals. It paginates backward through newest-first API pages, converts millisecond timestamps to UTC datetimes and numeric strings to floats, and sorts oldest first. It warns when removing identical duplicates and rejects conflicting duplicates, invalid candles, and incomplete interval coverage. Saving refuses to overwrite an existing snapshot. Daily, weekly, and monthly intervals are not supported in this first version.

`.env.example` contains empty variable names for future exchange configuration. Never add real credentials to source files or commit a local `.env` file. Credentials are not needed at this stage.

Read `PROJECT_STATE.md` before starting new work. Git is initialized at the project root (`/Users/romankondratenko/trading-lab/Trading Lab`). The initial commit has been pushed to [GitHub](https://github.com/puckmandestroyer/trading-lab), and `main` tracks `origin/main`. The CSV is ignored by the project's `.gitignore`.
