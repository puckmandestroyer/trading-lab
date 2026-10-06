# Changelog

## 2026-10-06 — Stage 7.7 — Exact Regression + Analytics Compatibility

- Preserved the complete frozen full-allocation Stage 5/6 regression and added canonical real-BTC 50%/25% analytics snapshots. Execution/ledger, duration/exposure, and benchmark paths remain fraction-independent; reserve-aware partial equity works with existing trade, drawdown, hourly-return, and Sharpe/Sortino analytics. No production code, analytics API/formula, old test, decision, notebook, dependency, or data changes; no download or notebook execution.
- All 37 new regression methods and every required targeted module pass; the full suite passed once with 747 tests (710 existing + 37 new), zero failures, errors, or skips. Existing references and tolerances are unchanged. Stage 7.8 — Position Sizing Notebook awaits explicit owner approval and has not started.

## 2026-10-06 — Stage 7.6 — Generic Backtest Integration

- Added final positional-or-keyword `position_fraction=1.0` to the generic pipeline, always forwarding the same value unchanged to independent GROSS/NET accounting. The pipeline remains call-order-only, with no risk import, sizing, or fraction validation. Strategy/execution/ledger behavior, four return keys, schemas, and exact default compatibility are preserved; reserve-aware equity remains optional downstream.
- All 24 new synthetic pipeline tests, 15 retained generic pipeline tests, 25 GROSS sizing tests, 33 NET sizing tests, and 31 partial-equity tests pass; the full suite passed once with 710 tests (686 existing + 24 new), zero failures, errors, or skips. Frozen Stage 6 references/tolerances, lower production layers, decisions, notebooks, dependencies, and data are unchanged; no notebook execution. Stage 7.7 — Exact Regression + Analytics Compatibility awaits explicit owner approval and has not started. The broad partial analytics audit and Stage 7 notebook remain pending.

## 2026-10-06 — Stage 7.5 — MTM Equity / Reserve Cash

- Made candle-CLOSE GROSS/NET equity reserve-aware using canonical quantity, basis, and total capital. GROSS spend is quantity times entry price; NET spend includes effective entry value and the paid entry fee. Reserve stays cash while LONG; actual exit capital remains authoritative. Existing public APIs, eleven-column schema, dtypes, timing, unrealized semantics, and exact all-in compatibility are preserved; no hypothetical liquidation costs.
- All 31 new synthetic partial-equity tests, 47 unchanged equity tests, 25 GROSS sizing tests, and 33 NET sizing tests pass; the full suite passed once with 686 tests (655 existing + 31 new), zero failures, errors, or skips. Frozen Stage 6 MTM references are unchanged. Accounting, risk, pipeline, other analytics, old tests, decisions, notebooks, dependencies, and data are unchanged; no notebook execution. Generic fraction forwarding and the broad partial analytics audit remain pending. Stage 7.6 — Generic Backtest Integration awaits explicit owner approval and has not started.

## 2026-10-06 — Stage 7.4 — NET Accounting Integration

- Added trailing `position_fraction=1.0` to `calculate_trade_results_with_costs(...)`, delegating current NET capital budgets to the unchanged sizing helper, including empty-ledger validation. Entry notional plus entry fee equals the budget; reserve is derived outside the position and total NET capital compounds independently. Existing costs, return meanings, twenty-column schema, and OPEN behavior are preserved.
- All 33 new synthetic tests, 21 unchanged transaction-cost tests, 25 GROSS sizing tests, and 35 sizing-core tests pass; the full suite passed once with 655 tests (622 existing + 33 new), zero failures, errors, or skips. Exact default/full-allocation parity and frozen Stage 6 EMA regression remain green without tolerance changes. GROSS, risk core, equity, pipeline, execution/ledger, old tests, decisions, notebooks, dependencies, and data are unchanged; no notebook execution. End-to-end partial-allocation analytics remain pending. Stage 7.5 — MTM Equity / Reserve Cash awaits explicit owner approval and has not started.

