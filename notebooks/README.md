# Research notebooks

Use this directory for data exploration, research, visualization, and experiments. `01_data_exploration.ipynb` explores historical Bybit spot BTCUSDT 1-hour OHLCV data. It calls the reusable loader from `src/trading_lab/data/market_data.py` if the local CSV is absent; otherwise it loads and validates the existing snapshot. It does not run a strategy.

The notebook covers imports, loading, dataset inspection, data quality, summary statistics, price visualization, volume visualization, and observation prompts. Its first period is 2025-10-01 00:00 UTC through 2026-10-01 00:00 UTC, with the end excluded. All code cells have been executed successfully against the saved snapshot.

Select the parent workspace's `.venv/` Python kernel. The notebook finds the project root and adds its `src/` directory to the Python import path. This lets research call the same functions that future analytics or backtests can reuse, rather than duplicating API logic.

Read original datasets from `../data/raw/` and save cleaned copies to `../data/processed/`. Check the notebook's working directory before using relative paths. Save generated outputs under `../results/`.

When experimental code becomes stable and reusable, move it into `src/trading_lab/`. Notebook checkpoints are ignored by Git. Review notebook outputs for secrets before saving or sharing them.

`04_generic_backtest_engine.ipynb` demonstrates the generic strategy → validation/execution → ledger → independent GROSS/NET accounting architecture. It uses the existing EMA20/50 strategy plus a tiny synthetic, contract-only non-EMA example; existing equity helpers compose downstream. It contains 23 cells (11 code / 12 Markdown), compact previews/summaries, and one candle-close GROSS/NET equity plot. All code cells execute sequentially without saved errors.

Notebook 04 reads only the frozen local `data/raw/BTCUSDT_1h.csv` through the existing loader and stops clearly if it is missing; it never downloads replacement data. It checks frozen references and input/raw-file preservation. Notebook 03 remains the frozen Stage 5 analytics report and was neither modified nor executed during Stage 6.6.

The five existing `.py` research placeholders are preserved unchanged. Their filenames do not indicate implemented strategies or comparison functionality.
