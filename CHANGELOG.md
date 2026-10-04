# Changelog

## 2026-10-04 — Stage 5.7 trade duration and exposure contract

- Added decision 005 defining ledger fill timestamps, half-open CLOSED durations, explicit market-window boundaries/denominator, and binary time-in-market exposure. The final OPEN interval contributes to exposure while completed-duration statistics exclude it; no GROSS/NET split is needed because current costs do not change fill timing.
- Documented worked/denominator examples, empty/OPEN-only/full-exposure cases, timezone/window/order/overlap validation, two future APIs, a six-column per-trade table, and a separate 11-field `TIME` summary. Updated current-stage documentation; implementation remains pending approval.
- All 216 existing tests passed. Documentation only: production code, tests, notebooks, raw BTC CSV, dependencies, and decisions 001–004 remain unchanged. Stage 5.8 implementation is recommended but not started.

## 2026-10-04 — Stage 5.6 realized-capital drawdown notebook integration

- Integrated the four unchanged Stage 5.5 helpers into notebook 03 after its CLOSED-trade summary and before cost analysis. Added a separate Gross/Net drawdown table, beginner explanations, one drawdown plot with derived trough markers, and regression/OPEN-exclusion/preservation assertions. The 16-metric table and two existing plots are retained; no financial metric formulas or mark-to-market valuation were added.
- Executed all 25 code cells successfully with sequential counts and no saved errors: 52 total cells, 27 Markdown, three visually inspected plots. Both paths have 78 observations for 77 CLOSED trades. GROSS/NET maximum realized drawdown remains -26.723425% / -37.185533%, at observations 33 / 66; final capital is 9,641.111388344 / 7,652.530163437 USDT. OPEN removal leaves both paths/summaries identical; accounting inputs and the raw-file hash are preserved.
- All 216 existing tests passed; updated stage documentation. Production code/tests, including `drawdown.py` and `trade_metrics.py`, decisions, notebooks 01/02, raw BTC CSV, and dependencies remain unchanged. Stage 5.7 duration/exposure contract is recommended but not started.

## 2026-10-04 — Stage 5.5 reusable realized-capital drawdown

- Implemented decision 004 unchanged with explicit gross/net path and summary functions, canonical CLOSED capital sources, the initial observation, negative drawdown/amount conventions, source-specific validation, and earliest-minimum associated amounts. OPEN remains excluded and unvalued; the 16-metric trade summary stays unchanged.
- Added 32 synthetic tests, including actual Stage 4 accounting integration; all 216 tests passed. BTC paths contain 78 points for 77 CLOSED trades. Maximum realized-capital drawdown is -26.723425% GROSS at observation 33 (-2,672.342545499 USDT) and -37.185533% NET at observation 66 (-3,718.553326267 USDT), under research cost assumptions. Final capitals match 9,641.111388344 / 7,652.530163437 USDT; OPEN removal leaves paths/summaries identical.
- Updated stage documentation and the limitation versus mark-to-market drawdown. Stage 4 code/tests, existing analytics/tests, all decisions, notebooks 01/02/03, raw BTC CSV, and dependencies remain unchanged. Notebook integration and Stage 5.6 have not started.

## 2026-10-03 — Stage 5.4 realized-capital drawdown contract

- Added decision 004 for independent gross/net capital paths with mandatory initial capital, CLOSED-only observations, running peaks, negative drawdown/amount conventions, maximum drawdown, edge cases, future validation/API/output direction, and the limitation versus mark-to-market portfolio drawdown. OPEN remains excluded and unvalued; the existing 16 metrics stay unchanged.
- Updated current-stage documentation. All 184 existing tests passed; production code, tests, notebooks, raw CSV, dependencies, and earlier decisions remain unchanged. Drawdown implementation and BTC measurement await Stage 5.5 approval.

## 2026-10-03 — Stage 5.3 performance summary notebook integration