## 2026-10-06 — Stage 7.3 — GROSS Accounting Integration

- Added trailing `position_fraction=1.0` to `calculate_trade_results(...)`, delegating current-capital budgets to the unchanged sizing helper, including empty-ledger validation. Partial quantities/PnL compound total capital; raw position-return semantics, eleven-column schema, derived reserve, and OPEN behavior are preserved.
- All 25 new synthetic tests, 27 unchanged GROSS tests, and 35 sizing-core tests pass; the full suite passed once with 622 tests (597 existing + 25 new), zero failures, errors, or skips. Exact default/full-allocation parity and frozen Stage 6 EMA regression remain green without tolerance changes. NET, equity, pipeline, risk core, execution/ledger, old tests, decisions, notebooks, dependencies, and data are unchanged; no notebook execution. End-to-end partial allocation remains pending. Stage 7.4 — NET Accounting Integration awaits explicit owner approval and has not started.

## 2026-10-06 — Stage 7.2 — Position Sizing Core

- Added `risk/position_sizing.py` with `calculate_position_budget(capital_before, position_fraction=1.0) -> float`: current-capital budgeting, fraction `(0, 1]`, default 1.0, and a positive finite Python float result. Rejects bools, non-scalars, invalid numeric values, unsafe conversion overflow/underflow, and zero-underflow products without coercion or clamping.
- Added 35 synthetic scalar unittest methods; targeted tests and the full 597-test suite (562 existing + 35 new) passed with zero failures, errors, or skips. No accounting/pipeline/equity integration, existing production/test/decision/notebook/dependency/data changes, or notebook execution. Stage 7.3 — GROSS Accounting Integration awaits explicit owner approval and has not started.

## 2026-10-06 — Stage 7.1 — Risk & Position Sizing Contract

- Accepted Decision 011: a fixed current-capital allocation fraction in `(0, 1]`, default 1.0, reserve-cash/OPEN semantics, and an exact Stage 6 compatibility requirement. Strategy owns intent, risk returns a budget, execution owns fills, and accounting calculates quantity/costs/PnL; equity must retain reserve cash.
- Recorded the accepted 7.1–7.9 roadmap and updated current project documentation. No production, test, notebook, decisions 001–010, dependency, or data changes; no notebook execution. Stage 7.2 — Position Sizing Core awaits explicit owner approval and has not started.

## 2026-10-05 — Stage 6.7 — Final Stage 6 Audit + Docs

- Stage 6 is COMPLETE. Final contract/API, architecture, linear commit-chain, and exact 12-file scope audits passed. All 104 Stage 6 methods and the full 562-test suite passed with zero failures, errors, or skips; real BTC exact EMA regression and frozen Stage 5 implementation/references are preserved.
- Audited committed notebook 04's saved state: 23 cells, counts 1–11, zero errors, one image. Neither notebook 03 nor 04 was re-executed. Corrected stale current-state documentation; no production code, test, notebook, decision, dependency, data, or financial-formula changes. Stage 7 — Risk Manager + Position Sizing has not started and awaits explicit owner approval.

## 2026-10-05 — Stage 6.6 — Generic Backtest Notebook

- Added and executed `notebooks/04_generic_backtest_engine.ipynb`: 23 cells (11 code / 12 Markdown), sequential counts 1–11, zero saved errors, and one embedded equity plot. Demonstrates existing EMA intent → generic execution/ledger/independent GROSS/NET accounting, separate equity helpers, and a tiny synthetic non-EMA contract example; frozen sanity and preservation checks pass.
- Updated notebook/project documentation. All 562 existing tests passed once; no new tests, production modules, dependencies, or financial formulas. Earlier notebooks including frozen notebook 03, `.py` placeholders, old tests, decisions, and raw data are unchanged. Only notebook 04 was executed; no download or external API call. Stage 6.7 awaits approval and has not started; Stage 7 has not started.

