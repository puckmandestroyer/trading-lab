# Trading Lab

Trading Lab is a long-term Python project for researching cryptocurrency trading strategies and eventually running them in demo trading. It is also a learning environment for Python, data analysis, SQL, statistics, and quantitative analysis.

The long-term goal is to support historical market data, multiple independent strategies, a reusable backtesting engine, performance analysis and strategy comparison, multiple autonomous bot instances, centralized risk management, order management, PostgreSQL storage, per-bot and global dashboards, and Docker deployment.

## Current stage

**Stage 1 — Historical market data and research environment.** A reusable Bybit public-market-data pipeline now downloads, normalizes, validates, and saves historical OHLCV candles. The exploration notebook loads a local snapshot and provides quality checks, summary statistics, and price/volume plots. Strategies, backtesting, and exchange trading are not implemented.

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
│   ├── backtest/          # Future historical simulation
│   ├── analytics/         # Future shared performance analysis
│   ├── exchange/          # Future exchange-specific adapters
│   ├── execution/         # Future order and execution management
│   ├── risk/              # Future centralized risk checks
│   ├── database/          # Future storage integration
│   └── config/            # Future application configuration
├── strategies/            # Existing Python placeholders, preserved
├── dashboard/             # Future dashboards; documentation only
├── results/               # Generated experiment and backtest output
├── tests/                 # Future checks for reusable code
└── scripts/               # Future small command-line utilities
```

The data package now contains `market_data.py`, and the exchange package contains the public HTTP adapter `bybit_market_data.py`. Other application packages remain placeholders. Existing `.py` files in `notebooks/` and the top-level `strategies/` are preserved. New reusable strategy code should eventually go in `src/trading_lab/strategies/`.

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

Read `PROJECT_STATE.md` before starting new work. Git is now initialized at the parent workspace, but no commits have been made. The CSV is ignored by the project's `.gitignore`.
