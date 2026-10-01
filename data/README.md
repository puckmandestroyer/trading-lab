# Market data

- `raw/`: original market datasets. Never manually modify these files.
- `processed/`: cleaned or transformed copies produced from raw datasets.
- `proceseed/`: an existing misspelled directory, preserved. Use `processed/` for new work.

Dataset contents are ignored by Git. `.gitkeep` files preserve the `raw/` and `processed/` directories. Do not store application code or credentials here.

## First snapshot: BTCUSDT_1h.csv

- Source: [Official Bybit V5 Public Market Kline API](https://bybit-exchange.github.io/docs/v5/market/kline), `https://api.bybit.com/v5/market/kline`.
- Retrieval date: 2026-10-01.
- Exchange/category/symbol: Bybit / spot / BTCUSDT.
- Interval: `60` (one hour).
- Requested range: `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. The start is included; the end is excluded.
- Observed range: 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC.
- Download: nine API pages, with a limit of 1,000 candles per request.
- Rows: 8,760; chronological order: oldest first.
- Columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`.
- In-memory dtypes: `datetime64[ns, UTC]` for timestamp; `float64` for each numeric column. CSV stores text, so the loader restores these types when reading it.
- Timestamp meaning: UTC candle opening time. Prices are in USDT; spot volume is in BTC.
- Missing values: zero in every column.
- Duplicate timestamps: zero; identical duplicates removed during download: zero.
- Missing hourly candles: zero, including both requested boundaries.
- Invalid OHLC/volume rows: zero; non-finite numeric values: zero.

This is normalized source market data: API string fields were converted to numeric/UTC values, rows sorted, and Bybit's turnover field excluded to match the six-column schema. No indicators, returns, volatility, or signals were added. The original snapshot is not manually modified.

## Loading and preservation

`src/trading_lab/data/market_data.py` provides `download_ohlcv`, `load_ohlcv_csv`, `save_ohlcv`, and `validate_ohlcv`. Exchange-specific HTTP handling stays in `src/trading_lab/exchange/bybit_market_data.py`. Public requests use no credentials or private endpoints.

Bybit returns newest-first pages. Pagination moves each request's end to one millisecond before the oldest returned candle. Full-range validation catches incomplete history, including an empty page before coverage is complete. Unexpected HTTP/JSON/API responses raise errors; retries are not automatic. After a request failure, rerun the download; no partial dataset is saved.

Identical duplicate rows are removed with a warning; conflicting duplicates raise an error. Missing values, non-finite numbers, non-positive prices, negative volume, inconsistent OHLC, timestamp misalignment, duplicates, gaps, or incorrect chronology fail validation. Invalid rows are reported, not silently removed or filled.

`save_ohlcv` refuses to overwrite an existing file. To collect a different period later, choose a different snapshot filename and record its provenance. Loading the local snapshot rather than downloading for every experiment keeps research inputs stable. Future transformations belong in `processed/`.

For each future dataset, record its filename, source, symbol, interval, date range, timestamp timezone, retrieval date, and any download settings. For processed datasets, also record the source raw file and transformations so the result can be reproduced.
