# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 1 — Historical market data and research environment.

## Completed

- Initial repository-style project structure and documentation.
- Empty reusable Python packages and a starter Jupyter notebook.
- Initial architecture decision and permanent Codex instructions.
- Codex-assisted workspace inspection and scaffolding.
- Reusable historical OHLCV loader with backward pagination through the Bybit V5 Public Market Kline API.
- UTC/numeric normalization, explicit duplicate handling, full-period validation, protected snapshot saving, and validated CSV loading.
- First Bybit spot BTCUSDT hourly snapshot saved under `data/raw/BTCUSDT_1h.csv`: 8,760 rows spanning 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC.
- Validation found zero missing values, duplicates, missing hourly candles, or invalid OHLC/volume rows; download used nine pages and removed zero duplicates.
- Research notebook executed with inspection examples, quality checks, summary statistics, and price/volume plots.
- Thirteen offline tests passed for pagination, normalization, response failures, incomplete coverage, invalid data, and snapshot preservation.

## Environment status

- The parent workspace's `.venv/` uses Python 3.9.6. pandas 2.3.3, NumPy 2.0.2, and Matplotlib 3.9.4 were installed for this task. requests and JupyterLab were already available.
- All notebook code cells executed successfully using this virtual environment; the editor's selected kernel was not changed.
- The existing Python/LibreSSL environment emits an urllib3 compatibility warning. Public API calls succeeded; the warning was not suppressed, and interpreter migration is outside this task.
- Git is now initialized at `/Users/romankondratenko/trading-lab`, with no commits yet on `main`. At task start, the project and parent `.venv/` were untracked. No Git configuration or commits were changed in this task.

## Current focus

Explore the saved historical BTCUSDT dataset and record research observations. Historical data collection is implemented; no trading integration is present.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Trading strategies and a backtesting engine.
- Performance metrics and strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Centralized risk engine.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Review the notebook's dataset summaries and plots, document notable price/volume periods and potential anomalies, and decide whether a reproducible preprocessing step is needed. Preserve the raw snapshot. Do not start this next task until the owner approves it.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