- Integrated the unchanged Stage 5.2 gross/net summary helpers into notebook 03 using its existing accounting outputs. Added a formatted 16-metric comparison, practical BTC explanations, and regression/OPEN-exclusion assertions without duplicating metric formulas.
- Executed all 21 code cells successfully with sequential counts and no errors: 44 cells total, 23 Markdown, two retained plots. Both paths have 77 CLOSED trades (20 WIN/57 LOSS/no BREAKEVEN); gross/net expectancy is -4.660891060 / -30.486621254 USDT and profit factor 0.945165760246 / 0.675088667158. The final OPEN trade remains excluded and unvalued.
- All 184 existing tests passed. Updated stage documentation; production code/tests, decision 003, raw CSV, notebooks 01/02, and dependencies remain unchanged. Stage 5.4 drawdown contract is recommended but not started.

## 2026-10-03 — Stage 5.2 reusable CLOSED-trade performance summary

- Implemented decision 003 with explicit gross/net summary functions, a private shared calculation helper, exact 16-column one-row output, integer counts, return-based tolerance classification, and PnL-based expectancy/profit factor. Validation and source guards reject malformed CLOSED values and wrong accounting schemas; OPEN rows are excluded without valuation.
- Added 35 synthetic tests; all 184 tests passed. BTC summaries both retain 77 CLOSED trades (20 WIN/57 LOSS/no BREAKEVEN). Gross/net total PnL is -358.888611656 / -2,347.469836563 USDT and profit factor 0.945165760246 / 0.675088667158; OPEN removal leaves every metric unchanged.
- Updated stage documentation. Stage 4 code/tests, notebooks, raw CSV, decision 003, and dependencies remain unchanged. No Stage 5.3 or additional metrics were introduced.

## 2026-10-03 — Stage 5.1 CLOSED-trade performance metric contract

- Added decision 003 defining CLOSED-only metric sources, counts/rates, return statistics, total realized PnL, sample expectancy, and profit factor. Gross uses Stage 4.6; net uses Stage 4.7, with independent return-based classification and a `1e-12` breakeven tolerance.
- Documented OPEN exclusion, residual handling, empty/subset cases, NaN/infinity profit-factor behavior, and Stage 5.2 validation invariants. Updated stage documentation; analytics implementation remains pending approval.
- All 149 existing tests passed. Documentation only: no source, tests, notebooks, raw data, or dependencies changed.

## 2026-10-02 — Stage 4.8 backtest research notebook

- Added and executed `notebooks/03_backtest_review.ipynb` end to end using the existing local loader, EMA/execution pipeline, trade ledger, and independent gross/net accounting helpers. All 18 code cells ran successfully; 38 total cells include comparison tables, first-trade/OPEN inspections, and two Matplotlib plots.
- Confirmed 8,760 candles, 78 entry/77 exit signals, and 77 CLOSED/one OPEN trade. From 10,000 USDT, gross/net realized capital is 9,641.111388344 / 7,652.530163437 USDT (-3.588886% / -23.474698%), with a 1,988.581224907 USDT gap under research cost assumptions. OPEN remains unvalued.
- All 149 existing tests passed; updated stage documentation. Raw CSV, notebooks 01/02, reusable modules/tests, dependencies, and architecture remain unchanged. No new production financial logic or Stage 5 analytics was added.

## 2026-10-02 — Stage 4.7 transaction costs

- Added separate cost-aware ledger accounting with adverse entry/exit slippage, effective-notional fees, self-financing sizing, and net compounding. OPEN trades record entry costs without exit results or valuation; the Stage 4.6 zero-cost helper is unchanged.
- Added 21 transaction-cost tests; all 149 tests passed. Full BTC zero-cost equivalence and accounting identities passed. Test rates of 0.10% fee and 0.05% slippage per side produce final CLOSED-trade net capital of 7,652.530163437 USDT versus gross capital of 9,641.111388344 USDT; these assumptions are not current Bybit fees.
- Updated stage documentation. Strategy, execution, pipeline, ledger, raw data, notebooks, architecture, and dependencies remain unchanged. No unrealized PnL, equity curve, performance metrics, or trading integration was added.

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
