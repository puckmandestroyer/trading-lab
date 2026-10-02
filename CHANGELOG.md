# Changelog

## 2026-10-02 — Stage 4.6 closed-trade returns and PnL

- Added separate pure ledger accounting for quantity, CLOSED-trade returns, realized gross PnL, and sequentially compounded capital. The model defaults to 10,000 USDT, allocates 100% per long spot trade, and excludes leverage and trading costs; OPEN trades receive quantity without realized results or valuation.
- Added 27 synthetic accounting tests; all 128 tests passed. BTC integration retained 77 CLOSED/one OPEN trade, verified the first trade independently, and produced realized capital of 9,641.111388344 USDT before the final OPEN entry, with quantity 0.1130341406801 BTC.
- Updated current-stage documentation. Pipeline/ledger behavior, raw data, notebooks, and dependencies remain unchanged; no fees, slippage, unrealized PnL, equity curve, or performance analytics was added.

## 2026-10-02 — Stage 4.5 trade ledger

- Added a pure trade-ledger helper that pairs recorded entry/exit fills into CLOSED or OPEN trades, validates metadata/order/state, and preserves unexecuted final-signal behavior without forced exits.
- Added 25 synthetic ledger tests; all 101 tests passed across all five suites. BTC integration verified 77 CLOSED trades and one final OPEN trade; first entry/exit fills are 2025-10-13 03:00 UTC at 115,332.3 USDT and 2025-10-14 06:00 UTC at 112,482.0 USDT.
- Updated current-stage documentation. Pipeline behavior, notebooks, raw data, and dependencies remain unchanged; no PnL, returns, sizing, fees, or portfolio valuation was added.

## 2026-10-02 — Stage 4.4 strategy + execution pipeline

- Added a pure EMA/execution pipeline that calls the existing components, checks row/index/timestamp/order alignment, and preserves desired-state versus next-open executed-state timing without reimplementing either layer.
- Added 19 synthetic integration tests, including final-row causal-prefix behavior and alignment failures; all 76 tests passed across the pipeline, strategy, execution, and market-data suites.
- Verified the 8,760-row BTC snapshot: unchanged strategy results, final desired/executed states 1/1, and first entry at 2025-10-13 03:00 UTC OPEN of 115,332.3 USDT. Updated stage documentation; notebooks, raw data, existing components, and dependencies are unchanged. No PnL or trade ledger was added.

## 2026-10-02 — Stage 4.3 reusable EMA strategy

- Extracted Stage 3.1 EMA signals into the pure `generate_ema_signals` function, preserving EMA seeding, 50-candle warm-up, crossover rules, desired-state gating, and hourly signal availability.
- Added 21 synthetic strategy tests; all 57 tests passed, including the existing execution and market-data suites. Every strategy output matched the original notebook across the 8,760-row snapshot: 78 bullish/78 bearish crossovers, 78 entries/77 exits, final desired state 1.
- Updated and executed all 12 EMA notebook code cells using the reusable function; preserved its charts and research explanations. Updated current-stage documentation; raw data and dependencies are unchanged. Strategy/execution composition, PnL, and a trade ledger remain deferred.

## 2026-10-02 — Stage 4.2 minimal execution helper

- Added a pure next-candle-OPEN execution helper with initial flat state, delayed row-level position changes, explicit signal-row fill metadata, final-candle handling, and rejection of invalid transitions and hourly inputs.
- Added 23 synthetic tests covering decision 002 cases A–G and validation; all 36 tests passed, including the existing 13 market-data tests.
- Updated current-stage documentation. Preserved EMA notebook behavior, raw data, and dependencies; no PnL, trade ledger, or full backtesting engine was added.

## 2026-10-02 — Stage 4.1 backtesting execution contract

- Recorded next-candle-OPEN execution, completed-candle signal availability, desired/executed state separation, long-only transitions from initial flat state, and unexecutable final-candle events in decision 002.
- Documented acceptance cases A–G and updated current-stage documentation; all 13 existing tests passed. No execution helper, new tests, backtest loop, PnL, or portfolio simulation was added; Stage 3.1 logic and raw data remain unchanged.

## 2026-10-02 — Stage 3.1 EMA logic cleanup before backtesting

- Added 50 initialization-only candles, renamed research state to `desired_position`, and gated entry/exit signals by prior state.
- Strengthened warm-up, alternating-event, HOLD-stability, state-transition, and causal-prefix checks; clarified completed-candle signal availability and separate future execution.
- Refreshed README and project state while preserving earlier milestone history. All 12 notebook code cells passed: 78 bullish/78 bearish eligible crossovers, 78 valid entries/77 valid exits, final desired state 1. Raw CSV remained unchanged; no backtest or processed data was added.

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
