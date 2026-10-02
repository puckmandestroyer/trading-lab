# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 2 — Minimal Historical Market Analytics (completed).

## Completed

- Initial repository-style project structure and documentation.
- Empty reusable Python packages and a starter Jupyter notebook.
- Initial architecture decision and permanent Codex instructions.
- Codex-assisted workspace inspection and scaffolding.
- Git repository setup, initial commit, and successful publication to GitHub.
- Reusable historical OHLCV loader with backward pagination through the Bybit V5 Public Market Kline API.
- UTC/numeric normalization, explicit duplicate handling, full-period validation, protected snapshot saving, and validated CSV loading.
- First Bybit spot BTCUSDT hourly snapshot saved under `data/raw/BTCUSDT_1h.csv`: 8,760 rows spanning 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC.
- Validation found zero missing values, duplicates, missing hourly candles, or invalid OHLC/volume rows; download used nine pages and removed zero duplicates.
- Research notebook executed with inspection examples, quality checks, summary statistics, and price/volume plots.
- Thirteen offline tests passed for pagination, normalization, response failures, incomplete coverage, invalid data, and snapshot preservation.
- Stage 2 notebook analysis: simple/log returns, sample return statistics and distribution, trailing 24-hour/7-day hourly-return volatility, volume, extreme movements, and BTC buy-and-hold close-based drawdown.
- All 20 notebook code cells executed successfully using the existing virtual environment, including five plots and checks of the derived calculations.
- The existing 8,760-row raw snapshot remains unchanged; all seven derived columns exist only in notebook memory. No processed dataset, dependencies, or application modules were added.
- Observed hourly mean return: -0.002462%; standard deviation: 0.469127%; minimum/maximum: -4.7946% / +3.9581%. Maximum observed close-based buy-and-hold drawdown: -53.7338%. These describe this snapshot, not predictions or bot performance.

## Environment status

- The parent workspace's `.venv/` uses Python 3.9.6. pandas 2.3.3, NumPy 2.0.2, and Matplotlib 3.9.4 were installed for this task. requests and JupyterLab were already available.
- All notebook code cells executed successfully using this virtual environment; the editor's selected kernel was not changed.
- The existing Python/LibreSSL environment emits an urllib3 compatibility warning. Public API calls succeeded; the warning was not suppressed, and interpreter migration is outside this task.
- Git repository root: `/Users/romankondratenko/trading-lab/Trading Lab`.
- Branch: `main`, tracking `origin/main`. Initial commit: `ff57150` (`Initialize Trading Lab project`), pushed successfully to GitHub.
- Remote repository: [puckmandestroyer/trading-lab](https://github.com/puckmandestroyer/trading-lab).

## Current focus

Stage 2 research is complete. Review its documented observations and agree on the next milestone before further development. Historical collection and notebook-only market analytics are implemented; no trading strategy or trading integration is present.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Trading strategies and a backtesting engine.
- Reusable strategy-performance analytics and strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Centralized risk engine.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Proposed Stage 3: define the first simple research strategy's signal rules, required inputs, and timing before implementation. Determine which calculations need reuse based on those concrete requirements. Do not start this milestone until the owner approves it.

No processed dataset or reusable preprocessing module is needed yet: the validated OHLCV snapshot and in-memory calculations are sufficient. Extract stable calculations only when an approved additional workflow needs them.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

Stage 2 volatility uses sample standard deviation (`ddof=1`) of hourly returns over trailing 24/168-observation windows and is not annualized. First-return and rolling-window NaNs are expected warm-up values. Drawdown uses candle closes and excludes intrahour lows; the index is BTC buy-and-hold price analysis, not a bot backtest.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