## 2026-10-05 — Stage 6.5 — EMA Exact Regression / Compatibility

- Added `tests/test_ema_generic_regression.py`: the frozen local BTC snapshot/hash passes exact legacy/generic EMA strategy, execution, ledger, GROSS/NET accounting, and MTM parity. Existing Stage 5 trade, drawdown, time/exposure, risk-adjusted, and benchmark references pass with unchanged tolerances; the final trade remains OPEN.
- All 16 new regression methods ran with zero failures, errors, or skips; the full suite passed once with 562 tests (546 existing + 16 new). No production modules, old tests, decisions, notebooks, raw data, or dependencies changed; no download, notebook execution, or EMA wrapper migration. Stage 6.6 awaits approval and has not started; Stage 7 has not started.

## 2026-10-05 — Stage 6.4 — Generic End-to-End Backtest Integration

- Added `run_backtest_pipeline(...)` in `backtest/pipeline.py`: call-order-only composition of generic execution, ledger, and independent GROSS/NET accounting, returning exactly `execution`, `trades`, `gross_results`, and `net_results`. Existing helpers own all schemas, validation, and financial mathematics; final no-fill/OPEN rules are preserved.
- Added 15 synthetic unittest methods; the full suite passed once with 546 tests (531 existing + 15 new). Non-EMA intent, exact helper parity, costs/compounding, diagnostics, error propagation, preservation, and index/timezone cases pass. Existing pipeline functions, lower layers, EMA, analytics, old tests, decisions, notebooks, dependencies, data, and Stage 5 logic are unchanged. No new BTC scenario or notebook execution. Stage 6.5 awaits approval and has not started; Stage 7 has not started.

## 2026-10-05 — Stage 6.3 — Generic Execution Pipeline

- Added `run_execution_pipeline(candles, strategy_output)` in `backtest/pipeline.py`, delegating canonical validation and existing next-OPEN execution. Returns the exact six-column execution output, uses authoritative candle OPEN values, ignores diagnostics, preserves inputs, and checks composition postconditions.
- Added 25 synthetic unittest methods; all 531 tests pass (506 existing + 25 new). Direct-helper parity, final no-fill rules, namespace collisions, delegation, preservation, and prefix behavior pass. Existing EMA pipeline/alignment helper, execution, validator, EMA strategy, old tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic are unchanged. Stage 6.4 awaits approval and is not started; Stage 7 has not started.

## 2026-10-05 — Stage 6.2 — Generic Strategy Signal Validation

- Added `backtest/strategy_validation.py` with pure `validate_strategy_output(candles, strategy_output)`: decision 010 canonical fields, strict alignment, elapsed-hour availability, and integer/state-machine validation; returns an independent full output with diagnostics preserved.
- Added 48 synthetic unittest methods covering contract/edge cases, EMA compatibility, DST, and preservation. All 506 tests pass (458 existing + 48 new). Pipeline, execution, EMA, existing tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic remain unchanged. Stage 6.3 awaits approval and is not started; Stage 7 has not started.

## 2026-10-05 — Stage 6.1 — Generic Strategy / Backtest Contract

- Accepted decision 010: canonical strategy fields, candle/index alignment, desired-state transitions, next-OPEN/final-candle rules, optional diagnostics, causality responsibilities, future acceptance cases, and frozen EMA regression references.
- Documentation only; production code, tests, notebooks, dependencies, data, and decisions 001–009 are unchanged. All 458 existing tests pass; no new tests. Stage 5 remains COMPLETE; Stage 6.2 awaits owner approval and is not started. Stage 7 has not started.

## 2026-10-04 — Stage 5.18 final Stage 5 analytics report

