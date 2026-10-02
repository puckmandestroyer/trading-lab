# Changelog

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
