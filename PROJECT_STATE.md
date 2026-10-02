# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 3.1 — EMA Strategy Logic Cleanup before Backtesting (completed).

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
- Stage 3 notebook `notebooks/02_ema_strategy.ipynb`: EMA20/EMA50 long-only crossover events, LONG_ENTRY/LONG_EXIT/HOLD signals, and post-signal flat/long research state.
- All 12 strategy-notebook code cells executed successfully, including full-period and zoomed charts, three event-inspection tables, and signal/state/timing/causal-prefix/raw-preservation checks.
- Original Stage 3 results before cleanup: 79 bullish and 78 bearish crossovers, ending in research state 1. These initialization and state conventions are superseded by Stage 3.1 below.
- Raw OHLCV and existing files remained unchanged during Stage 3. Derived strategy columns stay in notebook memory; no processed dataset, reusable strategy module, dependencies, or trading execution was added.
- Stage 3.1 completed: 50 initialization-only candles, `warmup_complete` eligibility from candle 51, `desired_position` naming, and prior-state gating of LONG_ENTRY/LONG_EXIT signals.
- Current results: 78 bullish and 78 bearish eligible crossovers; 78 valid entries and 77 valid exits. A bearish crossover while flat remains HOLD. Final `desired_position` is 1 (wants long).
- First valid LONG_ENTRY candle: 2025-10-13 02:00 UTC, signal_time 03:00 UTC. First valid LONG_EXIT candle: 2025-10-14 05:00 UTC, signal_time 06:00 UTC.
- All 12 updated notebook code cells ran successfully. Warm-up, previous-state, alternating-event, HOLD-stability, timing, and causal-prefix checks passed; raw CSV and the earlier analytics notebook stayed unchanged. No processed dataset was created.

## Environment status

- The parent workspace's `.venv/` uses Python 3.9.6. pandas 2.3.3, NumPy 2.0.2, and Matplotlib 3.9.4 were installed for this task. requests and JupyterLab were already available.
- All notebook code cells executed successfully using this virtual environment; the editor's selected kernel was not changed.
- The existing Python/LibreSSL environment emits an urllib3 compatibility warning. Public API calls succeeded; the warning was not suppressed, and interpreter migration is outside this task.
- Git repository root: `/Users/romankondratenko/trading-lab/Trading Lab`.
- Branch: `main`, tracking `origin/main`. Initial commit: `ff57150` (`Initialize Trading Lab project`), pushed successfully to GitHub.
- Remote repository: [puckmandestroyer/trading-lab](https://github.com/puckmandestroyer/trading-lab).

## Current focus

Stage 3.1 cleanup is complete and the README reflects the completed historical-data, market-analytics, and strategy-research stages. Review the conventions below before approving Stage 4. No backtest, PnL, trade simulation, or trading integration is present.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Reusable strategy modules and a backtesting engine.
- Reusable strategy-performance analytics and strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Centralized risk engine.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Proposed Stage 4 next step: define next-candle execution semantics and extract the validated EMA signal logic into a small pure function with lightweight tests, before implementing a minimal backtest. Execution must use the conventions below. Do not start Stage 4 until the owner approves it.

No processed dataset or reusable preprocessing module is needed yet. Keep the EMA logic in the notebook for now; extract it when the next approved workflow establishes the reuse requirement. No strategy classes or framework are needed.

## Conventions for Stage 4

- The first 50 candles are initialization-only; no events occur in them, and eligibility starts on candle 51.
- Signals use only completed candle data. `signal_time` is the candle opening timestamp plus one hour.
- `desired_position` is research intent: 0 wants flat and 1 wants long. Entries require previous state 0; exits require previous state 1; HOLD preserves state.
- Execution may occur no earlier than candle N+1 after a signal from candle N. It must be modeled separately from signal generation.
- `executed_position` does not exist yet. There is no backtest, PnL, trade simulation, or execution-price calculation.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

Stage 2 volatility uses sample standard deviation (`ddof=1`) of hourly returns over trailing 24/168-observation windows and is not annualized. First-return and rolling-window NaNs are expected warm-up values. Drawdown uses candle closes and excludes intrahour lows; the index is BTC buy-and-hold price analysis, not a bot backtest.

Stage 3.1 keeps `ewm(span=20/50, adjust=False)` with the first close as the seed. The 50-candle warm-up is a research convention, not an EWM mathematical requirement or a guarantee that seed effects have disappeared. No entry is synthesized merely because warm-up ends in a bullish regime; the flat strategy waits for a new bullish crossover. `desired_position` is not an executed position.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
