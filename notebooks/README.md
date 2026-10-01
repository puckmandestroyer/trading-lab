# Research notebooks

Use this directory for data exploration, research, visualization, and experiments. `01_data_exploration.ipynb` explores historical Bybit spot BTCUSDT 1-hour OHLCV data. It calls the reusable loader from `src/trading_lab/data/market_data.py` if the local CSV is absent; otherwise it loads and validates the existing snapshot. It does not run a strategy.

The notebook covers imports, loading, dataset inspection, data quality, summary statistics, price visualization, volume visualization, and observation prompts. Its first period is 2025-10-01 00:00 UTC through 2026-10-01 00:00 UTC, with the end excluded. All code cells have been executed successfully against the saved snapshot.

Select the parent workspace's `.venv/` Python kernel. The notebook finds the project root and adds its `src/` directory to the Python import path. This lets research call the same functions that future analytics or backtests can reuse, rather than duplicating API logic.

Read original datasets from `../data/raw/` and save cleaned copies to `../data/processed/`. Check the notebook's working directory before using relative paths. Save generated outputs under `../results/`.

When experimental code becomes stable and reusable, move it into `src/trading_lab/`. Notebook checkpoints are ignored by Git. Review notebook outputs for secrets before saving or sharing them.

The five existing `.py` research placeholders are preserved unchanged. Their filenames do not indicate implemented strategies or comparison functionality.