- Consolidated notebook 03 using existing outputs: setup, four-portfolio headline comparison, EMA behavior, integrated interpretation, limitations, and one final audit checking financial/risk/time references, raw data, and 31 report-source DataFrames.
- Executed all 104 cells (51 code / 53 Markdown) sequentially without saved errors. All seven existing plot sources/images are unchanged; no plot was added. All 458 existing tests pass; no production code, tests, decisions, dependencies, financial formulas, or other notebooks changed, and no project files were created.
- Stage 5 — Analytics completed. Review and commit Stage 5.18 first; Stage 6 awaits explicit owner approval and has not started.

## 2026-10-04 — Stage 5.17 float64 equity validation hardening

- Reject unsafe nonzero-to-zero float64 equity underflow; genuine final zero remains valid. Added four regression tests: 61 Stage 5.17 tests and all 458 tests pass. Financial formulas, BTC metrics, and notebook are unchanged.

## 2026-10-04 — Stage 5.17 time-based returns and Sharpe / Sortino

- Accepted decision 009; added `analytics/risk_adjusted.py` with simple consecutive-equity returns and a summary that reuses them. All four paths retain 8,760 hourly periods from 8,761 observations, including cash zeros/final OPEN marks. Explicit conventions: 8,760 periods/year, zero hourly rf/MAR, sample-std Sharpe, all-period downside Sortino. Added 57 tests; all 454 pass (397 existing + 57 new).
- Actual BTC Sharpe/Sortino: EMA GROSS -0.0654209479 / -0.0955348305; EMA NET -0.9029552504 / -1.3087247421; Buy-and-Hold GROSS -0.4873945323 / -0.6833501112; NET -0.4908162375 / -0.6881424711. Support metrics are documented in PROJECT_STATE/README; no general superiority or statistical significance is claimed.
- Notebook 03 adds compact summaries/previews, interpretation, assertions, and one NET hourly-return diagnostic: 96 cells (47 code / 49 Markdown), seven plots, sequential execution, no saved errors. All six previous plot sources/images, existing modules/tests, decisions 001–008, notebooks 01/02, raw data, and dependencies are unchanged. Stage 5.18 — Final Stage 5 Analytics Notebook / Report is recommended but not started; no Stage 6 work.

## 2026-10-04 — Stage 5.16 benchmark comparison

- Accepted decision 008 and added two reusable Buy-and-Hold APIs in `analytics/benchmark.py`: first-OPEN purchase, independent Stage 4 GROSS/NET accounting, Stage 5.11 CLOSE equity, and existing portfolio-drawdown helpers. NET incurs one actual entry fee/slippage; no final exit is fabricated. Added 38 tests; all 397 pass (359 existing + 38 new).
- Both BTC benchmark paths have 8,761 aligned observations. Final marked equity is GROSS 7,331.468087550229 / NET 7,320.483701755746 USDT; whole-window returns -26.6853191245% / -26.7951629824%, maximum drawdowns both -53.7338388920%. EMA ends ahead by 2,120.017226389085 / 170.292861096195 USDT, or 21.2001722639 / 1.7029286110 percentage points; all four paths lose capital in this sample.
- Notebook 03 adds compact comparisons, explanation, assertions, and exactly one equity plot: 88 cells (43 code / 45 Markdown), six plots, sequential execution, no saved errors. All five previous plot sources/images, earlier production modules/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are preserved. No Sharpe/Sortino or Stage 6 work. Stage 5.17 — Time-Based Returns + Sharpe / Sortino is recommended but not started.

## 2026-10-04 — Stage 5.15 candle-close portfolio drawdown notebook integration

- Integrated the four unchanged Stage 5.14 helpers into notebook 03 after MTM equity and before TIME, using existing equity paths directly. Added compact GROSS/NET summary/comparison/episode previews, final OPEN explanation, exactly one time-axis drawdown plot with helper-selected troughs, and regression/preservation assertions; no financial formulas were duplicated.
- Both paths retain 8,761 observations: maximum GROSS -27.6794381422% / NET -37.9679609807%, versus 78-point realized drawdowns -26.7234254550% / -37.1855332627%. Final OPEN marks participate naturally, with final drawdowns -7.6771641106% / -25.2825731282%. Peak/trough details remain documented in PROJECT_STATE/README and now appear in notebook tables.
- Executed all 39 code cells sequentially without saved errors: 80 cells total, 41 Markdown, five plots, with all four original plot sources/images unchanged. All 359 tests pass; production code/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are unchanged. No benchmark, Sharpe/Sortino, or duration/recovery was added; Stage 5.16 — Benchmark Comparison is recommended but not started.

