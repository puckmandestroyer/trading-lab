# Changelog

## 2026-10-02 — Stage 3 EMA trend-following signal research

- Added an EMA20/EMA50 long-only research notebook with explicit crossover events, LONG_ENTRY/LONG_EXIT/HOLD signals, and flat/long state transitions.
- Added full-period and zoomed charts, signal-event tables, initialization explanations, and candle-close signal availability separated from future execution.
- Executed all 12 code cells and validation checks successfully: 79 bullish and 78 bearish crossovers, final research state 1 (long). Preserved raw OHLCV and existing files; no PnL, execution, processed data, dependencies, or reusable strategy module was introduced.

## 2026-10-02 — Stage 2 minimal historical market analytics

- Expanded the exploration notebook with simple/log returns, sample return statistics and a histogram, trailing 24-hour/7-day volatility, volume summaries, extreme returns, and BTC buy-and-hold close-based drawdown.
- Added beginner-friendly explanations and a summary of the actual snapshot; observed maximum drawdown was -53.7338%, with no raw-data quality issues.
- Executed all 20 code cells and five plots successfully in the existing virtual environment. Preserved the raw CSV, kept derived columns in memory, and deferred reusable preprocessing until needed. No new dependencies or trading functionality were introduced.

## 2026-10-02 — Git/GitHub setup confirmed

- Confirmed Git is initialized at the project root, with initial commit `ff57150` pushed to [GitHub](https://github.com/puckmandestroyer/trading-lab) and `main` tracking `origin/main`.
- Corrected stale Git state in the project documentation.

## 2026-10-01 — Historical market data pipeline

- Added reusable OHLCV loading, normalization, validation, and snapshot persistence using the Bybit V5 Public Market Kline API, with exchange-specific HTTP calls isolated in the exchange layer.
- Collected 8,760 spot BTCUSDT 1-hour candles for 2025-10-01 through 2026-09-30 UTC across nine pages; saved the normalized raw CSV with no indicators or quality failures.
- Expanded and executed the exploration notebook with dataset inspection, data-quality checks, summary statistics, and price/volume plots.
- Added 13 offline tests covering pagination, API/data failures, and preservation of existing raw files; listed requests explicitly and installed the existing pandas/NumPy/Matplotlib research dependencies.

## 2026-10-01 — Project initialization

- Added the project structure, empty application packages, and a starter research notebook.
- Documented architecture boundaries, future development instructions, and the first data milestone.
- Added minimal research requirements, credential placeholders, and dataset/output ignore rules.
- Preserved all existing Python files and directories; no packages installed or commits made.