## 2026-10-04 — Stage 5.14 reusable candle-close portfolio drawdown

- Added `analytics/portfolio_drawdown.py` with decision 007's four pure GROSS/NET path/summary functions, strict three-field validation, causal peaks, exact earliest-trough/latest-peak selection, and preserved input/schema semantics. Added 55 synthetic/integration tests; all 359 tests pass.
- The unchanged BTC pipeline yields 8,761 drawdown rows per path: maximum GROSS -27.6794381422% / NET -37.9679609807%, with associated amounts -2,779.158887053809 / -3,806.4682385473616 USDT. Final OPEN marks are naturally included; separate 78-point realized drawdown remains -26.7234254550% / -37.1855332627%. Peak/trough details and final marks are documented in PROJECT_STATE/README.
- Preserved existing production modules/tests, decisions 001–007, all notebooks, raw data, and dependencies. Scope remains candle-CLOSE; duration/recovery and further metrics are deferred. Stage 5.15 notebook integration is recommended but not started.

## 2026-10-04 — Stage 5.13 candle-close portfolio drawdown contract

- Accepted decision 007: existing independent GROSS/NET equity paths, negative drawdown/amount formulas, exact six-column path/eight-field summary, earliest-trough/latest-peak selection, initial/zero-equity behavior, strict validation, and input preservation. Identical source schemas express caller intent through wrappers; final OPEN marks are naturally included.
- Preserved decision 004's separate CLOSED-only realized observations and documented candle-CLOSE intrabar limitations. Finalized four future APIs; implementation, BTC portfolio drawdown measurement, duration/recovery, and further metrics remain deferred to approved future work.
- Updated current-stage documentation; all 304 existing tests pass. Production code/tests, notebooks, raw data, dependencies, and decisions 001–006 remain unchanged. Stage 5.14 is recommended but not started.

## 2026-10-04 — Stage 5.12 candle-level equity notebook integration

- Integrated the two unchanged Stage 5.11 equity helpers into notebook 03 after realized drawdown and before TIME. Added compact initial/first-entry/final previews, a realized-versus-marked table, final OPEN state, one GROSS/NET time-axis equity plot, and regression/input/path-preservation checks; no equity formulas were duplicated.
- Both paths have 8,761 observations from 8,760 candles. Trade 78 stays OPEN at final CLOSE 83,616.2 USDT: GROSS marked equity 9,451.485313939314 / NET 7,490.776562851941 USDT, distinct from CLOSED realized capital 9,641.111388344 / 7,652.530163437 USDT. Representative exits 1, 39, and 77 reconcile in both paths; no hypothetical liquidation costs or realized OPEN results are added.
- Executed all 33 code cells sequentially without saved errors: 68 cells total, 35 Markdown, four plots, with all three original images/code unchanged. All 304 tests pass; production code/tests, decisions 001–006, notebooks 01/02, raw data, and dependencies are unchanged. No portfolio drawdown was calculated; Stage 5.13 contract is recommended but not started.

## 2026-10-04 — Stage 5.11 reusable candle-level mark-to-market equity

- Implemented decision 006 in `analytics/equity.py` with independent pure GROSS/NET helpers, the exact 11-column N + 1 path, canonical accounting reuse, OPEN-before-CLOSE event ordering, and OPEN marking without hypothetical liquidation costs or duplicated paid fees.
- Added 47 synthetic tests; all 304 tests pass. The unchanged 8,760-candle BTC flow produces 8,761 rows per path and marks final OPEN trade 78 at CLOSE 83,616.2 USDT: GROSS equity 9,451.485313939314 / NET 7,490.776562851941 USDT under the established research cost assumptions. All 77 CLOSED exits reconcile per path.
- Updated current-stage documentation. Stage 4, existing analytics/tests, decisions 001–006, notebooks, raw data, and dependencies remain unchanged. Scope is candle-close, long-only, single-position, all-in accounting; portfolio drawdown and Stage 5.12 notebook integration remain deferred.

## 2026-10-04 — Stage 5.10 candle-level portfolio equity contract

- Added decision 006 defining an initial-before-fill point plus one raw CLOSE mark per candle, OPEN-fill-before-CLOSE ordering, shared-OPEN EXIT then ENTRY, independent canonical GROSS/NET sources, and incurred-cost semantics without hypothetical liquidation costs.
- Finalized future pure APIs, the exact 11-column path/initial row, validation/timezone/no-lookahead rules, OPEN/final-fill cases, flat realized-capital reconciliation, a worked example, and the candle-close risk limitation. Updated stage documentation; implementation remains pending Stage 5.11 approval.
- All 257 existing tests pass. Production code, tests, all notebooks, raw data, dependencies, and decisions 001–005 are unchanged. No equity/portfolio-drawdown code or BTC mark-to-market results were added.

## 2026-10-04 — Stage 5.9 trade duration and exposure notebook integration

- Integrated the two unchanged Stage 5.8 helpers into notebook 03 directly from its canonical ledger and explicit 8,760-hour candle window, after drawdown and before costs. Added one 11-field TIME table, a compact first/last preview, top-five CLOSED-duration inspection, explanations/conclusions, and regression/preservation assertions. No GROSS/NET time split, duplicated formulas, or new financial metrics.
- BTC references pass: 77 CLOSED / one OPEN; average/median/minimum/maximum CLOSED durations 52.96103896103896 / 34 / 1 / 226 hours; total CLOSED 4,078 hours plus 11 observed final OPEN hours gives 4,089 hours in market and 46.678082% exposure. First CLOSED duration is 27 hours; longest is trade 68 / 226 hours. OPEN trade 78 entered at 2026-09-30 13:00 UTC; completed duration stays NaN and it remains unvalued.
- Executed all 28 code cells sequentially with no saved errors: 58 total cells, 30 Markdown, three byte-identical existing plot images. Existing tables and ledger/raw preservation checks pass. All 257 tests pass; production analytics/Stage 4 code and tests, decisions 001–005, notebooks 01/02, raw CSV, and dependencies are unchanged. Updated documentation and fixed stale README analytics listings. Stage 5.10 equity/mark-to-market contract is recommended but not started.

## 2026-10-04 — Stage 5.8 reusable trade duration and exposure

- Implemented decision 005 unchanged in `analytics/trade_time.py` with `calculate_trade_time_breakdown` and `summarize_trade_time_metrics`, explicit observation boundaries, the exact six-column breakdown and 11-field TIME summary, and shared interval validation. CLOSED statistics exclude OPEN; its observed final interval contributes to binary exposure without a synthetic exit, valuation, or GROSS/NET split.
- Added 41 synthetic tests, including fractional/DST elapsed time, boundaries, empty/OPEN-only/full exposure, order/overlap and timestamp validation, preservation, exact schemas/dtypes, and actual Stage 4 ledger integration. All 257 tests passed. The offline BTC ledger has 77 CLOSED / one OPEN over 8,760 hours: 4,078 CLOSED hours plus 11 OPEN hours gives 4,089 hours in market and exposure `0.46678082191780823`.
- Updated stage documentation with full BTC time results and the single-position limitation. Stage 4 modules/tests, existing analytics/tests, decisions 001–005, notebooks 01/02/03, raw BTC CSV, and dependencies remain unchanged. Stage 5.9 notebook integration is recommended but not started.

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
