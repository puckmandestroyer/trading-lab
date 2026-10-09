# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 8 — Strategy Robustness is COMPLETE.

Stage 8.8 — Final Stage 8 Audit + Docs is COMPLETE. All milestones 8.1–8.8 are complete under Accepted Decision 012.

Stage 8.7 — Strategy Robustness Notebook remains COMPLETE and unchanged.

Stage 8.6 — Robustness Summary / Diagnostics remains COMPLETE and unchanged.

Stage 8.5 — Walk-Forward Evaluation remains COMPLETE and unchanged.

Stage 8.4 — Parameter Stability Analysis remains COMPLETE and unchanged.

Stage 8.3 — Parameter Sensitivity Engine remains COMPLETE and unchanged.

Stage 8.2 — Time Split / OOS Evaluation Core remains COMPLETE and unchanged.

Stage 8.1 — Robustness Contract is COMPLETE; Decision 012 is Accepted.

Stage 7 — Risk Manager + Position Sizing is COMPLETE.

Stage 7.9 — Final Stage 7 Audit + Docs completed.

Stage 7.8 — Position Sizing Notebook remains complete.

Stage 7.7 — Exact Regression + Analytics Compatibility remains complete.

Stage 7.6 — Generic Backtest Integration remains complete.

Stage 7.5 — MTM Equity / Reserve Cash remains complete.

Stage 7.4 — NET Accounting Integration remains complete.

Stage 7.3 — GROSS Accounting Integration remains complete.

Stage 7.2 — Position Sizing Core remains complete.

Stage 7.1 — Risk & Position Sizing Contract remains Accepted as Decision 011.

Stage 6 — Generic Backtesting Engine remains COMPLETE at `df72973de837ecbd4ee81f4bdaf77efd74730a56`.

Stage 5 — Analytics remains COMPLETE and frozen at `a3fde091be234fd78d216f6338752a810fa117f0` (`Complete Stage 5 analytics report`).

## Completed

Milestone entries retain the status and test totals recorded at their completion; current status and next focus are stated separately.

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
- Stage 4.1 execution contract recorded in `decisions/002_backtest_execution_contract.md`: completed-candle signals map to the next candle's OPEN, with separate desired/executed state, initial executed state 0, and no execution for final-candle events without a next candle.
- Stage 4.1 documented acceptance cases A–G without implementing execution. All 13 existing market-data tests passed during that milestone.
- Stage 4.2 added the pure function `apply_next_open_execution(candles: pd.DataFrame) -> pd.DataFrame` in `src/trading_lab/backtest/execution.py`, consuming pre-generated signals without generating strategy decisions.
- Required input columns: `timestamp`, `open`, `signal`. Exact output columns: `timestamp`, `open`, `signal`, `execution_time`, `execution_price`, `executed_position`. Optional input columns are neither required nor copied into the output; input is not modified.
- Execution metadata on signal row N describes its fill at N+1 OPEN. `executed_position` describes state during the row's candle: initial 0, with N's event changing state only on N+1. Valid final-candle events retain their signal with missing execution metadata and no resulting state change; invalid transitions raise `ValueError`, including on the final candle.
- Added 23 synthetic execution tests covering cases A–G, invalid inputs, hourly continuity, input preservation, and edge cases. All 36 tests passed, including the existing 13 market-data tests. Stage 3.1 notebook, raw data, and dependencies remain unchanged. No PnL, trade ledger, or full backtesting engine was added.
- Stage 4.3 added `generate_ema_signals(candles: pd.DataFrame, fast_span: int = 20, slow_span: int = 50, warmup_candles: int = 50) -> pd.DataFrame` in `src/trading_lab/strategies/ema_trend.py`. It requires only `timestamp` and `close`, returns a new DataFrame, and remains independent of execution, files, and exchange APIs.
- Exact default strategy output: `timestamp`, `close`, `ema_20`, `ema_50`, `warmup_complete`, `bullish_cross`, `bearish_cross`, `signal`, `desired_position`, `signal_time`. Custom spans use `ema_{fast_span}` and `ema_{slow_span}`. Optional input columns are omitted; input values and index are preserved.
- Preserved first-close EWM seeding with `adjust=False`, 50 initialization-only candles, eligibility from candle 51, crossover equality rules, prior desired-state gating, and `signal_time = timestamp + 1 hour`. No entry is synthesized when warm-up ends in a bullish regime.
- Local snapshot regression exactly matched the original notebook across all 8,760 rows and ten strategy columns: 78 bullish/78 bearish crossovers, 78 entries/77 exits, first entry candle 2025-10-13 02:00 UTC (signal 03:00), first exit candle 2025-10-14 05:00 UTC (signal 06:00), final desired state 1.
- Added 21 synthetic strategy tests covering warm-up, crossovers, state gating, HOLD stability, event alternation, causality, input preservation, timing, parameters, validation, and edge cases. All 57 tests passed: 21 strategy, 23 execution, and 13 market-data tests.
- Updated `notebooks/02_ema_strategy.ipynb` to import the reusable strategy instead of duplicating its calculations. All 12 code cells executed successfully; notebook outputs match the function, fixed snapshot results are asserted, and both charts and inspection tables are retained. Raw CSV, earlier exploration notebook, execution helper, architecture decisions, and dependencies remain unchanged. No strategy/execution composition, PnL, or trade ledger was added.
- Stage 4.4 added `run_ema_execution_pipeline(candles: pd.DataFrame, fast_span: int = 20, slow_span: int = 50, warmup_candles: int = 50) -> pd.DataFrame` in `src/trading_lab/backtest/pipeline.py`. It orchestrates the existing strategy and execution helpers without duplicating their logic or modifying input.
- Required pipeline inputs: `timestamp`, `open`, `close`. Exact default output: `timestamp`, `open`, `close`, `ema_20`, `ema_50`, `warmup_complete`, `bullish_cross`, `bearish_cross`, `signal`, `desired_position`, `signal_time`, `execution_time`, `execution_price`, `executed_position`. Custom spans retain dynamic EMA names; optional market-context columns are omitted.
- Each component's output must match the input row count, index, timestamp values, and chronological order before columns are combined; mismatches raise `ValueError`. Execution output must preserve strategy signals. Existing validation errors propagate without signal repair or index resetting.
- Preserved 50-candle initialization, separate desired/executed states, source-signal-row fill metadata, and next-candle-OPEN execution. A final event has no fill; appending its next candle may populate only that former final row's execution metadata within the shared prefix, leaving its strategy output and executed state unchanged.
- Added 19 synthetic pipeline integration tests covering component consistency, row alignment and failures, input preservation, entry/exit timing, warm-up, final events, causal-prefix boundaries, and validation propagation. All 76 tests passed: 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC snapshot integration retained 8,760 rows, 50 warm-up candles, 78 bullish/78 bearish crossovers, 78 entries/77 exits, and the known first entry/exit signal timestamps. Both final desired and executed states are 1. First entry: candle 2025-10-13 02:00 UTC, signal and execution time 03:00 UTC, execution price 115,332.3 USDT verified against the receiving candle's OPEN; executed state is 0 on the signal row and 1 on the receiving row. Every strategy and execution output equals its direct component result.
- Raw data, both notebooks, existing strategy/execution modules and tests, architecture decisions, and dependencies remain unchanged. No additional notebook was needed; no PnL, trade ledger, capital, fees, or performance metrics were added.
- Stage 4.5 added the pure function `build_trade_ledger(backtest: pd.DataFrame) -> pd.DataFrame` in `src/trading_lab/backtest/trades.py`, called separately after the unchanged pipeline. Required inputs: `timestamp`, `signal`, `execution_time`, `execution_price`, `executed_position`.
- Exact ledger schema: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, `status`. IDs start at 1. Only recorded LONG_ENTRY/LONG_EXIT fills with both execution fields present open/close trades; prices and times come from source-signal-row execution metadata, not signal candle prices or desired state.
- CLOSED trades have both entry and exit fills. OPEN trades have an executed entry and missing exit time/price. A final unexecuted entry creates no trade; a final unexecuted exit leaves the existing trade OPEN. No exit is fabricated at dataset end.
- Ledger validation rejects partial execution metadata, invalid prices/signals, HOLD fills, non-chronological fills, invalid pairing, and inconsistent executed state. Source state must agree with prior recorded fills; where the receiving row exists, its timestamp/state must agree with the fill. No strategy or execution calculations are repeated.
- Added 25 synthetic ledger tests covering cases A–M, validation, empty/typed output, input preservation, and existing execution-helper integration. All 101 tests passed: 25 ledger, 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC integration verified actual fills individually: 78 executed entries and 77 executed exits produce 77 CLOSED trades and one final OPEN trade. First trade entry: 2025-10-13 03:00 UTC at 115,332.3 USDT; exit: 2025-10-14 06:00 UTC at 112,482.0 USDT. Final trade entered at 2026-09-30 13:00 UTC and remains OPEN with missing exit fields. Raw CSV, pipeline input/behavior, notebooks, existing modules/tests, architecture decisions, and dependencies remain unchanged; no PnL, returns, capital, fees, or valuation was added.
- Stage 4.6 added `calculate_trade_results(trades: pd.DataFrame, initial_capital: float = 10_000.0) -> pd.DataFrame` in `src/trading_lab/backtest/performance.py`, consuming the six-column Stage 4.5 ledger separately from pipeline and trade pairing.
- Exact required inputs: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, `status`. Exact output preserves those six columns and appends `capital_before`, `quantity`, `trade_return`, `gross_pnl`, `capital_after`; input context/index are preserved, optional columns omitted, and financial fields use float64.
- First accounting model: long-only spot economics, one trade at a time, 100% of current capital allocated, no leverage/borrowing, zero fees/commissions/slippage, and no quantity rounding. Default initial capital is 10,000 USDT. Quantity is `capital_before / entry_price`; CLOSED return is `exit_price / entry_price - 1`, gross PnL is `quantity * (exit_price - entry_price)`, and capital after is `capital_before + gross_pnl`, compounded into the next trade.
- A final OPEN trade receives capital before and quantity from its executed entry, with missing return, gross PnL, and capital after. Capital before means realized funds available before entering, not cash remaining after allocation. No market price is used to value an OPEN trade; no unrealized PnL or equity curve exists.
- Validation rejects invalid capital, IDs/status/order, overlapping trades, malformed exit metadata, invalid prices, multiple/non-final OPEN trades, and impossible numerical results. Added 27 synthetic accounting tests; all 128 tests passed: 27 accounting, 25 ledger, 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC integration retained 77 CLOSED trades and one OPEN trade. First trade return: -0.0247138052393; quantity: 0.0867059791576 BTC; gross PnL: -247.138052393 USDT; capital after: 9,752.861947607 USDT. Independent decimal arithmetic verified the first trade, and all CLOSED capital identities/compounding checks passed.
- From 10,000 USDT, realized capital after the final CLOSED trade is 9,641.111388344 USDT. The final OPEN trade has that capital before and quantity 0.1130341406801 BTC; it was not valued. Pipeline, ledger, existing tests/notebooks, raw CSV, architecture decisions, and dependencies remain unchanged; results remain in memory with no persistence.

- Stage 4.7 added `calculate_trade_results_with_costs(trades: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0) -> pd.DataFrame` in `src/trading_lab/backtest/costs.py`, called separately on the Stage 4.5 ledger. The Stage 4.6 helper and all earlier components remain unchanged.
- Output preserves the six ledger columns and appends `capital_before`, `effective_entry_price`, `effective_exit_price`, `quantity`, `entry_notional`, `exit_notional`, `entry_fee`, `exit_fee`, `total_fees`, `gross_pnl`, `price_adjusted_pnl`, `net_pnl`, `net_trade_return`, `net_capital_after`. Input is not modified or sorted; optional columns are omitted, index/timezone semantics preserved, and empty financial columns use float64.
- LONG effective entry/exit prices are recorded prices times `(1 + slippage_rate)` / `(1 - slippage_rate)`. Quantity is `capital_before / (effective_entry_price * (1 + fee_rate))`; entry notional plus entry fee equals capital before within float tolerance. Each side's fee uses its effective quote notional. CLOSED gross PnL uses recorded prices with this quantity, price-adjusted PnL uses effective prices, net PnL subtracts both fees, net return divides by capital before, and `net_capital_after = capital_before + net_pnl` compounds into the next trade.
- OPEN trades have capital before, effective entry price, quantity, entry notional, and entry fee. Exit and round-trip fields, including `total_fees`, remain missing, with no realized net result or mark-to-market valuation. Raw ledger entry/exit prices are unchanged.
- Added 21 transaction-cost tests covering zero-cost equivalence, adverse slippage, both fees, self-financing sizing, profitable/losing trades, net compounding, OPEN handling, separate fee/slippage cases, rate/capital/ledger validation, input preservation, empty schema, and arithmetic identities. All 149 tests passed, including all 128 earlier-stage tests.
- Full 8,760-row BTC integration retained 77 CLOSED and one OPEN trade. Zero-cost results matched Stage 4.6 economically; an independent decimal first-trade calculation, self-financing identities, net compounding, and input preservation passed. Scenario rates are test assumptions: 0.10% fee and 0.05% adverse slippage per side, not current Bybit fees.
- First trade recorded/effective entry: 115,332.3 / 115,389.96615 USDT; recorded/effective exit: 112,482.0 / 112,425.759 USDT; quantity: 0.0865760717619 BTC. Entry/exit/total fees: 9.990009990 / 9.733380579 / 19.723390569 USDT. Gross / price-adjusted / net PnL: -246.767777343 / -256.629410936 / -276.352801505 USDT; net return: -0.0276352801505; net capital after: 9,723.647198495 USDT.
- Final CLOSED-trade gross capital: 9,641.111388344 USDT; net capital: 7,652.530163437 USDT; reduction: 1,988.581224907 USDT, including fees, slippage, and compounded sizing effects. The final OPEN trade has capital before 7,652.530163437 USDT, quantity 0.0895852306473 BTC, and entry fee 7.644885278 USDT; it was not valued. These realized-capital figures are before its entry. No raw data, notebooks, architecture, dependencies, or existing source/test files changed.

- Stage 4.8 added `notebooks/03_backtest_review.ipynb`: local validated BTC OHLCV → `run_ema_execution_pipeline` → `build_trade_ledger` → independent `calculate_trade_results` and `calculate_trade_results_with_costs` calls. No strategy, execution, ledger, sizing, PnL, fee, or slippage logic is duplicated; descriptive summaries remain notebook research.
- All 38 notebook cells (18 code, 20 Markdown) were reviewed; all 18 code cells executed successfully in order in the existing virtual environment. Two Matplotlib plots show realized capital after CLOSED trades, including the initial point, and cumulative fees/modeled slippage on the cost-sized trade path. No candle-level equity curve is created.
- Snapshot checks retained 8,760 hourly candles from 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC, zero missing OHLCV values/duplicate timestamps, 78 LONG_ENTRY/77 LONG_EXIT signals, final desired/executed states 1/1, and 77 CLOSED/one OPEN trade. Fixed references validate results rather than supply calculation outputs; mismatches stop execution.
- From 10,000 USDT, gross realized capital is 9,641.111388344 USDT (change -358.888611656 USDT, return -3.588886%). With research assumptions of 0.10% fee and 0.05% adverse slippage per side, net realized capital is 7,652.530163437 USDT (change -2,347.469836563 USDT, return -23.474698%). The 1,988.581224907 USDT gap includes costs and their compounded sizing impact, not just summed fees; rates are not current Bybit fees.
- CLOSED-trade entry/exit/total fees sum to 577.318661158 / 576.124634617 / 1,153.443295774 USDT; average total fee is 14.979783062 USDT. Modeled slippage impact uses existing Stage 4.7 `gross_pnl - price_adjusted_pnl`: total 576.721493561 USDT, average 7.489889527 USDT. The final OPEN entry fee is excluded from these round-trip summaries.
- First-trade walkthrough uses recorded/effective prices and existing accounting columns. Final OPEN trade entered at 2026-09-30 13:00 UTC; its net-scenario quantity is 0.0895852306473 BTC and entry fee 7.644885278 USDT. Exit and realized fields remain missing, with no mark-to-market valuation. The final realized-capital comparison is before this entry / after the last CLOSED trade.
- All 149 existing unit tests passed. Notebook reference, zero-cost equivalence, and input/raw preservation checks passed; both plots were visually inspected. Existing reusable modules/tests, notebooks 01/02, raw CSV, dependencies, and architecture decisions remain unchanged. No new production financial logic, optimization, validation experiments, or Stage 5 analytics were introduced. Results describe this sample under stated assumptions, not general strategy quality; no out-of-sample or walk-forward validation exists yet.

- Stage 5.1 recorded the CLOSED-trade metric contract in `decisions/003_closed_trade_performance_metrics.md`. It defines counts/rates, mean/median/winning/losing/best/worst returns, total realized PnL, quote-currency expectancy, and profit factor without implementing analytics functions.
- Canonical GROSS source is Stage 4.6 `trade_return` / `gross_pnl`, with `capital_before` / `capital_after` context. Canonical NET source is Stage 4.7 `net_trade_return` / `net_pnl`, with `capital_before` / `net_capital_after` context. Stage 4.7 `gross_pnl` is not the canonical gross strategy simulation because it uses cost-aware quantity.
- Return-based classification uses fixed dimensionless `BREAKEVEN_TOLERANCE = 1e-12`: WIN above +tolerance, LOSS below -tolerance, BREAKEVEN inside or on the boundaries. OPEN rows are excluded from every CLOSED statistic and never valued. Total PnL/expectancy retain source breakeven residuals; profit factor uses PnL only from return-classified WIN/LOSS subsets.
- Recorded empty/subset cases, NaN/infinity profit-factor behavior, the 16-field future summary, and Stage 5.2 acceptance invariants. All 149 existing tests passed. No production code, new tests, notebooks, raw data, or dependencies were changed during Stage 5.1; implementation was pending at that milestone.

- Stage 5.2 added `src/trading_lab/analytics/trade_metrics.py`, implementing decision 003 through two pure public functions: `summarize_gross_trade_performance(results: pd.DataFrame) -> pd.DataFrame` and `summarize_net_trade_performance(results: pd.DataFrame) -> pd.DataFrame`. A small private helper shares calculations; no classes/framework or accounting recalculation was added.
- Each function returns one row indexed `GROSS` or `NET`, with exactly the 16 metric columns shown below in contract order. Counts are integers; other fields are float64. GROSS requires `status`, `trade_return`, `gross_pnl`, `capital_before`, `capital_after`; NET requires `status`, `net_trade_return`, `net_pnl`, `capital_before`, `net_capital_after`. Wrong Stage 4 accounting output fails clearly; capital columns guard source schema without repeating accounting validation.
- Only CLOSED rows enter metrics. Fixed `BREAKEVEN_TOLERANCE = 1e-12` uses unrounded returns: WIN above +tolerance, LOSS below -tolerance, BREAKEVEN inside/on the boundaries. Source values are preserved. Profit factor uses selected-source PnL with WIN/LOSS return masks; breakeven residual PnL remains in totals/expectancy but not those aggregates. Profit-only gives +infinity, loss-only 0.0, and no eligible PnL NaN.
- Empty/OPEN-only summaries have zero counts and total realized PnL, with NaN rates/statistics/expectancy/profit factor. Validation rejects non-DataFrames, duplicate/missing columns, invalid status, and missing/non-finite/non-real CLOSED financial values, including bools and strings. Inputs are never sorted, repaired, coerced from strings, or modified; optional columns are irrelevant.
- Added 35 synthetic metric tests covering all decision 003 conventions, boundary/residual behavior, degenerate populations, source separation, validation, preservation, and real Stage 4 helper integration without the raw CSV. All 184 tests passed, including all 149 earlier tests. No Stage 5.3 metrics were added.
- Local BTC research check ran the unchanged pipeline, ledger, gross accounting, and cost accounting before both summaries. Both retain 77 CLOSED trades; omitting the final OPEN row produces identical summaries. Independent standard-library arithmetic, count/rate/expectancy identities, total-PnL versus realized-capital changes, and input preservation passed. Stage 4 code/tests, all notebooks, raw CSV, decision 003, and dependencies remained unchanged during Stage 5.2.

- Stage 5.3 integrated `summarize_gross_trade_performance(gross_results)` and `summarize_net_trade_performance(net_results)` into the existing `notebooks/03_backtest_review.ipynb`, after the gross/net realized-capital comparison and plot, before transaction-cost analysis. Existing accounting outputs are reused; the pipeline still runs once.
- Added one readable Metric/Gross/Net table containing all 16 Stage 5.2 metrics. Counts display as integers, rates/returns as percentages, PnL/expectancy as USDT, and profit factor as a ratio; formatting leaves source values unchanged. Beginner explanations connect classification, win rate, average wins/losses, historical expectancy, profit factor, and arithmetic return versus compounding to this BTC sample.
- At Stage 5.3, notebook 03 had 44 cells: 21 code and 23 Markdown. All code cells executed top to bottom with sequential counts 1–21 and no error outputs. Both existing plots, transaction-cost analysis, first-trade walkthrough, and final OPEN inspection remained; no new plot or metric formula was added.
- All 16 BTC metric references passed for each path. Both have 77 CLOSED trades, 20 WIN, 57 LOSS, zero BREAKEVEN, and 25.974026% win rate. Gross/net total PnL is -358.888611656 / -2,347.469836563 USDT, expectancy -4.660891060 / -30.486621254 USDT per CLOSED trade, and profit factor 0.945165760246 / 0.675088667158. Classification remained unchanged only for this sample; costs can change classification in other samples.
- Removing the final OPEN row leaves every metric identical; its entry fee, quantity, and capital do not enter CLOSED statistics, and it remains unvalued. Accounting inputs and the raw-file hash are preserved. All 184 existing unit tests passed; no new unit tests were needed. Production modules, including `trade_metrics.py`, all tests, decision 003, notebooks 01/02, raw CSV, and dependencies remained unchanged during Stage 5.3; Stage 5.4 had not started at that milestone.

- Stage 5.4 recorded `decisions/004_realized_capital_drawdown.md`, defining REALIZED-CAPITAL drawdown only. Each independent path begins with explicit initial capital and then observes canonical capital after each CLOSED trade in existing accounting order: Stage 4.6 `capital_after` for GROSS, Stage 4.7 `net_capital_after` for NET. There are `N + 1` observations for `N` CLOSED trades; capital is never reconstructed from PnL.
- Running peak is the maximum capital observed so far. Decimal drawdown is `capital / running_peak - 1`, currency amount is `capital - running_peak`, and maximum realized drawdown is the minimum/most negative drawdown. The negative convention gives `-0.25` for a 25% decline. Empty/OPEN-only, flat, or increasing paths have maximum `0.0`; zero post-CLOSED capital gives `-1.0`, while negative capital is invalid.
- OPEN rows add no point; their capital before, entry fees/notionals, and quantities do not adjust realized observations. The final OPEN trade remains unvalued. This path omits intratrade/unrealized losses and can understate full mark-to-market portfolio drawdown; it must not be presented as the strategy's full drawdown.
- Stage 5.4 defined source-specific schema/finite real-capital validation, explicit gross/net API direction, a six-column observation path, and a small maximum summary. All 184 existing tests passed during that documentation-only milestone; implementation and BTC measurement were then pending Stage 5.5 approval.
- Stage 5.5 implemented decision 004 unchanged in `src/trading_lab/analytics/drawdown.py`, with four pure public functions: `calculate_gross_realized_drawdown`, `calculate_net_realized_drawdown`, `summarize_gross_realized_drawdown`, and `summarize_net_realized_drawdown`. Summaries reuse their source-specific path; accounting is never reconstructed.
- Added 32 synthetic tests in `tests/test_realized_drawdown.py` for schemas/dtypes, initial capital, source separation, peaks, empty/OPEN-only paths, zero capital, input validation/preservation/order, earliest tied minima, percentage-versus-currency minima, and integration with actual Stage 4 helpers. All 216 tests passed: 184 existing plus 32 new.
- The offline BTC research check verified 77 CLOSED trades and 78 observations per path, known final realized capitals, independent scalar drawdown calculations, and identical paths/summaries after removing the final OPEN row. Results are recorded below; OPEN remains unvalued.
- During Stage 5.5, Stage 4 production code/tests, `trade_metrics.py` / `test_trade_metrics.py`, all decisions, notebooks 01/02/03, raw BTC CSV, and dependencies remained unchanged. The existing 16-metric summary gained no drawdown column; notebook integration was then pending approval.

- Stage 5.6 integrated all four existing Stage 5.5 drawdown helpers into `notebooks/03_backtest_review.ipynb`, reusing `gross_results`, `net_results`, and `INITIAL_CAPITAL`. The new REALIZED-CAPITAL DRAWDOWN section follows the CLOSED-trade performance summary and precedes transaction-cost analysis. No accounting or drawdown formulas are duplicated; the pipeline still runs once.
- Added a separate Gross/Net table with maximum realized-capital drawdown, its associated USDT amount, trough observation/CLOSED-trade number, trough capital/peak, final realized capital, and population counts. Percentages, USDT formatting, and integer ordinals affect display only; the 16-metric table remains unchanged.
- Added one Matplotlib realized-capital drawdown plot using helper-provided `closed_trade_number` and `drawdown`, including observation 0 and trough markers derived from path/summary outputs. The existing realized-capital and accumulated-cost plots are retained. Notebook 03 now has 52 cells: 25 code, 27 Markdown, and three plots. All 25 code cells executed successfully with sequential counts 1–25 and no saved errors; all three plots were visually inspected.
- Notebook regression assertions passed for 77 CLOSED trades / 78 observations per path, explicit initial capital, maximum drawdowns, trough observations 33 GROSS / 66 NET, trough capital/peaks, and final CLOSED capital. Removing the final OPEN row leaves both paths and summaries identical. Accounting inputs and the raw-file hash were preserved.
- Beginner explanations and conclusions describe GROSS -26.723425% / NET -37.185533% realized-capital drawdown and the limitation versus mark-to-market portfolio drawdown. OPEN remains excluded and unvalued; intratrade/unrealized losses are not observed.
- All 216 existing unit tests passed during Stage 5.6; no new unit tests or dependencies were needed. Production modules including `drawdown.py` and `trade_metrics.py`, all tests, decisions, notebooks 01/02, and raw BTC CSV remained byte-identical. No new financial metric formulas were introduced; Stage 5.7 was then pending approval.

- Stage 5.7 recorded `decisions/005_trade_duration_and_exposure.md`, defining ledger-based CLOSED duration and simple binary observed time-in-market exposure. Canonical times are actual recorded `entry_time` / `exit_time` fills from `build_trade_ledger(...)`, independent of signal/position-state columns and accounting.
- CLOSED positions occupy half-open `[entry_time, exit_time)` intervals with strictly positive elapsed duration. The final OPEN trade has no completed duration and stays out of CLOSED duration statistics, but its observed `[entry_time, observation_end)` interval must contribute to exposure. No exit or valuation is invented.
- Defined the explicit market window `[observation_start, observation_end)`: first candle OPEN through the end of the final candle (last OPEN plus interval). The full denominator includes warm-up and flat time. Exposure is total non-overlapping observed position time divided by that window, a decimal fraction in `[0, 1]`.
- Chose two future APIs, a six-column per-trade table, and a separate 11-field summary indexed `TIME`. There is no GROSS/NET split because current cost models do not change ledger fill timestamps. Timestamp/window/order/overlap validation, empty/OPEN-only/full-exposure cases, and UTC recommendations are documented below and in decision 005.
- All 216 existing tests passed in Stage 5.7. That documentation-only milestone preserved production code, tests, all notebooks, raw BTC CSV, dependencies, and decisions 001–004. Duration/exposure implementation and BTC measurement were then pending Stage 5.8 approval.

- Stage 5.8 implemented decision 005 unchanged in `src/trading_lab/analytics/trade_time.py` with `calculate_trade_time_breakdown(...)` and `summarize_trade_time_metrics(...)`. Both consume the canonical ledger directly and share validated interval calculations; no accounting is called and no GROSS/NET time split is introduced.
- Added 41 synthetic tests in `tests/test_trade_time.py`, covering exact schemas/dtypes, elapsed/fractional durations, empty/OPEN-only/full exposure, boundaries, order/overlap, missing exits, timestamp/timezone validation, DST, optional fields, duplicate indexes, input preservation, and an actual Stage 4 ledger. All 257 tests passed: 216 existing plus 41 new.
- The offline BTC check has 77 CLOSED trades and one final OPEN trade over 8,760 hours. CLOSED time totals 4,078 hours; the final OPEN contributes 11 observed hours, giving 4,089 hours in market and exposure `0.46678082191780823`. Full results appear below.
- During Stage 5.8, Stage 4 modules/tests, existing trade metrics/drawdown modules/tests, decisions 001–005, notebooks 01/02/03, raw BTC CSV, and dependencies remained byte-identical. Notebook integration was then pending Stage 5.9 approval.

- Stage 5.9 integrated `calculate_trade_time_breakdown(...)` and `summarize_trade_time_metrics(...)` from unchanged `analytics/trade_time.py` into notebook 03 after realized-capital drawdown and before cost analysis. Both consume its existing canonical `trades` ledger directly; the explicit window derives from first candle timestamp through last timestamp plus one hour, including all 8,760 observed hours. No GROSS/NET time split or new financial metric is introduced.
- Added the separate 11-field TIME table, integer count/hour/percentage display formatting, a first/last-three-trade preview, and a derived top-five CLOSED-duration table. BTC references remain 77 CLOSED / one OPEN; average/median/minimum/maximum CLOSED durations are 52.96103896103896 / 34 / 1 / 226 hours, totaling 4,078 CLOSED hours. The first CLOSED duration is 27 hours; the longest is trade 68 at 226 hours.
- Final OPEN trade 78 entered at `2026-09-30 13:00 UTC` and contributes 11 observed hours, giving 4,089 hours in market and exposure `0.46678082191780823` (46.678082%). Its completed duration remains NaN and its exit missing; it remains unvalued. Explanations and conclusions distinguish CLOSED duration statistics from observed exposure and holding-time behavior from profitability.
- Notebook assertions check schemas/dtypes, all time references, first/longest CLOSED trades, final OPEN behavior, and deep-copy ledger/output preservation. The existing raw-file hash check is retained. All time values come from public helpers; no duration/exposure formulas or private-helper calls were added.
- Executed all 28 code cells sequentially with no saved errors: 58 total cells, 30 Markdown, and the same three plots. Saved-output checks confirm 12 existing table-producing cells and all three plot images unchanged. All 257 tests pass; no new unit tests or dependencies. Production analytics including `trade_time.py`, `trade_metrics.py`, and `drawdown.py`, all tests/Stage 4 code, decisions 001–005, notebooks 01/02, and raw BTC CSV remain byte-identical. Stage 5.10 was then pending approval.

- Stage 5.10 recorded `decisions/006_candle_level_mark_to_market_equity.md`: initial capital plus a raw CLOSE valuation after every candle, including the final OPEN position. An explicit fixed interval defines the window; N candles produce N + 1 observations.
- Defined initial-before-fill state, EXIT then ENTRY at each OPEN before that candle's CLOSE mark, independent canonical Stage 4.6 GROSS / Stage 4.7 NET paths, paid-cost semantics without hypothetical liquidation costs, exact future schema/APIs, validation, worked example, and boundary cases. Realized-capital reconciliation applies while flat; shared-OPEN replacement entries are marked as new positions.
- All 257 existing tests passed. This documentation-only milestone preserved production code/tests, all notebooks, raw BTC CSV, dependencies, and decisions 001–005. Equity implementation and BTC mark-to-market measurement were then pending Stage 5.11 approval; portfolio drawdown and notebook integration remained deferred.

- Stage 5.11 implemented decision 006 unchanged in `src/trading_lab/analytics/equity.py` with independent GROSS/NET pure functions, initial-before-fill state, EXIT then ENTRY at OPEN, raw CLOSE marking, and N + 1 observations. Canonical quantities/actual exit capital are reused; incurred costs are not charged twice and no hypothetical liquidation costs are added.
- Added 47 synthetic tests in `tests/test_mark_to_market_equity.py`; all 304 tests pass (257 existing + 47 new). Coverage includes exact schema/dtypes, initial losses, worked example, OPEN/final fills, shared-OPEN replacement, no lookahead, source guards, validation/timezones/DST, arithmetic reconciliation, and input preservation.
- The unchanged BTC loader → EMA pipeline → ledger → independent accounting → equity check produced 8,761 rows per path from 8,760 candles, with 77 CLOSED / one final OPEN. Final marked equity is GROSS 9,451.485313939314 USDT / NET 7,490.776562851941 USDT; all 77 CLOSED exit observations reconcile per path. Stage 4, existing analytics/tests, decisions 001–006, all notebooks, raw data, and dependencies remained unchanged. Notebook integration was then pending Stage 5.12 approval; no portfolio drawdown was implemented or calculated.

- Stage 5.12 integrated the two unchanged Stage 5.11 equity helpers into notebook 03 after realized-capital drawdown and before TIME. They consume its existing candles/GROSS/NET accounting with initial capital 10,000 USDT and an explicit one-hour interval; no equity formulas are duplicated.
- Added compact initial/first-entry/final path previews, a last-realized-versus-final-marked table, one GROSS/NET time-axis MTM plot, final OPEN state display, and regression/input/path-preservation checks. Both paths have 8,761 observations from 8,760 candles. At final CLOSE 83,616.2 USDT, trade 78 remains OPEN, position 1, cash zero: GROSS marked equity 9,451.485313939314 / NET 7,490.776562851941 USDT, versus CLOSED realized capital 9,641.111388344 / 7,652.530163437 USDT.
- Executed all 33 code cells in order with no saved errors: 68 cells total, 35 Markdown, four plots. All three original plot images and their generating code remain byte-identical; exactly one MTM plot was added. Representative exit checks passed for trades 1, 39, and 77 in both paths. All 304 tests pass; production code/tests, decisions 001–006, notebooks 01/02, raw data, and dependencies remain unchanged. No portfolio drawdown was calculated; Stage 5.13 contract was then pending approval.

- Stage 5.13 accepted decision 007 for candle-close portfolio drawdown from the existing independent Stage 5.11 equity paths, with exact path/summary schemas, negative drawdown conventions, and deterministic earliest-trough/latest-peak selection.
- Preserved the supplied initial reference, allowed later zero equity, and included final OPEN marked equity through the source path. Realized-capital drawdown stays separate and unchanged; candle-CLOSE observations still miss intrabar/tick losses.
- All 304 existing tests passed. This documentation-only milestone preserved production code/tests, all notebooks, raw data, dependencies, and decisions 001–006. No portfolio drawdown implementation or BTC measurement was performed; Stage 5.14 was then pending approval.

- Stage 5.14 implemented decision 007's four pure functions in `src/trading_lab/analytics/portfolio_drawdown.py`, consuming existing equity paths with shared validation, causal peaks, exact episode selection, and unchanged input/schema semantics.
- Added 55 focused synthetic tests, including actual Stage 5.11 equity integration and final OPEN inclusion. All 359 tests pass (304 existing + 55 new); existing production modules/tests, decisions 001–007, notebooks, raw data, and dependencies remain unchanged.
- The unchanged BTC pipeline produced 8,761 equity/drawdown observations per path. Maximum candle-close portfolio drawdown is GROSS -27.6794381422% / NET -37.9679609807%; both are deeper than this sample's separate realized-capital drawdowns. Notebook integration was then pending Stage 5.15 approval.

- Stage 5.15 integrated the four unchanged Stage 5.14 portfolio-drawdown helpers into notebook 03 immediately after MTM equity and before TIME. They consume the existing GROSS/NET equity paths directly; no equity or drawdown formulas are duplicated.
- Added a compact ten-result GROSS/NET table, realized-versus-portfolio comparison, initial/peak/trough/final path previews, exactly one time-axis drawdown plot with helper-selected trough markers, final OPEN explanation, and focused regression/preservation assertions. Both paths retain 8,761 rows; maximum drawdowns remain GROSS -27.6794381422% / NET -37.9679609807%, with final drawdowns -7.6771641106% / -25.2825731282%.
- Executed every code cell sequentially without saved errors: 80 cells total, 39 code, 41 Markdown, five plots. All four original plot cells and saved images remain byte-identical. All 359 tests pass; production code/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are unchanged. Equity inputs and drawdown outputs are preserved. No benchmark, time-based returns, Sharpe/Sortino, duration/recovery, or later stage was implemented.

- Stage 5.16 accepted decision 008 and added two reusable first-OPEN Buy-and-Hold APIs in `analytics/benchmark.py`. One synthetic OPEN trade delegates independent GROSS/NET sizing to Stage 4 accounting and CLOSE marking to Stage 5.11; no financial formulas, strategy signals, or exits are duplicated.
- Added 38 focused tests (36 synthetic/delegation/validation checks and two local BTC/alignment checks). All 397 tests pass, including the unchanged 359 earlier tests. Both BTC benchmark paths have 8,761 observations; actual values and EMA comparisons are documented below.
- Notebook 03 now calls the benchmark and existing portfolio-drawdown helpers, displays four-path and relative comparisons, explains absolute versus relative losses, and adds exactly one time-aligned equity plot. All 43 code cells executed sequentially without errors: 88 cells total, 45 Markdown, six plots. All five prior plot sources/images are byte-identical. Existing production modules/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are unchanged; no Sharpe/Sortino or Stage 6 work was added.

- Stage 5.17 accepted decision 009 and added `analytics/risk_adjusted.py` with one canonical simple-return helper and a summary that reuses it. Each of the four aligned equity paths produces 8,760 actual hourly returns from 8,761 observations, retaining flat cash periods and final OPEN marks.
- Sharpe uses sample excess standard deviation (ddof=1); Sortino uses all-period downside RMS with zero from non-downside hours. Explicit hourly annualization is 8,760 periods/year, with zero per-period risk-free return and zero MAR. 61 Stage 5.17 tests pass; all 458 tests pass (397 earlier + 61 Stage 5.17).
- Notebook 03 now presents eight-result/four-path summaries, compact return previews, interpretation, references/preservation checks, and exactly one NET hourly-return diagnostic. All 47 code cells executed sequentially without saved errors: 96 cells total, 49 Markdown, seven plots. All six previous plot sources/images remain byte-identical. Existing production modules/tests, decisions 001–008, notebooks 01/02, raw data, and dependencies are unchanged. No Stage 5.18 or Stage 6 work was started.

- Stage 5.18 consolidated notebook 03 into the final Stage 5 report: research setup, four-portfolio headline comparison, EMA trade behavior, integrated interpretation, limitations, and one final regression/preservation audit. Tables and explanations reuse existing helper outputs; no financial formulas or production APIs changed.
- All 51 code cells executed sequentially without saved errors: 104 total cells, 53 Markdown, seven plots. All seven existing plot sources/images remain byte-identical; no plot was added. All 458 existing tests pass; no new tests, production modules, decisions, dependencies, or project files were added. Stage 5 is complete; Stage 6 has not started.

- Stage 6.1 accepted [decision 010](decisions/010_generic_strategy_backtest_contract.md), defining canonical strategy fields, strict candle/index alignment, desired-state transitions, next-OPEN timing, optional diagnostics, causality responsibilities, and the frozen EMA regression gate.
- This contract-only milestone changes no production code, tests, notebooks, dependencies, data, or decisions 001–009. The existing 458-test baseline is preserved. Stage 6.2 awaits owner approval; Stage 7 has not started.

- Stage 6.2 added `backtest/strategy_validation.py` with `validate_strategy_output(candles, strategy_output)`, implementing decision 010's canonical fields, strict alignment, fixed one-hour availability, and desired-state machine. It returns an independent full strategy-output copy with diagnostics unchanged; no execution is called.
- Added 48 synthetic unittest methods, including EMA compatibility, DST, typed empty frames, duplicate index labels, strict scalar types, and input/output preservation. All 506 tests pass (458 unchanged baseline + 48 new). Pipeline, execution, EMA, existing tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic are unchanged. Stage 6.3 awaits owner approval; Stage 7 has not started.

- Stage 6.3 added `run_execution_pipeline(candles, strategy_output)` to `backtest/pipeline.py`. It delegates canonical validation, transfers only the validated signal into a local candle copy, and delegates next-OPEN execution. The separate six-column execution output retains authoritative candle OPEN values, dtypes, and index; strategy diagnostics cannot override market prices.
- Added 25 synthetic unittest methods covering timing, final no-fill cases, exact direct-helper parity, colliding diagnostic names, validation delegation, input preservation, causal prefixes, and defensive output checks. All 531 tests pass (506 unchanged baseline + 25 new). The existing EMA pipeline and alignment helper retain their original source; execution, validator, EMA strategy, existing tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic are unchanged. Stage 6.4 awaits approval; Stage 7 has not started.

- Stage 6.4 added `run_backtest_pipeline(...)` in `backtest/pipeline.py`, composing generic execution → ledger → independent GROSS/NET accounting. It returns exactly `execution`, `trades`, `gross_results`, and `net_results`; helper outputs and financial formulas are unchanged.
- Added 15 synthetic unittest methods; the full suite passed once with 546 tests (531 unchanged baseline + 15 new). Non-EMA intent reaches accounting; exact direct-composition parity, OPEN/final no-fill behavior, compounding, costs, diagnostics, errors, preservation, and index/timezone conventions pass. Existing pipeline functions, lower layers, EMA, analytics, old tests, decisions, notebooks, dependencies, data, and Stage 5 logic are preserved. Stage 6.5 awaits approval; Stage 7 has not started.

- Stage 6.5 added `tests/test_ema_generic_regression.py`, proving exact EMA20/50 compatibility between the existing EMA pipeline and generic strategy/execution/ledger/accounting paths on the frozen local BTC snapshot. The existing raw SHA-256 and Stage 5 financial/analytics references pass without changing production logic or tolerances.
- All 16 new regression methods execute with zero failures, errors, or skips; the full suite passed once with 562 tests (546 unchanged baseline + 16 new). All production modules, old tests, decisions, notebooks, dependencies, and raw data remain unchanged. No EMA wrapper migration or notebook execution occurred. Stage 6.6 awaits approval; Stage 7 has not started.

- Stage 6.6 added and executed `notebooks/04_generic_backtest_engine.ipynb`: 23 cells (11 code / 12 Markdown), sequential counts 1–11, zero saved errors, and one embedded GROSS/NET candle-close equity plot. It demonstrates existing EMA intent through the generic engine, separate accounting outputs, downstream equity helpers, and a tiny synthetic non-EMA contract example.
- Frozen BTC sanity references and input/raw-file preservation checks pass. All 562 existing tests passed once; no unit tests or production Python changes were added. Old tests, decisions, notebooks 01–03, `.py` placeholders, dependencies, and raw data are unchanged. Stage 6.7 awaits approval; Stage 7 has not started.

- Stage 6.7 completed the final contract/API, commit-chain, file-scope, frozen Stage 5, and saved notebook audit. Stage 6 — Generic Backtesting Engine is COMPLETE.
- All 104 Stage 6 methods and the full 562-test suite pass with zero failures, errors, or skips. This closure changes documentation only; Stage 7 awaits explicit owner approval.

- Stage 7.1 accepted Decision 011: a fixed current-capital allocation fraction in `(0, 1]`, default 1.0, with risk returning a budget and accounting calculating quantity. Reserve cash, OPEN/final-signal semantics, exact Stage 6 compatibility, and the 7.1–7.9 roadmap are documented.
- Documentation/architecture only: no sizing implementation, production/test/notebook/old-decision/dependency/data changes. The existing test inventory remains 562; Stage 7.2 awaits explicit owner approval and has not started.

- Stage 7.2 added the pure scalar `risk/position_sizing.py` helper, `calculate_position_budget(capital_before, position_fraction=1.0) -> float`. It returns current capital times a valid fixed fraction, with positive finite float validation and no accounting/pipeline/equity integration.
- Added 35 synthetic scalar unittest methods. All 35 targeted tests and the full 597-test suite (562 existing + 35 new) pass with zero failures, errors, or skips. Existing production modules/tests, risk package exports, decisions, notebooks, dependencies, and data are unchanged. Stage 7.3 awaits explicit owner approval and has not started.

- Stage 7.3 integrated the fixed budget helper into direct GROSS accounting via the trailing `position_fraction=1.0` parameter. Partial quantities/PnL compound total capital; raw position-return semantics and the exact output schema are unchanged, with reserve derived rather than stored.
- Added 25 synthetic integration methods. New tests (25), unchanged GROSS tests (27), and sizing-core tests (35) pass; the full suite passed once with 622 tests (597 existing + 25 new), zero failures, errors, or skips. The frozen Stage 6 default EMA regression remains green; NET/equity/pipeline sizing integration remains pending and Stage 7.4 has not started.
- Stage 7.4 integrated fixed-fraction budgets into direct NET accounting through the trailing `position_fraction=1.0` parameter. The budget includes entry fees; reserve is derived rather than stored, and total NET capital compounds independently. Existing return meanings, costs, schema, and OPEN semantics are preserved.
- Added 33 synthetic NET integration methods. New tests (33), unchanged transaction-cost tests (21), GROSS sizing tests (25), and sizing-core tests (35) pass; the full suite passed once with 655 tests (622 existing + 33 new), zero failures, errors, or skips. Frozen Stage 6 default EMA regression remains unchanged. Stage 7.5 awaits explicit owner approval and has not started.
- Stage 7.5 made GROSS/NET candle-CLOSE equity reserve-aware using canonical entry spend. Cash remains reserve while LONG; actual exit capital, raw marks, unrealized PnL, public APIs, schemas, dtypes, and timing are preserved. NET entry fees are paid once; full-allocation reserve remains exact zero.
- Added 31 synthetic partial-equity methods. New tests (31), unchanged equity tests (47), GROSS sizing tests (25), and NET sizing tests (33) pass; the full suite passed once with 686 tests (655 existing + 31 new), zero failures, errors, or skips. Frozen Stage 6 MTM references remain unchanged. Stage 7.6 awaits explicit owner approval and has not started.
- Stage 7.6 added trailing `position_fraction=1.0` to the generic backtest pipeline, forwarding it unchanged to both independent accounting paths. Execution, ledger behavior, four return keys, and exact default compatibility are preserved; equity remains downstream.
- Added 24 synthetic pipeline integration methods. New tests (24), retained generic pipeline methods (15), GROSS sizing tests (25), NET sizing tests (33), and partial-equity tests (31) pass; the full suite passed once with 710 tests (686 existing + 24 new), zero failures, errors, or skips. Frozen Stage 6 references and tolerances are unchanged. Stage 7.7 awaits explicit owner approval and has not started.
- Stage 7.7 verified the complete frozen Stage 5/6 path at fraction 1.0 and downstream analytics compatibility at 0.50/0.25. Canonical BTC partial snapshots are now literal regression constants; execution, ledger, duration/exposure, and benchmark paths remain fraction-independent. No production code, analytics API/formula, existing test, decision, notebook, dependency, or data changes were required.
- Added 37 real-BTC regression methods. New regression (37), frozen EMA regression (16), trade metrics (35), realized drawdown (32), trade time (41), equity (47), portfolio drawdown (55), benchmark (38), risk-adjusted (61), generic sizing pipeline (24), and partial equity (31) targeted tests pass. The full suite passed once with 747 tests (710 existing + 37 new), zero failures, errors, or skips. All frozen Stage 5/6 references/tolerances are unchanged. Stage 7.8 awaits explicit owner approval and has not started.

- Stage 7.8 added executed educational notebook `notebooks/05_risk_position_sizing.ipynb`, comparing fixed fractions 1.0/0.50/0.25 through the existing generic pipeline, reserve-aware GROSS/NET equity, drawdown, and Sharpe/Sortino helpers. All 32 cells (15 code / 17 Markdown) are saved with sequential counts 1–15, zero errors, and two embedded plots.
- The unchanged 37-method position-sizing regression, 16-method frozen EMA regression, and full 747-test suite pass with zero failures, errors, or skips. Frozen references, source/test/decision/dependency/data files, notebooks 01–04, and all existing `.py` placeholders are preserved. Stage 7.9 awaits explicit owner approval and has not started.

- Stage 7.9 completed the final contract/API, milestone-chain, file-scope, frozen regression, and committed-notebook audit. Stage 7 — Risk Manager + Position Sizing is COMPLETE. All 185 Stage 7 test methods, the 16-method frozen EMA regression, and the full suite (run once: 747 tests) pass with zero failures, errors, or skips. Documentation only; Stage 8 — Strategy Robustness is next and has not started.

- Stage 8.1 accepted [Decision 012 — Strategy Robustness Contract](decisions/012_strategy_robustness.md) and the 8.1–8.8 roadmap. Documentation/architecture only; no production, test, notebook, dependency, or data changes. The full existing suite passed once: 747 tests, zero failures, errors, or skips. Stage 8.2 awaits explicit owner approval and has not started.

- Stage 8.2 added the focused `trading_lab.robustness` package: chronological splitting, generic cold-start segment evaluation, and independent IS/OOS orchestration using existing pipeline/equity APIs. The 56 new methods and all 803 suite tests pass with zero failures, errors, or skips; frozen Stage 5–7 references/tolerances, existing modules/tests, decisions, notebooks, dependencies, and data are unchanged. Stage 8.3 awaits explicit owner approval and has not started.

- Stage 8.3 added a generic deterministic parameter-grid evaluator through the unchanged Stage 8.2 core and existing analytics. The 36 new methods and full 839-test suite pass with zero failures, errors, or skips, including the canonical 25-combination BTC research grid and direct EMA20/50 parity. No ranking, selection, optimization, or default parameter changes. Stage 8.4 awaits explicit owner approval and has not started.

- Stage 8.4 added downstream-only two-dimensional parameter stability diagnostics on the existing sensitivity table, using supplied-order radius-one Moore adjacency and finite local statistics. The 39 new methods and full 878-test suite pass with zero failures, errors, or skips, including canonical BTC geometry for three OOS NET metrics. No backtest reruns, ranking, classification, threshold, or score. Stage 8.5 awaits explicit owner approval and has not started.

- Stage 8.5 added deterministic expanding row-count windows and independent fixed-configuration train/test evaluation through the unchanged Stage 8.2 core. The 42 new methods and full 920-test suite pass with zero failures, errors, or skips, including three canonical BTC windows. No state/capital/trade carry, cross-boundary fills, parameter selection, summary metrics, or stitched equity. Stage 8.6 awaits explicit owner approval and has not started.

- Stage 8.6 added downstream-only IS/OOS and walk-forward diagnostic tables over precomputed canonical results, reusing existing analytics. The 62 new methods and full 982-test suite pass with zero failures, errors, or skips. Neutral comparisons and finite-only test-window statistics preserve undefined raw metrics without reruns, window compounding, stitched equity, scores, classification, or parameter recommendations. Stage 8.7 awaits explicit owner approval and has not started.

- Stage 8.7 added and executed `notebooks/06_strategy_robustness.ipynb` using accepted production APIs and only the hash-verified local BTC snapshot. All 34 cells (17 code / 17 Markdown) executed sequentially with zero errors and six visually inspected embedded figures. Canonical split/grid/neighborhood/walk-forward and input/raw-hash checks pass; all 982 tests remain green. No production/test/decision/earlier-notebook/dependency/data/result changes, optimization, score, or stitched equity. Stage 8.8 awaits explicit approval; Stage 8 remains INCOMPLETE.

- Stage 8.8 completed the Decision 012 contract/API, seven-commit milestone chain, file-scope, frozen Stage 5–7 regression, canonical BTC, and saved-notebook audits. Stage 8 — Strategy Robustness is COMPLETE. Its 235 new tests plus the unchanged 747-test baseline give 982 passing tests, zero failures/errors/skips. Documentation only; source, tests, decisions, notebooks, dependencies, data/results, and reference values/tolerances are preserved. Stage 9 — Bybit Demo Exchange Adapter awaits explicit owner approval and has not started.

## Strategy robustness contract

[Decision 012](decisions/012_strategy_robustness.md) is Accepted. Stage 8 evaluates stability across chronological periods and nearby strategy parameters; it does not optimize profit, choose one best EMA pair, or deploy parameters automatically. Splits use predefined chronological half-open windows, never random splitting or shuffled candles, with no look-ahead. EMA20/50 with 50 warm-up candles remains the existing research baseline, not an optimal or validated strategy.

Every independent IS/OOS/walk-forward segment cold-starts FLAT with its own initial capital and fresh strategy, execution, accounting, and ledger state. Initialization/warm-up occurs inside the segment and remains in its observation window. No pre-window indicators, portfolio state, or trades carry in; no synthetic boundary entry or terminal liquidation is added. Existing strategy generation, generic backtest, independent GROSS/NET accounting, reserve-aware equity, and analytics are reused without duplicate formulas or changed responsibilities.

Sensitivity uses a predefined valid finite grid with consistent window/cost/sizing assumptions; isolated peaks are robustness warnings. Normally hold the accepted fixed `position_fraction` constant while varying time or strategy parameters. Fixed-parameter walk-forward supports the initial research; adaptive selection is not required, and no magic robustness score is introduced. Independent windows do not imply continuous compounded equity. Existing undefined metrics remain honest. The BTC snapshot is already-seen research data; chronological OOS checks within it are methodological evidence, not pristine unseen validation.

Stage 8.1 was documentation/architecture only; Stage 8.2 implements the split/evaluation core, Stage 8.3 adds descriptive parameter sensitivity, Stage 8.4 analyzes local surface variation, Stage 8.5 adds independent expanding walk-forward evaluation, and Stage 8.6 summarizes precomputed IS/OOS and walk-forward results below. Stage 8.7 presents these outputs in executed notebook 06. Stage 7 remains COMPLETE and Stage 5 analytics remains frozen. Current suite: 982 tests, zero failures, errors, or skips; `git diff --check` passes. Decision 012 remains unchanged; Stage 8.8 final audit and Stage 8 are COMPLETE.

## Accepted Stage 8 roadmap

| Milestone | Status |
| --- | --- |
| 8.1 — Robustness Contract | Complete; Decision 012 Accepted, documentation/architecture only. |
| 8.2 — Time Split / OOS Evaluation Core | Complete; chronological split and independent cold-start evaluation. |
| 8.3 — Parameter Sensitivity Engine | Complete; deterministic descriptive grid through the existing IS/OOS core. |
| 8.4 — Parameter Stability Analysis | Complete; downstream-only two-dimensional local variation diagnostics. |
| 8.5 — Walk-Forward Evaluation | Complete; fixed-configuration expanding windows with independent cold starts. |
| 8.6 — Robustness Summary / Diagnostics | Complete; downstream neutral comparisons and finite-only independent-window statistics. |
| 8.7 — Strategy Robustness Notebook | Complete; executed local-only research with six embedded figure groups. |
| 8.8 — Final Stage 8 Audit + Docs | Complete; contract/API, history/scope, frozen regression, data, and saved-notebook audits passed. |

## Chronological split / OOS evaluation core

Stage 8.2 introduced three helpers from `trading_lab.robustness`, implemented in `src/trading_lab/robustness/evaluation.py`:

```python
chronological_split(
    candles: pd.DataFrame, train_fraction: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame]

evaluate_strategy_segment(
    candles: pd.DataFrame, strategy_generator, *, candle_interval,
    strategy_kwargs=None, initial_capital: float = 10_000.0,
    fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0,
) -> dict

evaluate_train_test_split(
    candles: pd.DataFrame, strategy_generator, *, candle_interval,
    train_fraction: float = 0.70, strategy_kwargs=None,
    initial_capital: float = 10_000.0, fee_rate: float = 0.0,
    slippage_rate: float = 0.0, position_fraction=1.0,
) -> dict
```

The default is a chronological 70/30 row-count split, with IS size `int(len(candles) * validated_fraction)`. It validates strictly increasing datetime timestamps and a finite real fraction in `(0, 1)` producing two non-empty sides. There is no overlap, gap, sorting, shuffling, or index reset; copies retain all columns, dtypes, timezone, values, and original labels. The frozen local 8,760-row BTC snapshot splits into **6,132 IS / 2,628 OOS** rows; the first OOS timestamp is **2026-06-13 12:00 UTC**. This is a research default, not a universal financial standard.

The generic strategy callable receives only an independent copy of its supplied segment and unchanged keyword settings. EMA initializes from that segment's first CLOSE and performs its own 50-candle warm-up inside the observation window. The evaluator delegates to the existing generic pipeline and reserve-aware GROSS/NET equity; financial validation, formulas, and schemas remain authoritative downstream. It returns exactly `strategy_output`, `execution`, `trades`, `gross_results`, `net_results`, `gross_equity`, `net_equity`, in that order, without summary analytics or added financial-frame metadata.

Train/OOS orchestration returns exactly `split_index`, `split_timestamp`, `in_sample`, `out_of_sample`, in that order. Both evaluations receive the same strategy, interval, kwargs, initial capital, fees, slippage, and fraction. Each starts independently from the configured initial capital; no desired/executed state, signal, OPEN trade, ledger, or capital carries across. A final IS signal cannot use the first OOS OPEN. Segment-end OPEN positions remain unliquidated with missing realized exits and existing final-CLOSE equity marks.

All 56 new `tests/test_robustness_oos.py` methods pass: 18 split, 23 segment, 11 train/OOS, and four local BTC integration cases. They cover exact composition/schema parity, arguments/validation/error propagation, copy preservation, boundary fills, independent state/capital, and exact seven-frame invariance when only the other segment's prices change. The BTC integration verifies cold-start EMA and deterministic local-only composition without downloading data or claiming profitability/robustness. Compatibility gates pass: generic sizing pipeline 24, partial equity 31, frozen EMA regression 16. The full suite passed once: **803 tests (747 existing + 56 new), zero failures, errors, or skips**. Existing files/data and all frozen references/tolerances are preserved; no notebooks were executed.

Stage 8.2 remains complete and frozen. Stage 8.3 composes it for the descriptive grid, Stage 8.4 analyzes that table downstream, Stage 8.5 composes independent expanding train/test windows, and Stage 8.6 summarizes precomputed segment/window results. No new benchmark orchestration or robustness score is implemented.

## Parameter sensitivity engine

Stage 8.3 — Parameter Sensitivity Engine is **COMPLETE**. `src/trading_lab/robustness/sensitivity.py` exposes this generic API by explicit import from `trading_lab.robustness`; the existing three-name wildcard `__all__` contract stays unchanged for Stage 8.2 compatibility:

```python
evaluate_parameter_sensitivity(
    candles: pd.DataFrame,
    strategy_generator,
    parameter_grid,
    *,
    candle_interval,
    train_fraction: float = 0.70,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict
```

The caller supplies a non-empty Mapping of non-empty ordered sequences (such as list, tuple, or range). Mapping key order and candidate order define a deterministic sequential Cartesian product, with one row per combination. Strings/bytes, unordered containers, scalars, invalid keys, empty grids/candidates, overlapping common/grid keys, and names colliding with fixed metric columns are rejected. Strategy parameter semantics remain with the supplied generator. Errors propagate without skipped rows or partial results. Candles, grid/candidate values, and common kwargs are preserved; mutable keyword values are copied per combination.

Each combination calls the unchanged `evaluate_train_test_split(...)` with the same candles, chronological split (default 70/30), interval, initial capital, costs, and fixed allocation. Stage 8.2 supplies independent cold-start IS/OOS behavior. Split metadata must reconcile exactly across combinations. The return keys are exactly `split_index`, `split_timestamp`, `parameter_names`, `results`, in that order; `parameter_names` is the supplied key-order tuple. The table uses a fresh RangeIndex, parameter columns first, then these 11 metrics with `is_` prefixes followed by the same 11 with `oos_` prefixes:

```text
trade_count, closed_trade_count, exposure_ratio,
gross_final_equity, net_final_equity,
gross_max_portfolio_drawdown, net_max_portfolio_drawdown,
gross_sharpe, gross_sortino, net_sharpe, net_sortino
```

Counts are int64; other fixed metrics are float64; parameter columns retain pandas' inferred scalar dtypes. Counts come from canonical trades. Existing trade-time analytics uses the equity path's complete first-to-last valuation window. Final equity includes canonical OPEN-position CLOSE marks; existing portfolio drawdown and risk-adjusted helpers consume the same paths with explicit annualization/risk-free/MAR settings. Undefined NaN and signed infinities remain unchanged. No financial formula, terminal liquidation, ranking, best pair, selection, or optimization is added; EMA defaults stay 20/50 with 50 warm-up candles.

The predefined canonical research grid is fast spans **[10, 15, 20, 25, 30]** × slow spans **[40, 50, 60, 70, 80]** = **25 combinations**, with common warm-up 50 and EMA20/50 included. It is explicitly caller-supplied, never an implicit production default or recommendation. The frozen local BTC snapshot has 8,760 rows; every combination uses **6,132 IS / 2,628 OOS**, first OOS **2026-06-13 12:00 UTC**. Assumptions: initial capital 10,000, fee 0.001, slippage 0.0005, fraction 1.0, periods/year 8760, per-period risk-free/MAR zero. Costs are research assumptions, not current exchange settings. The EMA20/50 row exactly matches direct Stage 8.2 evaluation plus the same analytics.

All **36 new methods** (32 synthetic/contract and four focused local BTC integration cases) pass. Compatibility gates: Stage 8.2 **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. Full suite passed once: **839 tests (803 existing + 36 new), zero failures, errors, or skips**; `git diff --check` passes. Evaluation/backtest/analytics/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 8.3 remains complete and frozen; Stage 8.4 consumes its output below.

## Parameter stability analysis

Stage 8.4 — Parameter Stability Analysis is **COMPLETE**. The downstream-only `src/trading_lab/robustness/stability.py` API is explicitly importable from `trading_lab.robustness`:

```python
analyze_parameter_stability(sensitivity_result, metric: str) -> dict
```

It consumes an existing Stage 8.3 result with the four canonical fields, without calling sensitivity, IS/OOS evaluation, a strategy, or a backtest. This milestone requires exactly two distinct non-empty parameter names in a tuple and a non-empty DataFrame with unique columns and RangeIndex 0..N-1. Both parameter columns and one non-parameter real numeric metric must exist. Boolean/complex metrics, missing/unhashable parameter labels, and parameter names colliding with diagnostic columns are rejected. Each parameter pair must occur exactly once in a complete rectangular Cartesian grid; no missing/duplicate cells are repaired.

Parameter levels are recovered in first-occurrence order, never sorted numerically or converted to strings. Adjacency means one step in each supplied axis, including diagonals: a radius-one Moore neighborhood, excluding the center and without wraparound or numeric-distance weighting. Ordinary two-dimensional corners, non-corner edges, and interiors have **3 / 5 / 8** neighbors; smaller axes retain only the cells that exist. Every source row is retained in its original order.

Return keys are exactly `parameter_names`, `metric`, `parameter_levels`, `surface`, `local_stability`, in that order. `parameter_levels` maps the two names to ordered tuples. The fresh unpivoted `surface` has exactly the two parameter columns followed by the original metric. The fresh `local_stability` has the two parameter columns followed by:

```text
metric_value, neighbor_count, finite_neighbor_count,
neighbor_mean, neighbor_std, neighbor_min, neighbor_max,
mean_absolute_delta, max_absolute_delta,
local_min, local_max, local_range
```

`neighbor_count` includes every geometric neighbor; `finite_neighbor_count` uses `np.isfinite`. Counts are int64, all metric/diagnostic values float64, and parameter columns retain their source dtypes. Neighbor statistics exclude the center and non-finite neighbors; standard deviation uses **ddof=1**, remaining NaN with fewer than two finite neighbors. Mean/min/max are NaN with zero finite neighbors. Absolute deltas use finite neighbors only when the center is finite; otherwise, or with no finite neighbors, they are NaN. Local min/max/range uses the finite center plus finite neighbors, or finite neighbors alone when the center is non-finite; an empty finite region yields NaN. All quantities stay in the metric's own units.

Original NaN, +infinity, and -infinity remain in the surface and `metric_value`; no grid cell is dropped or filled. Inputs are preserved and repeated analysis is exact and deterministic. These diagnostics describe local similarity/variation without deciding performance direction, classifying robust/fragile regions, applying universal thresholds, ranking/selecting parameters, or creating a stability/robustness score. EMA defaults remain unchanged. Broad plateaus versus isolated variation can be interpreted later; no winner or parameter recommendation is recorded.

The hash-checked local BTC integration generates the accepted Stage 8.3 **25-cell** research grid through its production API, with the unchanged fast/slow levels, warm-up 50, default 70/30 split, capital/cost/allocation/annualization assumptions above. It analyzes **OOS NET final equity, Sharpe, and maximum portfolio drawdown**. All three retain every cell; **10/40 has three neighbors, 10/50 five, and EMA20/50 eight**. EMA20/50's exact neighbors are 15/40, 15/50, 15/60, 20/40, 20/60, 25/40, 25/50, and 25/60. Across the 5×5 geometry: four corners with 3, twelve edges with 5, nine interiors with 8. No performance preference is asserted.

All **39 new methods** (35 synthetic/contract, four focused BTC integration cases) pass. Unchanged compatibility gates: sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. Full suite passed once: **878 tests (839 existing + 39 new), zero failures, errors, or skips**; `git diff --check` passes. Existing evaluation/sensitivity/backtest/analytics/strategy modules, tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are preserved. The three-name wildcard export contract stays unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.4 remains complete and frozen; Stage 8.5 composes independent segment evaluations below.

## Expanding walk-forward evaluation

Stage 8.5 — Walk-Forward Evaluation is **COMPLETE**. `src/trading_lab/robustness/walk_forward.py` exposes two APIs by explicit import from `trading_lab.robustness`; the existing three-name wildcard `__all__` contract remains unchanged:

```python
generate_expanding_walk_forward_windows(
    candles: pd.DataFrame,
    initial_train_rows,
    test_rows,
) -> pd.DataFrame

evaluate_expanding_walk_forward(
    candles: pd.DataFrame,
    strategy_generator,
    *,
    candle_interval,
    initial_train_rows,
    test_rows,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> dict
```

The initial mode is expanding training history only: training always starts at positional row zero and grows by `test_rows`. Tests have fixed length, are chronological, non-overlapping and gap-free, and begin exactly at the train slice's exclusive end. Only full test windows are evaluated; a partial final test is excluded and reported as `unused_tail_rows`. Row counts are explicit positive Python/NumPy integral scalars; bools, floats, non-scalars, and insufficient data are rejected. Candles require unique columns and a datetime timestamp column with no missing, duplicate, or non-increasing values. Source order, index labels, dtypes, values, and timezone are preserved without sorting or repair.

The fresh RangeIndex definition table has exactly these columns, in order: `window_id`, `train_start_index`, `train_end_index`, `test_start_index`, `test_end_index`, `train_rows`, `test_rows`, `train_start_timestamp`, `train_last_timestamp`, `test_start_timestamp`, `test_last_timestamp`. Index fields use half-open Python slice semantics; timestamp fields record actual first/last observations without invented calendar boundaries.

The evaluator returns exactly `window_definitions`, `unused_tail_rows`, `windows`, in that order. `windows` is a tuple; each mapping contains exactly `window_id`, `train`, `test`. Each train/test result is the unchanged seven-frame `evaluate_strategy_segment(...)` output. Every segment independently cold-starts FLAT with the same initial capital, fixed generator/configuration, interval, costs, and position fraction. Fresh candle slices and deep-copied strategy kwargs isolate mutable settings between runs and preserve caller inputs. Warm-up occurs inside every segment. No strategy/execution/ledger state, trades, or capital carry across runs; no cross-boundary fill or terminal liquidation is added. Errors propagate without skipping windows or returning partial results. No sensitivity/stability engine is called, no training-based parameter selection occurs, and no summary metrics or stitched equity are produced.

Canonical local BTC research uses **8,760 rows**, `initial_train_rows=4380`, `test_rows=1460`: **three complete windows**, train sizes **4,380 / 5,840 / 7,300**, test size **1,460 each**, and **zero unused tail rows**. Every train begins at **2025-10-01 00:00 UTC**. These are row counts, not exact calendar months.

| Window | Train slice | Test slice | Train last (UTC) | Test start (UTC) | Test last (UTC) |
| --- | --- | --- | --- | --- | --- |
| 1 | `[0, 4380)` | `[4380, 5840)` | 2026-04-01 11:00 | 2026-04-01 12:00 | 2026-06-01 07:00 |
| 2 | `[0, 5840)` | `[5840, 7300)` | 2026-06-01 07:00 | 2026-06-01 08:00 | 2026-08-01 03:00 |
| 3 | `[0, 7300)` | `[7300, 8760)` | 2026-08-01 03:00 | 2026-08-01 04:00 | 2026-09-30 23:00 |

All six evaluations use predefined **EMA20/50**, **50 warm-up candles inside every segment**, initial capital **10,000**, fee **0.001**, adverse slippage **0.0005**, position fraction **1.0**, and the existing one-hour candle interval. Costs are research assumptions. Integration reads only the hash-checked frozen local snapshot, with no download or parameter comparison; it verifies window metadata, fresh EMA initialization/warm-up, unchanged settings, and input/raw preservation without freezing profitability conclusions.

All **42 new methods** pass: **14** window-definition, **24** evaluation, and **4** BTC integration cases. Exact seven-frame direct-composition parity, future-data independence, boundary signals, fresh capital/state, kwargs isolation, tail exclusion, and determinism are covered. Unchanged compatibility gates pass: stability **39**, sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. The full suite passed once: **920 tests (878 existing + 42 new), zero failures, errors, or skips**; `git diff --check` passes. Existing evaluation/sensitivity/stability, backtest/analytics/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.5 remains complete and frozen; Stage 8.6 summarizes its precomputed independent outputs below.

## Robustness summary / diagnostics

Stage 8.6 — Robustness Summary / Diagnostics is **COMPLETE**. `src/trading_lab/robustness/diagnostics.py` exposes exactly two new public APIs by explicit import from `trading_lab.robustness`; all existing explicit imports and the historical three-name wildcard `__all__` contract are preserved:

```python
summarize_train_test_diagnostics(
    train_test_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict

summarize_walk_forward_diagnostics(
    walk_forward_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict
```

Both consume precomputed Stage 8.2/8.5 mappings only. They accept no candles, strategy generator/settings, costs, or sizing parameters and rerun no strategy, backtest, sensitivity grid, stability calculation, or walk-forward evaluation. Structural validation checks canonical fields/types and reconciles window IDs with definition rows in supplied order; existing analytics validate financial frames and propagate their errors without partial summaries. Inputs remain unchanged and every summary table has a fresh RangeIndex.

The exact 14 segment metrics, in order, are `trade_count`, `closed_trade_count`, `exposure_ratio`, `initial_equity`, `gross_final_equity`, `net_final_equity`, `gross_total_return`, `net_total_return`, `gross_max_portfolio_drawdown`, `net_max_portfolio_drawdown`, `gross_sharpe`, `gross_sortino`, `net_sharpe`, `net_sortino`. Counts are int64; the other metrics are float64. OPEN trades remain in total count and final marked equity, without forced closure. Each segment's GROSS and NET initial equity must match exactly or raise ValueError. Total return is the unannualized endpoint diagnostic `final_equity / initial_equity - 1`, not a sum of trades/periods/windows.

Exposure calls `summarize_trade_time_metrics(...)` over the first/last GROSS valuation times. GROSS/NET drawdown calls their existing public portfolio-drawdown summaries. Sharpe/Sortino calls `summarize_risk_adjusted_performance(...)` separately on each independent equity path, forwarding annualization, risk-free return, and MAR unchanged. No financial formula is duplicated.

The single-split return keys are exactly `split_index`, `split_timestamp`, `segment_metrics`, `comparison`. `segment_metrics` has two rows, **IN_SAMPLE** then **OUT_OF_SAMPLE**, with `segment` followed by the 14 metrics. `comparison` has 13 rows in that same metric order excluding contextual `initial_equity`; columns are `metric`, `in_sample_value`, `out_of_sample_value`, `oos_minus_is`. Differences are neutral OOS minus IS values, without interpreting metric desirability.

The walk-forward return keys are exactly `unused_tail_rows`, `window_metrics`, `window_comparison`, `test_metric_summary`. Each wide window row has authoritative definition metadata `window_id`, `train_rows`, `test_rows`, `train_start_timestamp`, `train_last_timestamp`, `test_start_timestamp`, `test_last_timestamp`, followed by all 14 `train_` metrics and then all 14 `test_` metrics. Metadata/counts are int64, other metrics float64, and timestamp dtypes/timezones are preserved. `window_comparison` has 13 rows per window in definition order; columns are `window_id`, `metric`, `train_value`, `test_value`, `test_minus_train`.

`test_metric_summary` describes distributions across independent test windows, with 13 comparable metric rows and columns `metric`, `finite_count`, `mean`, `median`, `minimum`, `maximum`. `finite_count` is int64; descriptive fields are float64. Only finite values enter these four statistics. Zero finite values gives four NaNs; one finite value gives that value in all four fields. Raw window metrics/comparisons retain NaN and signed infinities with normal IEEE subtraction. Independent +10% test windows describe a +10% mean/median, never a +21% compounded portfolio. There is no capital continuity, stitched equity, robustness score, pass/fail classification, parameter ranking, or recommendation. Stage 8.3 sensitivity and Stage 8.4 local stability tables remain separate, ready for later visualization.

The hash-checked local BTC integration uses unchanged EMA20/50, warm-up 50, capital 10,000, fee 0.001, slippage 0.0005, fraction 1.0, one-hour candles, 8,760 periods/year, and zero per-period risk-free return/MAR. These remain research assumptions. Single split: **6,132 IS / 2,628 OOS**, boundary **2026-06-13 12:00 UTC**, diagnostic table **2 × 15**, comparison **13 × 4**. Walk-forward: **4,380 initial train / 1,460-row tests**, **three windows**, **zero tail**, window metrics **3 × 35**, comparisons **39 × 5**, test statistics **13 × 6**. Every train/test initial equity remains **10,000**. All segment metrics match direct public analytics; counts, exposure, equity, drawdown, and endpoint returns satisfy canonical sanity checks. No download or strategy-quality verdict occurs.

All **62 new methods** pass: **24** train/test, **29** walk-forward, **5** architecture/delegation, and **4** BTC integration cases. Coverage includes exact schemas/dtypes/parity, neutral comparisons, raw non-finite preservation, finite-only statistics, non-compounding, input preservation, determinism, structural errors, and the hard no-rerun gate. Unchanged compatibility suites pass: walk-forward **42**, stability **39**, sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. The full suite passed once: **982 tests (920 existing + 62 new), zero failures, errors, or skips**; `git diff --check` passes. Existing robustness evaluation/sensitivity/stability/walk-forward, analytics/backtest/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.7 — Strategy Robustness Notebook is complete as recorded below.

## Strategy robustness notebook

Stage 8.7 — Strategy Robustness Notebook is **COMPLETE**. `notebooks/06_strategy_robustness.ipynb` calls the accepted Stage 8.2–8.6 public APIs, computing each canonical research object once and reusing it for tables and figures. Notebook helpers only format supplied values, pivot parameter tables, and plot; no production financial formulas, neighborhood algorithms, ranking, parameter selection, optimizer, robustness score, or stitched capital are added.

The notebook executed top-to-bottom from a clean kernel in the existing `.venv`: **34 cells (17 code / 17 Markdown)**, all **17** code cells executed with sequential counts **1–17**, valid notebook JSON, **zero saved errors**, and **six embedded Matplotlib figures**. All figures were visually inspected, including readable heatmap annotations/colorbars and visible baseline outlines. The groups are the 2×2 IS/OOS panel; three sensitivity heatmaps; two Sharpe local-variation maps; walk-forward train/test return bars; independent test NET equity indexed to each own start at 100; and three test-diagnostic panels. No external result files are created in the repository.

Data is only the local **8,760-row** `data/raw/BTCUSDT_1h.csv`, period `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. SHA256 **`0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`** is verified before loading and after analysis; loaded candles and raw data are unchanged. Missing/different data stops execution without a replacement download. No network/API calls or package installations occurred.

Canonical settings remain EMA20/50, warm-up 50 inside every segment, capital 10,000, fee 0.001, adverse slippage 0.0005, fixed fraction 1.0, one-hour candles, 8,760 periods/year, and zero per-period risk-free return/MAR. Fees/slippage are frozen research assumptions. The single cold-start split verifies **6,132 IS / 2,628 OOS**, first OOS **2026-06-13 12:00 UTC**. The predefined fast `[10, 15, 20, 25, 30]` × slow `[40, 50, 60, 70, 80]` grid has **25** rows in supplied order; EMA20/50 appears once and has **eight** stability neighbors. Three stability objects cover OOS NET equity, Sharpe, and portfolio drawdown. Walk-forward verifies **three** independent tests, train sizes **4,380 / 5,840 / 7,300**, test sizes **1,460** each, and **zero** unused tail rows; no capital continues between windows.

Markdown distinguishes robustness from profitability and explains chronological testing, local similarity versus isolated variation, and limits of already-seen single-asset/hourly/EMA research. It makes no strategy-quality verdict or live/demo/production claim. All six targeted modules pass: diagnostics **62**, walk-forward **42**, stability **39**, sensitivity **36**, OOS **56**, frozen EMA regression **16**. The full suite passed once: **982 tests, zero failures, errors, or skips**; `git diff --check` passes. No tests were added. Source, tests, decisions, notebooks 01–05, `.py` placeholders, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.8 — Final Stage 8 Audit + Docs is complete as recorded below.

## Final Stage 8 audit

Stage 8.8 — Final Stage 8 Audit + Docs is **COMPLETE**. Stage 8 — Strategy Robustness is **COMPLETE** under Accepted, unchanged [Decision 012](decisions/012_strategy_robustness.md). All milestones 8.1–8.8 are accepted: contract; chronological split / OOS core; deterministic parameter sensitivity; descriptive local stability; fixed-configuration expanding walk-forward; downstream summary / diagnostics; research notebook; and final audit.

The audit confirms chronological-only splitting without sorting, shuffling, random splitting, overlap, or gaps. Every independent segment generates strategy output from its own candles, cold-starts FLAT with its own configured capital and internal warm-up, and reuses the existing generic backtest, accounting, reserve-aware equity, and analytics. No pre-window indicators, state, capital, trades, cross-boundary fills, or terminal liquidation are introduced. Sensitivity preserves caller-supplied Cartesian order; two-dimensional radius-one Moore stability clips at edges (3/5/8 neighbors) and preserves raw NaN/infinities. Walk-forward holds parameters fixed across expanding trains and independent full tests, with explicit unused tails. Diagnostics consume precomputed results only, retain neutral comparisons and finite-only descriptive statistics, and never compound independent windows. No optimizer, ranking, winner selection, automatic deployment, classification threshold, robustness score, stitched equity, or second financial engine exists.

All **nine** accepted public APIs are explicitly importable from `trading_lab.robustness`. The historical wildcard contract remains exactly `chronological_split`, `evaluate_strategy_segment`, and `evaluate_train_test_split`. The seven implementation commits from `6928991` through `09112fc` added only six robustness modules, five test modules, Decision 012, and notebook 06, plus documentation. Every pre-Stage-8 non-documentation file stayed unchanged in every commit; no later-stage exchange/runtime/database/dashboard/deployment implementation or dependencies were added.

Canonical research remains the frozen **Bybit spot BTCUSDT 1-hour** snapshot: **8,760 rows**, `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`, SHA256 **`0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`** unchanged. EMA20/50 and 50-candle warm-up remain the baseline/defaults, not an optimal configuration. Initial capital 10,000, fee 0.001, adverse slippage 0.0005, fraction 1.0, 8,760 periods/year, and zero per-period risk-free return/MAR stay fixed; costs are research assumptions, not current exchange pricing. The 70/30 split is **6,132 / 2,628**, first OOS **2026-06-13 12:00 UTC**. The ordered 25-cell grid includes EMA20/50 once, with eight neighbors. Three walk-forward tests have **1,460 rows each**, train sizes **4,380 / 5,840 / 7,300**, starts **2026-04-01 12:00**, **2026-06-01 08:00**, and **2026-08-01 04:00 UTC**, and **zero** unused tail. Diagnostics retain shapes **2 × 15**, **13 × 4**, **3 × 35**, **39 × 5**, and **13 × 6**.

Committed notebook 06 validates as JSON with **34 cells (17 code / 17 Markdown)**, saved sequential execution **1–17**, **zero errors**, and **six embedded figures** covering all required groups. Its source/output/claims audit confirms public API reuse, presentation-only helpers, independent own-start equity indexing, no obvious secrets/credentials, no network/download output, and no external result-file dependency. Notebook 06 was **not edited or re-executed** during this audit; its milestone-time status note remains preserved.

Each required targeted suite ran once, as did the full suite:

| Test group | Passing methods |
| --- | ---: |
| Stage 8.2 OOS core | 56 |
| Stage 8.3 sensitivity | 36 |
| Stage 8.4 stability | 39 |
| Stage 8.5 walk-forward | 42 |
| Stage 8.6 diagnostics | 62 |
| Stage 8 additions total | 235 |
| Stage 7 analytics regression | 37 |
| Frozen EMA regression | 16 |
| Full suite: 747 + 235 | 982 |

All gates passed with **zero failures, errors, or skips**; `git diff --check` passes. Stages 8.1, 8.7, and 8.8 add no tests. Stage 7 references and Decisions 010/011/012 are unchanged. Frozen EMA remains **78 ENTRY / 77 EXIT**, **77 CLOSED / one OPEN**, last CLOSED GROSS/NET capital **9,641.111388344 / 7,652.530163437**, and final GROSS/NET MTM equity **9,451.485313939314 / 7,490.776562851941**, with original tolerances. All source, tests, decisions, `.ipynb` files, placeholders, dependencies, data/results, and frozen references are preserved during 8.8; only the four allowed documentation files change, with no new repository files.

Completion means the research tools satisfy the accepted contract, not that the strategy has a proven edge. The BTC sample is already seen; evidence covers one asset, one hourly timeframe, one primary strategy family, and three canonical OOS windows. Cold-start research differs from continuous live state, and transaction costs are frozen assumptions. Historical robustness does not prove future profitability; there is no demo/live trading evidence yet. Stage 7 remains COMPLETE. **Stage 9 — Bybit Demo Exchange Adapter** is next, awaiting explicit owner approval and **NOT STARTED**.

## Risk and position-sizing contract

[Decision 011](decisions/011_risk_and_position_sizing.md) is Accepted. Stage 7's implemented policy is a scalar fixed `position_fraction` in `0 < position_fraction <= 1`, default `1.0`, constant for one backtest run. Reject zero, negatives, values above 1, Python/NumPy bools, non-finite values, strings, None, complex values, and non-scalars without coercion or clamping. No leverage, borrowing, or zero-allocation trade veto is introduced.

Strategy continues to decide Decision-010 intent. Risk determines the allowed budget from CURRENT portfolio capital at each actual executed entry: `position_budget = capital_before * position_fraction`; reserve is `capital_before - position_budget`. Accounting converts that budget into quantity using raw price for GROSS and the existing effective-price/entry-fee self-financing rules for NET. Risk does not calculate quantity, costs, or PnL. Execution timing, prices, signals, and ledger pairing remain unchanged.

Reserve belongs to the same portfolio. Stage 7.5 MTM equity now includes reserve cash plus marked position value: 10,000 capital, fraction 0.50, entry 100, and mark 110 gives quantity 50, reserve 5,000, and equity 10,500 without costs. Next-entry budgets compound from current capital, so 10,500 at fraction 0.50 permits 5,250. OPEN trades retain known entry/budget/reserve information with missing realized exit results; final unexecuted entries allocate nothing, and final unexecuted exits leave positions OPEN. Allocation fraction is distinct from time exposure and is not a fixed loss-at-risk percentage.

Default fraction 1.0 must reproduce Stage 6 exactly, including quantities, independent GROSS/NET accounting, equity, and downstream analytics, without loosening existing tolerances. Frozen BTC reference values are recorded in Decision 011. Prefer existing accounting schemas and derive reserve safely from canonical entry accounting; any necessary new field requires an explicit reviewed decision.

The unchanged Stage 7.2 helper `calculate_position_budget(capital_before, position_fraction=1.0) -> float` supplies budgets to both GROSS and NET accounting. NET budgets include the entry fee and both paths independently compound total portfolio capital. Stage 7.5 equity derives reserve from canonical entry spend without rerunning risk policy. Stage 7.6 `run_backtest_pipeline(...)` forwards the same fraction unchanged to both accounting paths, defaulting to full allocation. Stage 7.7 verifies downstream analytics compatibility at fractions 1.0/0.50/0.25; Stage 7.8 now presents these comparisons in executed notebook 05. Production code, tests, decisions 001–011, notebooks 01–04, dependencies, and data are preserved; the current full suite passes with 982 tests.

## Position sizing core

`src/trading_lab/risk/position_sizing.py` exposes `calculate_position_budget(capital_before, position_fraction=1.0) -> float`. The pure helper returns only `capital_before * position_fraction`, using the caller's current total portfolio capital: 10,000 at 0.50 gives 5,000, while 10,500 at 0.50 gives 5,250. It calculates no quantity, costs, reserve cash, PnL, or equity and imports only standard-library `math` and `numbers`.

Capital must be a positive finite real scalar; the fraction must satisfy `0 < position_fraction <= 1` and defaults to 1.0. Python/NumPy integer and floating scalars are accepted and the result is always a positive finite Python float. Python/NumPy bools, non-scalars, strings, None, complex values, and non-finite/nonpositive values raise ValueError. Fractions above 1 are rejected using the original numeric value, even if float conversion rounds them to 1.0. Unsafe conversion overflow/underflow and multiplication underflow to zero are rejected; there is no parsing, clamping, epsilon, minimum allocation, leverage, or veto.

All 35 methods in `tests/test_position_sizing.py` remain unchanged and pass. Stage 7.2's full suite passed once with 597 tests (562 unchanged baseline + 35 new), zero failures, errors, or skips. Tests cover current-capital examples, Python/NumPy scalar types, invalid inputs, exact boundaries, finite float limits, conversion/product underflow, output type, and repeatability. A valid finite float capital multiplied by a fraction at most 1 cannot overflow; conversion overflow is rejected and the final budget still has an explicit finite/positive check.

Stages 7.3 and 7.4 delegate GROSS and NET budgeting to this unchanged helper. Stage 7.5 adds reserve-aware equity downstream; Stage 7.6 forwards the fraction through the generic pipeline without importing risk or calculating budgets. The risk module/package, decisions 001–011, existing notebooks 01–04, requirements, and raw data are unchanged; no notebook was executed during Stage 7.2–7.7. Stage 6 remains COMPLETE. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## GROSS position-sizing integration

`calculate_trade_results(trades: pd.DataFrame, initial_capital: float = 10_000.0, position_fraction=1.0) -> pd.DataFrame` now accepts the allocation fraction as its final positional-or-keyword parameter. The default is 1.0. Each actual ledger entry delegates `calculate_position_budget(capital_before, position_fraction)` to the unchanged Stage 7.2 helper, then calculates `quantity = position_budget / entry_price`. Empty valid ledgers also validate the public fraction through that helper. Existing ledger/schema checks and financial safety checks are preserved; no sorting or repair is introduced.

`capital_before` remains TOTAL portfolio capital. CLOSED `gross_pnl = quantity * (exit_price - entry_price)` and `capital_after = capital_before + gross_pnl` compound that total into the next entry. `trade_return` stays the raw position return `exit_price / entry_price - 1`, independent of fraction. For 1,000 capital and fraction 0.50, a 100 → 110 trade has quantity 5, position return 10%, PnL 50, and total capital 1,050; a next entry at 50 has budget 525 and quantity 10.5.

The exact eleven-column schema is unchanged: six ledger fields plus `capital_before`, `quantity`, `trade_return`, `gross_pnl`, and `capital_after`. No budget/fraction/reserve columns are added. Reserve is derived as `capital_before - quantity * entry_price`; CLOSED capital reconciles to reserve plus `quantity * exit_price` within existing numerical tolerance. OPEN rows have partial-sized quantity and total capital before entry, with missing realized return/PnL/capital-after and exit fields. No mark-to-market or terminal close is introduced. Input values, dtypes, timezone, and index are preserved.

All 25 methods in `tests/test_gross_position_sizing.py`, all 27 unchanged GROSS methods, and all 35 unchanged budget-core methods pass. The full suite passed once with 622 tests (597 existing + 25 new), zero failures, errors, or skips. Default versus explicit 1.0 outputs match exactly; the existing Stage 6 EMA regression remains unchanged and green, with no reference/tolerance changes.

Stages 7.3 and 7.4 added GROSS/NET partial sizing; Stage 7.5 values those canonical results with reserve-aware MTM. Stage 7.6 forwards `position_fraction` through the generic pipeline with default 1.0. Accounting, risk, execution, ledger, decisions 001–011, existing notebooks 01–04, dependencies, and data remain unchanged. The Stage 7.7 partial-allocation analytics audit is complete; Stage 7.8 notebook now demonstrates the verified comparisons. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## NET position-sizing integration

`calculate_trade_results_with_costs(trades: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0) -> pd.DataFrame` adds the fraction as its final positional-or-keyword parameter, default 1.0. Each NET entry delegates its CURRENT independently compounded total `capital_before` to `calculate_position_budget(...)`; empty valid ledgers also validate the fraction through that helper. Fee/slippage validation, then the existing GROSS ledger/numerical validation, precede NET sizing. GROSS output amounts never supply NET budgets or compounding.

`quantity = position_budget / (effective_entry_price * (1 + fee_rate))` keeps entry self-financing: `entry_notional + entry_fee = position_budget`. Reserve stays outside the position and is derived as `capital_before - (entry_notional + entry_fee)`, never stored or charged the entry fee again. Effective-price slippage, notional fees, recorded-price `gross_pnl`, effective-price PnL, and `net_pnl` formulas remain unchanged. CLOSED total `net_capital_after = capital_before + net_pnl` reconciles to `reserve + exit_notional - exit_fee` within existing tolerance and funds the next NET entry.

`net_trade_return = net_pnl / capital_before` remains a portfolio-capital return, while GROSS `trade_return` remains raw position price return. With 1,000 capital, fraction 0.50, zero costs, and 100 → 110, quantity is 5, NET PnL is 50, NET return is 5%, GROSS position return is 10%, and total capital is 1,050. Zero-cost GROSS/NET quantities, PnL, and total capital reconcile at the same fraction; their partial return fields intentionally differ.

The exact twenty-column order is preserved: six ledger columns plus the fourteen existing NET financial fields, which remain float64. No fraction, budget, or reserve columns are added. OPEN rows populate only known entry-side accounting using current NET capital, with all exit/round-trip/realized fields missing. No valuation or forced close is introduced. Input values, column order, dtypes, timezone, index, and optional source fields are preserved.

All 33 methods in `tests/test_net_position_sizing.py`, 21 unchanged transaction-cost methods, 25 unchanged GROSS sizing methods, and 35 unchanged sizing-core methods pass. The full suite passed once with 655 tests (622 existing + 33 new), zero failures, errors, or skips. Default versus explicit 1.0 DataFrames match exactly. Frozen Stage 6 EMA regression remains unchanged and green: last CLOSED NET capital 7,652.530163437 USDT and final NET MTM 7,490.776562851941 USDT; no references or tolerances changed.

GROSS and NET partial accounting from the generic pipeline can feed reserve-aware MTM downstream. Accounting remains unchanged in Stage 7.6; each path uses its own current capital. Stage 7.7 verifies partial-allocation analytics compatibility; Stage 7.8 now demonstrates partial allocation in executed notebook 05. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reserve-aware candle-level MTM

Stage 7.5 keeps the public APIs unchanged: `calculate_gross_mark_to_market_equity(candles: pd.DataFrame, gross_results: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame` and `calculate_net_mark_to_market_equity(candles: pd.DataFrame, net_results: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame`. Equity receives no `position_fraction`, imports no risk helper, and never resizes canonical accounting quantity or rebalances.

GROSS reserve is `capital_before - quantity * entry_price`. NET reserve is `capital_before - (quantity * effective_entry_price + entry_fee)`, so the entry fee is already paid and never deducted again. Canonical entry spend must be finite, positive, and no greater than total capital beyond the existing reconciliation tolerance. Spend close to capital at `rel_tol=1e-12, abs_tol=0.0` produces exact `cash = 0.0`; material overspend raises ValueError without clamping or changing quantity. Each entry's total capital still reconciles with initial capital or the preceding canonical realized exit.

While LONG, cash stays constant at the derived reserve and `position_value = quantity * raw_close`; `equity = cash + position_value`. GROSS unrealized PnL remains `quantity * (raw_close - entry_price)`, giving `equity = capital_before + unrealized_pnl` within tolerance. NET retains its effective-entry basis, giving `equity = capital_before - entry_fee + unrealized_pnl`. A 1,000-capital half allocation at entry 100 has reserve 500 and quantity 5 without costs: CLOSE 110 gives equity 1,050 and CLOSE 90 gives 950. No hypothetical exit fees/slippage or final liquidation are introduced.

Actual EXIT sets cash to canonical `capital_after` / `net_capital_after` and clears the position. A replacement ENTRY at the same OPEN then installs its own reserve and quantity from current independently compounded accounting. The preceding CLOSE observation still occurs before those OPEN events. Initial/flat/no-trade states, the exact eleven-column schema, RangeIndex, int64/nullable-Int64/float64 dtypes, and timestamp/timezone behavior are unchanged. Both inputs are preserved on success and validation failure.

All 31 methods in `tests/test_partial_mark_to_market_equity.py`, 47 unchanged equity methods, 25 unchanged GROSS sizing methods, and 33 unchanged NET sizing methods pass. The full suite passed once with 686 tests (655 existing + 31 new), zero failures, errors, or skips. Explicit full allocation matches default paths exactly. Frozen Stage 6 EMA regression remains unchanged and green: final GROSS MTM 9,451.485313939314 USDT and final NET MTM 7,490.776562851941 USDT; no reference or tolerance changes.

Partial GROSS/NET accounting-to-equity composition is ready through the generic pipeline. Equity remains optional downstream, with unchanged APIs and no allocation parameter. The Stage 7.7 partial-allocation analytics audit is complete; Stage 7.8 notebook is complete and Stage 7 is COMPLETE after the final audit. Accounting, sizing, equity/other analytics, execution, ledger, strategies, decisions 001–011, existing notebooks 01–04, dependencies, and data are unchanged. No notebook was executed during Stage 7.5. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic position-sizing integration

Stage 7.6 adds final positional-or-keyword `position_fraction=1.0` to `run_backtest_pipeline(...)`. The pipeline always forwards the same value unchanged to GROSS and NET accounting, including the default and empty/all-HOLD cases. It owns call order only: no risk import, fraction validation, budgeting, sizing, reserve, equity, or financial formulas. Lower layers retain validation ownership.

Changing the fraction affects accounting quantities and realized results without affecting strategy intent, execution, or ledger pairing. GROSS and NET compound their own current total capital independently. Zero-cost amounts agree at the same fraction; GROSS raw position return and NET portfolio return keep their distinct meanings. The exact four return keys are `execution`, `trades`, `gross_results`, and `net_results`; helper schemas are unchanged and no equity output is added. Omitted versus explicit 1.0 outputs match exactly.

All 24 new synthetic methods in `tests/test_generic_position_sizing_pipeline.py`, all 15 retained generic pipeline methods, 25 GROSS sizing methods, 33 NET sizing methods, and 31 partial-equity methods pass. The full suite passed once with 710 tests (686 existing + 24 new), zero failures, errors, or skips. The frozen Stage 6 EMA regression passes without reference or tolerance changes. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE; the analytics regression and educational notebook are complete; the final Stage 7 audit passed.

## Position-sizing analytics regression

Stage 7.7 uses the unchanged hash-checked `data/raw/BTCUSDT_1h.csv`, 8,760 hourly candles over `[2025-10-01, 2026-10-01)`, EMA20/50 with 50 warm-up candles, and initial capital 10,000. NET fee 0.001 and adverse slippage 0.0005 are fixed research assumptions, not current exchange fees. No download or notebook execution occurred.

Omitted versus explicit fraction 1.0 pipeline/equity DataFrames match exactly and preserve the complete frozen Stage 5/6 regression, including all trade, realized-drawdown, time/exposure, portfolio-drawdown, benchmark, hourly-return, and Sharpe/Sortino references. Fractions 1.0/0.50/0.25 share identical strategy intent, execution, and ledger: 78 ENTRY / 77 EXIT fills, 77 CLOSED / one OPEN trade. GROSS raw trade returns and ledger duration/exposure are invariant; NET portfolio trade returns scale with the fraction and win/loss classification is unchanged in this snapshot. Aggregate PnL-based ratios are not assumed invariant.

Partial accounting feeds reserve-aware equity and all existing downstream analytics with unchanged schemas, signatures, and formulas. Each equity path has 8,761 aligned observations, retains reserve while LONG, and marks final OPEN trade 78 without liquidation. Realized and portfolio drawdown accept the canonical inputs; hourly returns retain all 8,760 periods, cash zeros, and final OPEN changes. Sharpe/Sortino use 8,760 periods/year and zero per-period risk-free return/MAR. Buy-and-Hold remains independently full-allocated and exactly unchanged. No analytics API receives `position_fraction` or imports the risk helper. Input/raw preservation and repeated pipeline/equity runs pass exact checks.

The reviewed one-off production-API capture established these full-precision literal references in `tests/test_position_sizing_analytics_regression.py`. Capital/equity uses USDT; drawdowns are negative decimal fractions and ratios are dimensionless. Tests retain the corresponding established capital, equity, drawdown, and risk-adjusted tolerances.

| Canonical BTC measurement | Fraction 0.50 | Fraction 0.25 |
| --- | ---: | ---: |
| Last CLOSED GROSS capital | 9918.391236748259 | 9985.739621448789 |
| Last CLOSED NET capital | 8837.511197655364 | 9426.098541539295 |
| Final GROSS MTM equity | 9820.851361993184 | 9936.638523863317 |
| Final NET MTM equity | 8744.110764994484 | 9376.288042723892 |
| Maximum realized GROSS drawdown | -0.14248540505494767 | -0.07357702428688317 |
| Maximum realized NET drawdown | -0.20423832781018214 | -0.1070450228128268 |
| Maximum portfolio GROSS drawdown | -0.14809055437971497 | -0.07660787284120885 |
| Maximum portfolio NET drawdown | -0.20920070404661006 | -0.10983103209615619 |
| GROSS Sharpe | -0.058161849146260235 | -0.054056339584623025 |
| GROSS Sortino | -0.08507501805626921 | -0.07914256241587235 |
| NET Sharpe | -0.8824772122392462 | -0.8712069545635516 |
| NET Sortino | -1.2814314707945054 | -1.2663722258083463 |

Smaller allocations leave ending capital/equity closer to 10,000 and produce shallower drawdowns in this frozen losing BTC sample. These tested orderings are dataset-specific, not a general claim about strategy quality. All 37 new methods and all 747 suite tests pass with zero failures, errors, or skips. No production analytics change was required; Stage 7 is COMPLETE. Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Position-sizing notebook

[Notebook 05](notebooks/05_risk_position_sizing.ipynb) is the Stage 7.8 educational comparison of fractions 1.0/0.50/0.25 using one shared EMA20/50 strategy output and the existing generic pipeline. It explains capital allocation versus signal timing/time exposure, current-capital budgets and compounding, independent GROSS/NET quantity, self-financing entry costs, and reserve-aware equity. Compact views present first-entry budget/spend/reserve, four CLOSED trades, final OPEN holdings, a 12-measurement comparison, and ledger time exposure. Separate GROSS and NET charts show all three total-portfolio equity paths.

It reads only the hash-checked local BTCUSDT 1-hour snapshot: 8,760 candles over `[2025-10-01, 2026-10-01)`, first raw OPEN 114,051.1, SHA-256 `0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`. Configuration is EMA20/50, 50 warm-up candles, initial capital 10,000 USDT, fee 0.001 and adverse slippage 0.0005 per side (research assumptions, not current exchange fees). Missing data stops execution; no network call, download, dataset export, or production financial formula duplication occurs.

All 32 cells (17 Markdown / 15 code) executed top to bottom using the existing parent-workspace `.venv/`. Saved execution counts are 1–15, error outputs are zero, and both embedded plots were visually inspected. Each equity path has 8,761 observations; trade 78 remains OPEN and marked without liquidation. The four fraction-1.0 capital/equity headlines and both 12-field partial Stage 7.7 snapshots match at established tolerances. Execution, ledger, and time exposure remain fraction-independent: 77 CLOSED / one OPEN, 4,089 invested hours over 8,760 hours, exposure 0.46678082191780823. Realized/portfolio drawdown and Sharpe/Sortino come from unchanged helpers, with 8,760 periods/year and zero hourly risk-free return/MAR.

Input and raw-hash preservation checks pass. The 37-method Stage 7.7 regression, 16-method frozen EMA regression, and full suite (run once: 747 tests) pass with zero failures, errors, or skips; `git diff --check` passes. No production module, test, decision, data, dependency, earlier notebook, or existing `.py` placeholder changed. Smaller-allocation outcomes are explicitly dataset-specific, not recommendations or general strategy improvements. Stage 7.8 is complete; Stage 7.9 — Final Stage 7 Audit + Docs is complete. Stage 7 is COMPLETE.

## Accepted Stage 7 roadmap

| Milestone | Status |
| --- | --- |
| 7.1 — Risk & Position Sizing Contract | Completed; documentation/architecture only. |
| 7.2 — Position Sizing Core | Completed; standalone budget helper only. |
| 7.3 — GROSS Accounting Integration | Completed; direct GROSS accounting only. |
| 7.4 — NET Accounting Integration | Completed; direct NET accounting only. |
| 7.5 — MTM Equity / Reserve Cash | Completed; direct reserve-aware GROSS/NET equity. |
| 7.6 — Generic Backtest Integration | Completed; unchanged fraction forwarding to both accounting paths. |
| 7.7 — Exact Regression + Analytics Compatibility | Completed; frozen full allocation and 50%/25% downstream regression. |
| 7.8 — Position Sizing Notebook | Completed; executed educational 100%/50%/25% comparison. |
| 7.9 — Final Stage 7 Audit + Docs | Completed; architecture, scope, regression, notebook, and documentation gates passed. |

## Final Stage 7 audit

Stage 7 — Risk Manager + Position Sizing is **COMPLETE**. Milestones 7.1–7.9 in the accepted roadmap are complete. Decision 011 is implemented without a new policy or framework: a fixed scalar `position_fraction` in `0 < f <= 1`, default 1.0, permits a budget from current total capital. GROSS and NET independently convert it into quantity and compound total capital; NET's entry budget includes its fee. Equity retains reserve cash alongside the raw-CLOSE marked canonical holding. The generic pipeline only forwards the fraction and retains its four accounting/execution outputs; analytics receives no sizing-policy parameter.

The eight 7.1–7.8 commits form the expected direct-child chain after Stage 6 baseline `df72973de837ecbd4ee81f4bdaf77efd74730a56`, ending at `fc7965fe7d8af1e107b1204e6007feccc2f7fffb`. Production changes are limited to risk budgeting, GROSS/NET accounting, reserve-aware equity, and generic fraction forwarding. Strategy, execution, ledger, other analytics formulas, dependencies, data/results, decisions 001–010, and notebooks 01–04 retain their baseline contents. No hidden production commit, new committed dataset/result, credential, exchange runtime, database, or Stage 8 implementation was introduced.

Default/explicit 1.0 exact-frame compatibility and all frozen Stage 5/6 references pass at unchanged tolerances. The hash-checked local 8,760-candle BTC snapshot preserves 78 ENTRY / 77 EXIT fills, 77 CLOSED / one OPEN trade, last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 USDT, and final GROSS/NET MTM 9,451.485313939314 / 7,490.776562851941 USDT. Both canonical 0.50/0.25 analytics snapshots pass. Intent, execution, ledger, and time exposure remain fraction-independent: 4,089 invested hours / 8,760 hours, exposure 0.46678082191780823. Final trade 78 remains OPEN without liquidation.

| Audit test module | Passed methods |
| --- | ---: |
| Position sizing core | 35 |
| GROSS sizing | 25 |
| NET sizing | 33 |
| Partial MTM equity | 31 |
| Generic sizing pipeline | 24 |
| Position-sizing analytics regression | 37 |
| Stage 7 additions total | 185 |
| Frozen EMA regression | 16 |
| Full suite, run once | 747 |

Every required targeted module and the full suite passed with zero failures, errors, or skips. No tests were added in Stage 7.9. Committed notebook 05 validates as JSON with 32 cells (15 code / 17 Markdown), sequential counts 1–15, zero saved errors, and two embedded plots; its accepted Stage 7.8 execution was inspected without re-execution or modification. It demonstrates local-only fixed-allocation budgeting, compounding, reserve-aware GROSS/NET equity, drawdown, Sharpe/Sortino, and unchanged time exposure through production APIs. Source/test/decision/notebook/dependency bytes and all data/result files were preserved during this audit; `git diff --check` passes. Closure changes only the allowed documentation.

The completed scope remains single-asset LONG/FLAT fixed allocation: no leverage, shorts, dynamic sizing, stop-based sizing, multi-asset or multi-bot allocation. Stage 8 is COMPLETE under Decision 012 after its final audit; Stage 9 awaits explicit owner approval and has not started.

## Final Stage 6 audit

Decision 010 remains Accepted. Its four canonical fields (`timestamp`, `signal_time`, `signal`, `desired_position`), strict alignment, one-hour availability, integer LONG/FLAT state machine, final-row no-fill rules, and strategy-owned causality match the implementation.

The final architecture is strategy producer → canonical intent → `validate_strategy_output(...)` → `run_execution_pipeline(...)` → ledger → independent GROSS/NET accounting via `run_backtest_pipeline(...)`. The backtest returns exactly `execution`, `trades`, `gross_results`, and `net_results`. Candle OPEN values remain authoritative; diagnostics cannot control fills. Equity and analytics remain reusable downstream components. EMA20/50 is the only reusable production strategy currently implemented.

The six Stage 6 commits are consecutive direct children after frozen Stage 5 commit `a3fde091be234fd78d216f6338752a810fa117f0`, ending at `c004df851862bc68bf2f6937ca7e94a4b1e3a738`. The committed Stage 6 diff contains exactly the 12 expected files, with no unexpected scope.

| Stage 6 test module | Methods |
| --- | ---: |
| Strategy validation (6.2) | 48 |
| Generic execution (6.3) | 25 |
| Generic backtest (6.4) | 15 |
| EMA exact regression (6.5) | 16 |
| Total Stage 6 additions | 104 |

All 104 targeted methods passed with zero failures, errors, or skips, including the real frozen BTC regression. The full suite passed once: 562 tests (458 Stage 5 + 104 Stage 6), zero failures, errors, or skips. Stage 6.6/6.7 add no tests; `git diff --check` passes.

Frozen Stage 5 execution, ledger, accounting, EMA, analytics, decisions 003–009, notebook 03, market-data code, and dependencies have identical Git blobs/trees. The legacy `run_ema_execution_pipeline(...)` source is unchanged. Exact frame parity and existing scalar tolerances preserve BTC execution/accounting, MTM, trade, drawdown, duration/exposure, risk-adjusted, and benchmark references.

Committed notebook 04 has 23 cells (11 code / 12 Markdown), execution counts 1–11, zero saved errors, and one embedded image. Its saved demonstration covers local frozen data, EMA intent, generic execution/ledger/accounting, downstream equity, a synthetic non-EMA contract example, a conceptual future strategy interface, and preservation checks. Neither notebook 03 nor notebook 04 was re-executed during this audit.

Stage 6.7 changes documentation only. No production code, tests, notebooks, decisions, dependencies, raw data, or financial formulas changed. Stage 7.1 has accepted the sizing contract; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic backtest notebook

[Notebook 04](notebooks/04_generic_backtest_engine.ipynb) demonstrates candles → strategy-specific intent → the Decision-010 contract → `run_backtest_pipeline(...)` → `execution`, `trades`, `gross_results`, and `net_results`. Existing EMA20/50 is one intent producer; a five-candle manually supplied contract example reaches the same shared engine without EMA calculations or a new production strategy. Small views explain availability, desired versus executed state, next-OPEN fills, trade pairing, and independent GROSS/NET sizing/compounding.

The notebook loads only the existing frozen local 8,760-candle BTC snapshot through `load_ohlcv_csv(...)`, checking its canonical window, first raw OPEN, and accepted SHA-256. It has no downloader or external API calls and fails clearly when the file is absent. Frozen sanity checks preserve 78 ENTRY / 77 EXIT signals, 78 trades (77 CLOSED / one OPEN), first fill at `2025-10-13 03:00 UTC` for 115,332.3, and last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 USDT.

Existing equity helpers compose downstream; the generic engine still stops at accounting. Each path has 8,761 observations, ending at GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT. The final OPEN holding is marked without liquidation. Modeled fee/slippage rates remain frozen research assumptions, not current exchange fees. The notebook copies no production financial formulas; Stage 6.5 remains the authoritative exact compatibility regression.

Executed top to bottom using the existing parent-workspace `.venv/`: 23 total cells, 11 code, 12 Markdown, sequential execution counts 1–11, zero saved errors, and one rendered plot. All intended outputs are saved; the plot was visually inspected. Candles, strategy output, and raw bytes are preserved. The full unchanged suite passed once with 562 tests; no new tests, dependencies, or production modules were added or changed. Notebooks 01–03 and all existing `.py` placeholders are unchanged; notebook 03 was not executed. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## EMA exact regression / compatibility

Stage 6.5 is a regression gate only. The canonical local `data/raw/BTCUSDT_1h.csv` loads through `load_ohlcv_csv(...)` with the explicit hourly window `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. Before EMA calculations, the new regression module checks the existing frozen SHA-256 from notebook 03, 8,760 rows, first/last timestamps, and first raw OPEN 114,051.1. No download, network call, or raw-file modification occurs. Established local-snapshot test policy permits skipping only when the file is absent on another clone; this environment ran all 16 methods with zero skips.

Using unchanged EMA20/EMA50 and 50 initialization candles, separately generated strategy output exactly matches the legacy combined frame's strategy subset. `run_execution_pipeline(...)` and `run_backtest_pipeline(...)["execution"]` exactly match its six execution columns; generic ledger and independent GROSS/NET accounting exactly match the direct legacy helper path. Frame checks use `check_exact=True`; frozen scalar checks retain notebook 03's established tolerances. Full outputs are cached once per test class.

Bullish/bearish crossovers remain 78/78; ENTRY/EXIT signals and fills remain 78/77; final desired position remains 1. First ENTRY intent is `2025-10-13 02:00 UTC`, filled at the next OPEN `2025-10-13 03:00 UTC` for 115,332.3. The ledger remains 78 trades: 77 CLOSED and one final OPEN with missing exit fields and entry-only accounting. No terminal liquidation is introduced.

Last CLOSED realized capital remains GROSS 9,641.111388344 / NET 7,652.530163437 USDT. Existing equity helpers produce 8,761 observations and final OPEN marks of GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT, exactly matching legacy equity paths. Existing CLOSED-trade summaries, realized/portfolio drawdown, duration/exposure, hourly returns, Sharpe/Sortino, and Buy-and-Hold comparison pass frozen Stage 5 references. NET rates 0.001 fee / 0.0005 adverse slippage remain research assumptions, not current exchange fees.

All 16 Stage 6.5 methods and all 562 tests pass. Candles, strategy output, accounting/equity sources, and raw bytes are preserved. All production Python modules, the existing EMA compatibility function, old tests, decisions 001–010, earlier notebooks, and dependencies are unchanged. Stage 6.6 adds the separate notebook 04 demonstration above. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic end-to-end backtest pipeline

`run_backtest_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0) -> dict`

Any valid Decision-010 strategy output can pass through validation/execution, the trade ledger, and independent GROSS/NET accounting. The function owns call order only: `run_execution_pipeline(...)` → `build_trade_ledger(...)` → `calculate_trade_results(...)` → `calculate_trade_results_with_costs(...)`. Both accounting functions receive the same ledger and unchanged `position_fraction`; NET is not derived from the returned GROSS results. Existing helpers own validation, timing, trade pairing, financial mathematics, and output schemas. The pipeline performs no fraction validation or sizing and imports no risk helper.

The new dictionary contains exactly four separate DataFrames: `execution`, `trades`, `gross_results`, and `net_results`, each the corresponding helper's exact output. Strategy diagnostics are ignored; inputs remain unchanged. No strategy generation, analytics summary, equity path, or mark-to-market valuation is included.

An executed entry may remain OPEN with entry-only accounting and missing exit/realized fields. A final unexecuted ENTRY creates no trade; a final unexecuted EXIT leaves the existing trade OPEN. No terminal fill or close is forced. All-HOLD and typed empty inputs retain helper-defined schemas and dtypes.

All 15 new Stage 6.4 methods pass; that milestone's full suite passed with 546 tests. These tests use only synthetic data, including a non-EMA CLOSED trade at recorded prices 100 → 110, multiple trades with independent compounding, zero/nonzero cost parameters, exact four-frame parity, call order, error propagation, preservation, and index/timezone checks. The existing EMA pipeline remains internally unchanged. Stage 6.5 now proves exact EMA compatibility on the frozen BTC snapshot; notebooks 01–03 were neither modified nor executed. Stage 5 remains COMPLETE and frozen. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic execution pipeline

`src/trading_lab/backtest/pipeline.py` now exposes:

`run_execution_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

The function calls `validate_strategy_output(...)` before `apply_next_open_execution(...)`. The validator owns intent/alignment/availability; execution owns continuous hourly spacing, valid fill OPEN prices, next-OPEN timing, executed state, and final-row no-fill rules. No indicator logic, warm-up rule, close requirement, or duplicated execution algorithm is added.

Candles supply `timestamp` and authoritative market `open`. Only validated `signal` is transferred into a deep candle copy, replacing any unrelated candle signal locally. Arbitrary strategy diagnostics, including `open` or execution-like names, are ignored and not merged into execution output. Both source DataFrames remain unchanged; ordinary scalar edits to the result do not affect them.

The return is the existing execution helper's exact schema/order/dtypes/index: `timestamp`, `open`, `signal`, `execution_time`, `execution_price`, `executed_position`. Reused alignment checks verify row count, index, and timestamps; additional postconditions verify unchanged validated signals and market OPEN values. Direct-helper parity, non-RangeIndex/duplicate-label alignment, typed empty output, and naive/aware clock checks pass. Valid final entries/exits remain unfilled without forced closing; a newly appended next candle may populate former-final fill metadata without changing earlier rows or state during that candle.

All 25 Stage 6.3 test methods pass; that milestone's full suite passed once with 531 tests (506 earlier + 25 new). `run_ema_execution_pipeline(...)` is not refactored into a wrapper and its source is unchanged. This execution-only API stops before the ledger; Stage 6.4 adds the separate ledger/accounting composition API above. Analytics remain separate downstream components. Stage 5 remains COMPLETE and frozen; notebooks 01–03 were neither modified nor executed. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic strategy output validation

Decision 010 is implemented by `src/trading_lab/backtest/strategy_validation.py`:

`validate_strategy_output(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

Candles need only `timestamp`; strategy output requires `timestamp`, `signal_time`, `signal`, and `desired_position`. Both DataFrames need unique column names. Row counts, indexes (`Index.equals`), and timestamp Series (`Series.equals`) must match exactly. Timestamps must already be non-missing, unique, chronological pandas datetimes; compatible datetime/timezone representation is preserved. Non-RangeIndex and duplicate index labels are valid when aligned. No parsing, sorting, repair, OHLCV checks, candle-spacing enforcement, or warm-up rules are added.

Every signal_time equals its timestamp plus one elapsed hour, including HOLD/final rows and DST transitions. Start desired state FLAT (0); LONG_ENTRY changes 0 → 1, LONG_EXIT changes 1 → 0, and HOLD preserves state. Require Python/NumPy integer 0/1; reject bools, floats, strings, missing values, invalid signals, and inconsistent transitions with ValueError. Valid final-row events and aligned empty typed frames remain valid intent. Causality stays the strategy's responsibility.

The return value is a new full DataFrame copy: canonical and diagnostic columns, values, dtypes, index, and column order are unchanged. Both inputs are preserved; ordinary scalar output edits do not mutate the source. Synthetic EMA output passes without modifying EMA logic. No execution helper is called and no fills or financial fields are added. `run_execution_pipeline(...)` now delegates to this validator; the existing EMA pipeline remains unchanged.

All 48 Stage 6.2 test methods pass; that milestone's full suite passed once with 506 tests (458 earlier + 48 new). Stage 5 remains COMPLETE and frozen, including notebook 03 (104 cells, 51 code / 53 Markdown, seven plots), which was neither modified nor executed. Stage 6.4 now composes execution, ledger, and independent accounting. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Final Stage 5 analytics report

Notebook 03 brings together CLOSED-trade performance, realized-capital drawdown, duration/exposure, candle-level MTM equity, candle-close portfolio drawdown, Buy-and-Hold comparison, time-based returns, volatility, and Sharpe/Sortino. Its final report reads existing outputs for setup, a seven-row/four-portfolio comparison, EMA behavior, costs, benchmark opportunity cost, drawdown, time, and risk-adjusted interpretation. Explicit limitations cover this single BTC sample, fixed modeled costs, hourly marks, final OPEN positions, and absent out-of-sample validation.

The final audit checks the 8,760-candle snapshot, 78 executed entries / 77 exits, 77 CLOSED / one final OPEN trade, all four 8,761-observation equity paths and 8,760-return clocks, financial/risk/time references, raw CSV hash, and preservation of 31 report-source DataFrames. All seven existing plot sources/images and earlier calculations are preserved. The notebook has 104 cells (51 code / 53 Markdown), sequential execution, and no saved errors. All 458 existing tests pass; Stage 5.18 adds no tests or metric logic. Production code/tests, decisions, notebooks 01/02, raw data, and dependencies are unchanged.

Stage 5 — Analytics remains complete and frozen at the committed Stage 5.18 baseline. Stage 6.5 proves exact EMA compatibility through generic execution, ledger, accounting, and existing analytics; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable time-based returns and risk-adjusted metrics

[Decision 009](decisions/009_time_based_returns_and_risk_adjusted_metrics.md) is implemented by `src/trading_lab/analytics/risk_adjusted.py`:

- `calculate_time_based_returns(equity_path: pd.DataFrame) -> pd.DataFrame`
- `summarize_risk_adjusted_performance(equity_path: pd.DataFrame, periods_per_year: float, risk_free_return_per_period: float = 0.0, minimum_acceptable_return_per_period: float = 0.0, label: str = "PORTFOLIO") -> pd.DataFrame`

Consume only existing marked portfolio equity, independently for EMA GROSS/NET and Buy-and-Hold GROSS/NET. Time-based returns describe portfolio value through time; completed-trade metrics describe completed trades. No candles, raw asset returns, CLOSED-trade returns/PnL, realized-capital paths, sizing, or fee formulas are substituted.

For ending observation i, simple return is `E_i / E_(i-1) - 1`, timed from previous valuation to current valuation. No log returns, fake observation-0 return, first-return omission, or filtering of flat hours. Exact six-column path: `observation`, `period_start_time`, `period_end_time`, `starting_equity`, `ending_equity`, `period_return`, on a new RangeIndex. Ending ordinals are int64 1..N, datetimes preserve the coherent clock, and financial fields are float64. The summary reuses that helper and returns one row indexed by label: `period_count` (int64), then float64 `mean_period_return`, `period_return_std`, `annualized_volatility`, `downside_deviation`, `annualized_downside_deviation`, `sharpe_ratio`, `sortino_ratio`.

Validation requires unique/required columns, at least two equity observations, canonical integer ordinals 0..N, valid coherent strictly increasing datetimes, equal elapsed spacing including same-zone DST, and finite real numeric equity with bools rejected. First equity is positive and later equity non-negative; every starting equity is positive. A final positive-to-zero loss returns -1; zero before another observation fails. Do not parse, sort, repair, interpolate, or replace zero denominators. Annualization must be explicit positive finite real numeric; rf/MAR must be finite real numeric, all rejecting bools/strings. Labels are nonempty strings. Outputs are independent and sources unchanged; unsafe non-finite arithmetic fails clearly.

Sharpe is `mean(r - rf) / std(r - rf, ddof=1) * sqrt(periods_per_year)`. Hourly standard deviation is sample std; annualized volatility is that std times the same square-root factor. Sortino is `(mean(r) - MAR) / sqrt(mean(min(r - MAR, 0)**2)) * sqrt(periods_per_year)`, with the downside mean over ALL periods, not a negative-return subset. Annualized downside deviation uses the same factor. Current hourly 24/7 crypto convention is `365 * 24 = 8760`, independent of sample row count; rf and MAR are zero because no cash yield is modeled. No external rate is retrieved or converted.

Exact zero standard deviation gives Sharpe +inf / -inf / NaN according to positive / negative / zero mean excess. Exact zero downside gives Sortino +inf for positive numerator or NaN for zero. A single actual return has NaN sample std, annualized volatility, and Sharpe; Sortino still follows its downside rule. No epsilon, infinity clamping, or invented observations. These are documented undefined/degenerate results, not normal BTC results.

The unchanged BTC paths provide 8,760 equally spaced periods: first `2025-10-01 00:00 → 01:00 UTC`, final end `2026-10-01 00:00 UTC`. All four ordinal arrays and both return clocks align exactly. Each independently uses `periods_per_year=8760`, `rf=0`, `MAR=0`:

| Measurement | EMA GROSS | Buy & Hold GROSS | EMA NET | Buy & Hold NET |
| --- | ---: | ---: | ---: | ---: |
| Hourly return periods | 8,760 | 8,760 | 8,760 | 8,760 |
| Mean hourly return | -0.00020683% | -0.00244285% | -0.00285941% | -0.00245998% |
| Hourly sample standard deviation | 0.29590511% | 0.46910330% | 0.29638903% | 0.46909987% |
| Annualized volatility | 27.69520093% | 43.90566292% | 27.74049327% | 43.90534186% |
| Hourly all-period downside deviation | 0.20263178% | 0.33458454% | 0.20449375% | 0.33458454% |
| Annualized downside deviation | 18.96529558% | 31.31539704% | 19.13956636% | 31.31539704% |
| Sharpe ratio | -0.06542095 | -0.48739453 | -0.90295525 | -0.49081624 |
| Sortino ratio | -0.09553483 | -0.68335011 | -1.30872474 | -0.68814247 |

Percentages label return/variability fields; Sharpe/Sortino are dimensionless raw ratios. All results above are finite. EMA GROSS/NET retain 4,647 / 4,595 exact zero-return hours; benchmark GROSS/NET each has three. Unchanged cash periods are included, not filtered. Final EMA trade 78 remains OPEN and its marked-equity change naturally enters the final return. No forced sale, liquidation costs, or realized OPEN result is added.

Sharpe measures reward relative to total variability; Sortino measures reward relative to deviations below MAR. Signs here are relative to zero hourly return. EMA NET finishes with slightly more equity than NET Buy-and-Hold but has more negative ratios; compounded final wealth and arithmetic return relative to variability answer different questions. Results depend on interval, annualization, costs, exposure, and sample window, and establish neither general superiority nor statistical significance.

Notebook 03 snapshots all four equity sources before calling the reusable helpers, displays one compact eight-row comparison and representative first/flat/invested/final return previews, and retains one transparent NET hourly-return scatter plot. Its final Stage 5.18 report brings the notebook to 104 cells (51 code / 53 Markdown), executed sequentially without errors, with seven plots and all seven prior plot sources/images unchanged. Assertions check all 8,760 periods, full clocks, spot formulas, cash zeros, final OPEN marks, actual summary references, all four equity sources, candles, and raw CSV hash. The 61 Stage 5.17 tests cover these contracts, synthetic conventions/degenerate cases, strict validation/DST/preservation/causal prefixes, and actual EMA/benchmark integration. All 458 tests pass. Stage 5.18 preserves production code/tests, decisions, notebooks 01/02, raw data, and dependencies; Stage 5 remains complete; Stage 6.5 proves exact EMA regression through the generic path; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable Buy-and-Hold benchmark comparison

[Decision 008](decisions/008_buy_and_hold_benchmark.md) is implemented by `src/trading_lab/analytics/benchmark.py` with exactly two public APIs:

- `calculate_gross_buy_and_hold_benchmark(candles: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame`
- `calculate_net_buy_and_hold_benchmark(candles: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0) -> pd.DataFrame`

Buy at the first raw OPEN, independent of EMA signals/execution: one canonical trade ID 1, status OPEN, with missing exit time/price. GROSS delegates to Stage 4.6; NET independently delegates to Stage 4.7 with self-financing entry sizing and one actual entry fee/adverse slippage. Both delegate to Stage 5.11 equity and return its exact 11-column schema. The initial flat point is immediately before purchase; N candles produce N + 1 observations, then remain long with ID 1 at each raw CLOSE timed at OPEN + interval. No forced exit or hypothetical exit fee/sell slippage is added; final marked equity is not liquidation proceeds. Zero-cost NET equals GROSS exactly.

Entry guards check DataFrame, unique/required `timestamp`/`open`/`close` columns, nonempty input, usable positive real first OPEN, and an existing first datetime without parsing. Existing accounting/equity validators handle the remaining financial, interval, timestamp, and CLOSE rules. Inputs are unchanged; no sorting, repair, interpolation, framework, class, or new dependency is introduced. Benchmark drawdown reuses the Stage 5.14 calculate/summary helpers.

The unchanged BTC snapshot starts at `2025-10-01 00:00 UTC`, first OPEN 114,051.1 USDT, and finishes at `2026-10-01 00:00 UTC`, marking the final CLOSE 83,616.2 USDT. Each path has initial equity 10,000 USDT and exactly 8,761 aligned observations. NET research assumptions remain `fee_rate=0.001`, `slippage_rate=0.0005`; the benchmark pays one entry, while EMA pays its actual turnover costs. These are modeled assumptions, not current exchange fees.

| Measurement | EMA GROSS | Buy & Hold GROSS | EMA NET | Buy & Hold NET |
| --- | ---: | ---: | ---: | ---: |
| Initial equity (USDT) | 10,000 | 10,000 | 10,000 | 10,000 |
| Final marked equity (USDT) | 9,451.485313939314 | 7,331.468087550229 | 7,490.776562851941 | 7,320.483701755746 |
| Total marked return | -5.4851468606% | -26.6853191245% | -25.0922343715% | -26.7951629824% |
| Maximum candle-close drawdown | -27.6794381422% | -53.7338388920% | -37.9679609807% | -53.7338388920% |
| Observations | 8,761 | 8,761 | 8,761 | 8,761 |

EMA minus benchmark final equity is GROSS +2,120.017226389085 USDT / NET +170.292861096195 USDT; total marked return differences are +21.2001722639 / +1.7029286110 percentage points. Whole-window return means `final equity / initial equity - 1`, not hourly returns or annualization. All four paths lose capital in this declining-BTC sample: EMA's relative advantage does not prove general superiority. Both benchmark paths finish OPEN; no liquidation is fabricated.

Notebook 03 uses helper outputs for the tables and existing equity-comparison plot, with reference assertions for rows, full valuation-time alignment, first-OPEN timing, final OPEN marks, benchmark drawdowns, unchanged EMA/candle inputs, and raw CSV hash. The final Stage 5.18 report preserves the benchmark and time-based analytics sections: 104 cells (51 code / 53 Markdown), seven plots, sequential execution, no saved errors, and all seven prior plot sources/images unchanged. The 38 benchmark tests include exact schemas, delegated sizing/costs, paid-once/no-exit behavior, zero-cost equality, validation, input/output independence, causal prefixes, existing drawdown integration, and actual BTC alignment. All 458 tests pass, including these unchanged 38 benchmark tests. Decision 009 supplies time-based returns and Sharpe/Sortino; Stage 6.4 provides generic execution/ledger/accounting composition; analytics remain separate, Stage 6.5 exact EMA regression is complete, and Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable candle-close portfolio drawdown

[Decision 007](decisions/007_candle_close_portfolio_drawdown.md) is implemented by `src/trading_lab/analytics/portfolio_drawdown.py`. Its sole input is a Stage 5.11 GROSS or NET equity path, requiring `observation`, `valuation_time`, and `equity`. Extra columns are ignored. It never consumes candles/accounting again or reconstructs equity. Both source schemas are identical: the GROSS/NET wrappers express caller intent and summary labels, not detectable provenance or different formulas.

For each observation, `running_peak = max(equity observed so far)`, `drawdown = equity / running_peak - 1`, and `drawdown_amount = equity - running_peak`. Drawdown is a negative decimal; amount is non-positive quote currency. Keep the supplied positive initial observation 0 with zero drawdown/amount; accept later zero equity as `-1.0` drawdown. No new initial-capital parameter, synthetic row, sorting, repair, or lookahead is allowed.

Exact path columns: `observation`, `valuation_time`, `equity`, `running_peak`, `drawdown`, `drawdown_amount`, on a new RangeIndex with unchanged row order/count. Exact summary fields: `max_portfolio_drawdown`, `max_portfolio_drawdown_amount`, `peak_observation`, `trough_observation`, `peak_valuation_time`, `trough_valuation_time`, `peak_equity`, `trough_equity`, in one row indexed GROSS or NET. Financial fields are float64, ordinals int64, and timestamps preserve a coherent source clock. Inputs remain unchanged.

Select the earliest exact minimum percentage-drawdown trough, then the latest exact matching running-peak occurrence at or before it. The summary currency amount belongs to that trough, not an independent minimum amount. Flat/increasing and initial-only paths select initial observation 0 as both peak and trough. Final OPEN marks are naturally included through supplied equity, without status handling or forced closure.

Public APIs: `calculate_gross_portfolio_drawdown(gross_equity_path)`, `calculate_net_portfolio_drawdown(net_equity_path)`, `summarize_gross_portfolio_drawdown(gross_equity_path)`, and `summarize_net_portfolio_drawdown(net_equity_path)`. Each takes only its equity path and returns a new DataFrame. Validation covers unique/required columns, nonempty input, canonical integer ordinals, safely representable strictly increasing coherent datetimes, positive initial/non-negative later finite real equity, and finite float64 arithmetic. No interval/equal-spacing requirement, bool acceptance, parsing, sorting, repair, or timezone conversion is introduced.

The 55 Stage 5.14 tests cover schemas/dtypes, initial-only/flat/increasing/full-loss/recovery paths, worked examples, exact trough/peak ties, associated currency amount, causal prefixes, malformed values/schema/order/clocks, DST, unequal time spacing, optional columns, duplicate indexes, deep-copy/output independence, actual Stage 5.11 integration, and final OPEN marks. All 458 tests pass, including these unchanged 55 tests; Stage 5.15 added no unit tests. Decision 004 retains initial-plus-post-CLOSED observations and excludes/unvalues OPEN; decision 007 observes initial-plus-every-CLOSE equity. Neither candle-CLOSE observations nor HIGH/LOW reveal the full intrabar path. Duration, recovery, and further risk/return metrics remain deferred. Decisions 008/009 now supply aligned Buy-and-Hold comparison, time-based returns, and Sharpe/Sortino.

Stage 5.15 introduced these unchanged helpers in notebook 03 using existing equity paths, compact ten-result summaries, realized-versus-portfolio comparison, selected-episode previews, and one drawdown plot. The current flow is performance → realized-capital drawdown → MTM equity → candle-close portfolio drawdown → benchmark comparison → time-based returns and Sharpe/Sortino → TIME → costs → final OPEN → final integrated report → audit and limitations. Stage 5.18 preserves the earlier sections and all seven plot sources/images. All 51 code cells executed sequentially without errors: 104 total cells, 53 Markdown, seven plots. All tables/plot coordinates come from helper outputs; fixed BTC values are regression assertions only.

## BTC candle-close portfolio drawdown check

The unchanged local loader → EMA20/EMA50 execution pipeline → ledger → independent accounting → Stage 5.11 equity pipeline uses 8,760 hourly candles, 77 CLOSED trades, and one final OPEN trade. Initial capital is 10,000 USDT; NET uses test assumptions only: fee rate 0.001 per side and adverse slippage rate 0.0005 per side. Each equity path feeds its new calculate/summary helpers directly, producing 8,761 drawdown rows including initial observation 0.

| Field | GROSS | NET |
| --- | ---: | ---: |
| `max_portfolio_drawdown` | -0.2767943814221776 | -0.37967960980713844 |
| `max_portfolio_drawdown_amount` (USDT) | -2,779.158887053809 | -3,806.4682385473616 |
| `peak_observation` | 308 | 308 |
| `trough_observation` | 3,687 | 7,369 |
| `peak_valuation_time` (UTC) | 2025-10-13 20:00 | 2025-10-13 20:00 |
| `trough_valuation_time` (UTC) | 2026-03-03 15:00 | 2026-08-04 01:00 |
| `peak_equity` (USDT) | 10,040.517704060354 | 10,025.474479603712 |
| `trough_equity` (USDT) | 7,261.358817006545 | 6,219.0062410563505 |
| Final drawdown | -0.07677164110576007 | -0.25282573128169417 |
| Final running peak (USDT) | 10,237.429583791658 | 10,025.474479603712 |

This sample's 78-point realized-capital paths have maximum drawdowns GROSS -26.7234254550% / NET -37.1855332627%; the 8,761-point candle-close portfolio paths show -27.6794381422% / -37.9679609807%. Here the observed portfolio declines are deeper by 0.9560126872 / 0.7824277180 percentage points. These results come from independently checked paths, not a required universal ordering of the two metrics.

Final observation 8,760 at `2026-10-01 00:00 UTC` retains trade 78's OPEN marked equity: GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT. The final drawdowns are -7.6771641106% / -25.2825731282%. Every source observation is present; no status logic, closing fill, hypothetical exit costs, duration, or recovery calculation is added. Deep-copy checks preserved candles, pipeline/ledger/accounting/equity inputs and the raw CSV hash. Stage 5.15 now presents these results in notebook 03 and verifies the complete peak/trough episode above against helper outputs. This remains candle-CLOSE risk, potentially missing intrabar/tick lows; the notebook explains the conceptual 10,000 → intrabar 7,000 → CLOSE 9,500 limitation without calculating a BTC intrabar metric.

## Reusable candle-level portfolio equity

[Decision 006](decisions/006_candle_level_mark_to_market_equity.md) is implemented by `src/trading_lab/analytics/equity.py`. Consume validated market candles with at least `timestamp` (OPEN time) and `close`, plus independent canonical GROSS results from Stage 4.6 `calculate_trade_results(...)` or NET results from Stage 4.7 `calculate_trade_results_with_costs(...)`. Reuse each path's quantity and realized capital without resizing, reconstructing PnL/capital, or rerunning cost formulas; Stage 4.7 `gross_pnl` is not the independent GROSS simulation. Stage 7.5 implements Decision 011 reserve-cash semantics for both full and partial canonical accounting results while preserving Decision 006 valuation timing and schema.

Public functions: `calculate_gross_mark_to_market_equity(candles, gross_results, candle_interval, initial_capital=10_000.0)` and `calculate_net_mark_to_market_equity(candles, net_results, candle_interval, initial_capital=10_000.0)`. Both return new independent path DataFrames. GROSS requires `trade_id`, `status`, `entry_time`, `entry_price`, `exit_time`, `capital_before`, `quantity`, `capital_after`; NET requires `trade_id`, `status`, `entry_time`, `exit_time`, `capital_before`, `quantity`, `effective_entry_price`, `entry_fee`, `net_capital_after`, even for empty input. Wrong accounting sources fail clearly. Initial capital is an independent positive finite real parameter, never inferred; use the same value as accounting.

The required explicit positive fixed `candle_interval` defines `observation_start = first timestamp` and `observation_end = last timestamp + interval`. N contiguous candles give N + 1 observations. Initial observation 0 is immediately before any first-OPEN fill. For each candle: carry state → actual EXIT at its OPEN → actual ENTRY at its OPEN → observe completed CLOSE → mark remaining quantity → record at OPEN timestamp + interval. A preceding CLOSE observation occurs before the next OPEN's fills at the same boundary timestamp. If a future valid ledger shares exit/entry time, EXIT precedes ENTRY; current upstream validation stays unchanged. Fills must match supplied candle OPENs; the exclusive window end is not an extra OPEN.

Both paths mark at the same raw market CLOSE. Current scope is one asset, long-only spot, one position, no leverage, canonical full or partial entry allocation, fixed NET cost assumptions, and fixed-interval candle-CLOSE marking. After entry, cash is derived reserve and quantity is canonical; `position_value = quantity * close` and `equity = cash + position_value`. GROSS price-based `unrealized_pnl = quantity * (close - entry_price)`; NET uses `effective_entry_price` instead and excludes the already-paid entry fee. NET entry slippage/fee already affect canonical basis/quantity; do not charge entry fee again. Conceptually `equity = capital_before - entry_fee + unrealized_pnl`; at the effective-entry basis mark, NET unrealized PnL is zero while total equity is lower than capital before by the paid fee.

At an actual exit, set cash directly to GROSS `capital_after` / NET `net_capital_after`, clear position/active ID, and set quantity/value/unrealized PnL to zero. NET realized cash already includes actual exit costs. Do not re-sell quantity or subtract costs again. If the portfolio stays flat, that candle's CLOSE equity reconciles to canonical realized cash. With a replacement entry at the same OPEN, reconcile immediately after exit and then mark the new position; do not force its CLOSE equity to the old realized value.

The final OPEN position is marked on every remaining CLOSE, including the last, without inventing exit time, realized PnL, or capital-after values. Marking creates no trade and charges no hypothetical exit fee/slippage, spread, or bid/ask adjustment. Final NET equity reflects only costs actually incurred, not hypothetical liquidation proceeds. Existing accounting/realized analytics retain their separate OPEN semantics; Stage 5.12 now presents the independent equity paths and final OPEN valuation in notebook 03.

Exact columns, in order: `observation`, `candle_timestamp`, `valuation_time`, `mark_price`, `position`, `active_trade_id`, `cash`, `quantity`, `position_value`, `unrealized_pnl`, `equity`. Output has a RangeIndex; observation/position are int64, active ID nullable Int64, all six price/financial fields float64, and timestamps retain coherent datetime/timezone semantics. Initial row: `0`, `NaT`, `observation_start`, `NaN`, `0`, missing ID, `initial_capital`, `0.0`, `0.0`, `0.0`, `initial_capital` respectively. Each subsequent mark belongs to its source candle and is timed at its completion.

Decision 006 specifies strict candle spacing/positive CLOSE validation, event-to-OPEN alignment, canonical source/status/order/non-overlap checks, capital/allocation reconciliation, finite arithmetic, coherent all-naive or matching-zone-aware timestamps, and input preservation without sorting, repair, parsing, or timezone conversion. UTC remains recommended. No future exit or next-candle price may influence a current mark. Zero trades still give N + 1 flat constant-equity observations with recorded candle marks. OPEN-only input is marked from entry onward; a final-OPEN entry gets a final CLOSE mark, while a final-OPEN exit leaves realized cash if flat. An unexecuted final-candle signal is not a fill.

Decision 004 remains separate and unchanged: initial plus post-CLOSED realized-capital drawdown omits within-trade losses. Decision 007 is now implemented from the initial-plus-every-CLOSE equity series. This still cannot observe intrabar/tick losses. A fall from prior-close equity 10,000 to an intrabar 7,000 followed by a 9,500 CLOSE records only 9,500. HIGH/LOW does not reconstruct that path; excursion/stress analytics and further portfolio-metric implementations remain deferred. Decision 006's worked GROSS example passes as a synthetic test: 1,000 → 1,100 → 900 → 1,200 versus realized 1,000 → 1,200.

## BTC candle-level equity check

Used the existing local BTCUSDT snapshot through the unchanged loader, default EMA20/EMA50 pipeline with 50-candle warm-up, ledger, and independent Stage 4 accounting. Initial capital is 10,000 USDT and interval is one hour. NET uses the established research assumptions `fee_rate=0.001`, `slippage_rate=0.0005` (0.10% fee / 0.05% adverse slippage per side), not current exchange fees.

| Measurement | GROSS | NET |
| --- | ---: | ---: |
| Equity path rows (8,760 candles) | 8761 | 8761 |
| Initial equity, USDT | 10000 | 10000 |
| Final position / active trade ID | 1 / 78 | 1 / 78 |
| Final quantity, BTC | 0.1130341406801471 | 0.08958523064731405 |
| Final price-based unrealized PnL, USDT | -189.62607440501543 | -154.10871530682684 |
| Final position value, USDT | 9451.485313939314 | 7490.776562851941 |
| Final marked equity, USDT | 9451.485313939314 | 7490.776562851941 |
| CLOSED exit observations reconciled | 77 / 77 | 77 / 77 |

The ledger has 77 CLOSED trades and one final OPEN trade. Final candle OPEN is `2026-09-30 23:00 UTC`, raw CLOSE is 83,616.2 USDT, and final valuation time is `2026-10-01 00:00 UTC`. Both paths end long with zero cash; trade 78 remains OPEN with missing exit/capital-after values. Its marked equity is not realized capital or hypothetical liquidation proceeds. Stage 5.12 presents these values in notebook 03 alongside a realized-versus-marked table, compact previews, and one time-axis equity plot. Input/path deep-copy and raw-hash checks pass; no dataset/report is exported. Stage 5.15 now also presents portfolio drawdown from these same unchanged MTM paths, including their final OPEN observations naturally.

## Reusable trade duration and exposure

[Decision 005](decisions/005_trade_duration_and_exposure.md) is implemented by `src/trading_lab/analytics/trade_time.py`. Its helpers consume `trades`, the canonical executed ledger from `build_trade_ledger(...)`, requiring `trade_id`, `status`, `entry_time`, and `exit_time` even when empty. Price economics and optional accounting fields do not affect time analytics. Current fees/slippage change quantity/PnL/capital but not fill timestamps, so calculate once from the ledger. Any strategy/model producing that ledger can share these helpers.

For CLOSED trades, `closed_trade_duration = exit_time - entry_time > 0` over `[entry_time, exit_time)`. Hours express elapsed seconds divided by 3,600, preserving fractional and sub-microsecond precision without counting candles or rounding. OPEN completed duration is NaN and excluded from all CLOSED descriptive statistics/totals. Its observed interval through `observation_end` still contributes to exposure, without changing its missing ledger exit or creating a valuation.

The caller supplies an explicit positive `[observation_start, observation_end)` window; boundaries are never inferred from trading activity. For candle research, start is the first candle OPEN and end is the final candle OPEN plus its interval. The BTC check uses `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`, including the final hour, warm-up, and flat periods. No dataset-specific dates or values are hardcoded into analytics.

```text
observation_window_duration = observation_end - observation_start
total_time_in_market = sum(CLOSED exit_time - entry_time)
                       + (observation_end - final OPEN entry_time, if present)
exposure_ratio = total_time_in_market / observation_window_duration
```

Exposure is a decimal `[0, 1]`, without annualization or internal percentage conversion. Summing intervals relies on the current non-overlapping, single-position ledger. A ten-hour window with one three-hour CLOSED interval and one three-hour observed OPEN interval gives six hours / ten hours = 60% exposure; CLOSED descriptive durations contain only the completed trade. Using the first entry to shorten that window to nine hours would incorrectly report 66.67%.

Public APIs: `calculate_trade_time_breakdown(trades: pd.DataFrame, observation_start, observation_end) -> pd.DataFrame` and `summarize_trade_time_metrics(trades: pd.DataFrame, observation_start, observation_end) -> pd.DataFrame`. Both boundaries are required, with no defaults. The summary reuses the validated per-trade calculation. Exact per-trade columns, in order: `trade_id`, `status`, `entry_time`, `exit_time`, `closed_duration_hours`, `observed_time_in_market_hours`. The new table preserves source order/index, IDs/status, timestamps/dtypes/timezones, and the original missing OPEN exit; duration fields use float64 even when empty. No price, PnL, or capital fields are added.

Exact separate summary columns, in order: `closed_trade_count`, `open_trade_count`, `average_closed_duration_hours`, `median_closed_duration_hours`, `minimum_closed_duration_hours`, `maximum_closed_duration_hours`, `total_closed_duration_hours`, `open_observed_duration_hours`, `total_time_in_market_hours`, `observation_window_hours`, `exposure_ratio`. One row is indexed `TIME`; counts are int64 and the other nine fields float64. The existing 16-metric summaries and drawdown component remain unchanged.

With no trades, counts, aggregate holding times, and exposure are zero; the four CLOSED descriptive duration statistics are NaN and the explicit window remains positive. OPEN-only input also has NaN CLOSED descriptive statistics, but its observed time produces positive exposure. An entry at window start still OPEN through its end gives exposure `1.0`, without a completed duration.

Validation requires unique DataFrame columns, the schema even when empty, exact CLOSED/OPEN statuses, valid non-missing datetime scalars, safely representable positive elapsed durations, entries within `[start, end)`, and CLOSED exits after entry and no later than end. Strings/numeric epochs are rejected rather than parsed. OPEN exits must be missing; OPEN entry at end is invalid. At most one OPEN is allowed, as the final row. Entries must be chronological and each next entry must be at or after the previous CLOSED exit; touching half-open boundaries are allowed. Malformed order/overlap is rejected without sorting, clipping, or repair. Both APIs preserve their input; full ledger validation stays upstream. UTC-aware timestamps are recommended; accept all-naive inputs or all-aware inputs with matching timezone implementation/zone, including DST offset changes within that zone. Reject mixing/different zones without localization, conversion, or stripping; aware subtraction measures actual elapsed time.

## BTC trade duration and exposure check

The unchanged local loader → EMA20/EMA50 pipeline (50-candle warm-up) → canonical trade ledger feeds both time APIs directly. No gross/net accounting is called. The explicit window is `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`: first candle timestamp through last candle timestamp plus one hour. Inputs and the raw-file hash were preserved.

| TIME summary field | BTC result |
| --- | ---: |
| `closed_trade_count` | 77 |
| `open_trade_count` | 1 |
| `average_closed_duration_hours` | 52.96103896103896 |
| `median_closed_duration_hours` | 34.0 |
| `minimum_closed_duration_hours` | 1.0 |
| `maximum_closed_duration_hours` | 226.0 |
| `total_closed_duration_hours` | 4078.0 |
| `open_observed_duration_hours` | 11.0 |
| `total_time_in_market_hours` | 4089.0 |
| `observation_window_hours` | 8760.0 |
| `exposure_ratio` | 0.46678082191780823 |

The first CLOSED trade lasted 27 hours; the longest was trade 68 at 226 hours. Final OPEN trade 78 entered at `2026-09-30 13:00 UTC` and contributes 11 observed hours. Its exit remains missing and its completed duration remains NaN; it is not valued. Exposure is about 46.678082% for this sample, with no general strategy-quality conclusion. Stage 5.9 presents these same helper outputs in notebook 03 with a separate TIME table, six-row preview, longest-CLOSED inspection, and regression assertions.

## Reusable realized-capital drawdown

Module: `src/trading_lab/analytics/drawdown.py`. All four functions take `(results: pd.DataFrame, initial_capital: float = 10_000.0)` and return a new `pd.DataFrame`:

| Path function | Summary function | Required source columns | Canonical CLOSED capital |
| --- | --- | --- | --- |
| `calculate_gross_realized_drawdown` | `summarize_gross_realized_drawdown` | `status`, `capital_before`, `capital_after` | Stage 4.6 `capital_after` |
| `calculate_net_realized_drawdown` | `summarize_net_realized_drawdown` | `status`, `capital_before`, `net_capital_after` | Stage 4.7 `net_capital_after` |

Exact path columns, in order: `observation`, `closed_trade_number`, `capital`, `running_peak`, `drawdown`, `drawdown_amount`. The first two use int64; the other four use float64. Output has a RangeIndex. Observation 0 has both ordinals 0, capital/peak equal to explicit initial capital, and both drawdown fields `0.0`. Each CLOSED row adds one point in existing input order, so `N` CLOSED trades produce `N + 1` rows. `capital_before` is a schema guard, never the inferred initial value; callers supply the same initial capital as accounting.

Exact summary columns, in order: `max_realized_drawdown`, `max_realized_drawdown_amount`, both float64. There is one row indexed `GROSS` or `NET`. Running peak is the maximum capital through the current observation; drawdown is `capital / running_peak - 1`, and amount is `capital - running_peak`. Maximum drawdown is the minimum negative decimal drawdown. Exact tied minima select the earliest observation; the reported amount belongs to that same point, which can differ from the minimum currency decline. No rounding, tolerance, or clamping changes the calculation.

Validation requires a DataFrame, unique columns, the source-specific schema even for empty input, and statuses exactly CLOSED/OPEN. Initial capital is independently finite real numeric and strictly positive. CLOSED capital is finite real numeric and non-negative; missing values, bool/np.bool_, strings, complex, and non-finite values are rejected. Negative CLOSED capital is invalid; zero is valid and gives drawdown `-1.0` from a positive peak. Full ledger/capital consistency validation stays upstream. Optional columns do not affect results; no input rows, values, dtypes, columns, or index are modified, sorted, reset, or repaired.

OPEN rows, their missing capital-after values, and entry costs add no point and do not alter realized capital. Empty/OPEN-only inputs contain exactly the initial point and have zero summaries, with no NaN. Flat/increasing capital has zero drawdown; recovery to an earlier peak does not remove historical declines. This is REALIZED-CAPITAL drawdown only: it omits intratrade/unrealized losses and can understate full mark-to-market portfolio drawdown. Notebook 03 now presents these existing helper outputs through the Stage 5.6 integration.

## BTC realized-capital drawdown check

The existing local 8,760-row BTCUSDT hourly snapshot ran through the unchanged EMA20/EMA50 pipeline (50 warm-up candles), ledger, and independent gross/net accounting, then the new drawdown paths/summaries. Initial capital was 10,000 USDT; NET used `fee_rate=0.001` and `slippage_rate=0.0005` as research assumptions only, not current Bybit fees. Drawdowns are negative decimal fractions; amounts/capital use USDT. Values below are rounded for display only.

| Result | GROSS | NET |
| --- | ---: | ---: |
| CLOSED trades | 77 | 77 |
| Path rows including initial capital | 78 | 78 |
| `max_realized_drawdown` | -0.267234254550 | -0.371855332627 |
| `max_realized_drawdown_amount` | -2,672.342545499 | -3,718.553326267 |
| Minimum-drawdown observation | 33 | 66 |
| Minimum-drawdown `closed_trade_number` | 33 | 66 |
| Capital at that observation | 7,327.657454501 | 6,281.446673733 |
| Running peak at that observation | 10,000.000000000 | 10,000.000000000 |
| Final realized capital | 9,641.111388344 | 7,652.530163437 |

The maxima are -26.723425% GROSS and -37.185533% NET on these realized-capital observations. Both final path capitals equal the known final CLOSED accounting values. Removing the final OPEN row leaves each full path and summary identical; that position remains unvalued. Inputs and the raw CSV hash were preserved. Stage 5.6 notebook assertions verified the same references, OPEN exclusion, and preservation; its table and plot read from the existing helpers. These sample-specific results do not establish general strategy quality or full portfolio drawdown.

## BTC CLOSED-trade performance summary

Existing 8,760-row BTCUSDT hourly snapshot; EMA20/EMA50 with 50 warm-up candles and initial capital 10,000 USDT. NET rates are research assumptions only: 0.10% fee and 0.05% adverse slippage per side, not current Bybit fees. Return/rate values below are decimal fractions; PnL/expectancy use USDT. Values are rounded for display; implementation uses unrounded inputs.

| Metric (exact output order) | GROSS | NET |
| --- | ---: | ---: |
| `closed_trade_count` | 77 | 77 |
| `winning_trade_count` | 20 | 20 |
| `losing_trade_count` | 57 | 57 |
| `breakeven_trade_count` | 0 | 0 |
| `win_rate` | 0.259740259740 | 0.259740259740 |
| `loss_rate` | 0.740259740260 | 0.740259740260 |
| `breakeven_rate` | 0.000000000000 | 0.000000000000 |
| `average_trade_return` | 0.000070588288 | -0.002925128404 |
| `median_trade_return` | -0.008735290732 | -0.011704629367 |
| `average_win_return` | 0.038651616726 | 0.035540330361 |
| `average_loss_return` | -0.013466614673 | -0.016421780603 |
| `best_trade_return` | 0.224171061391 | 0.220504050556 |
| `worst_trade_return` | -0.043755772679 | -0.046620207277 |
| `total_realized_pnl` | -358.888611656 | -2,347.469836563 |
| `expectancy_pnl` | -4.660891060 | -30.486621254 |
| `profit_factor` | 0.945165760246 | 0.675088667158 |

The final OPEN trade is excluded and unvalued. The positive gross arithmetic average return does not imply a positive compounded result; total PnL follows actual compounded capital. These metrics describe this sample and do not establish general strategy quality or future profit.

## Environment status

- The parent workspace's `.venv/` uses Python 3.9.6. pandas 2.3.3, NumPy 2.0.2, and Matplotlib 3.9.4 were installed for this task. requests and JupyterLab were already available.
- All notebook code cells executed successfully using this virtual environment; the editor's selected kernel was not changed.
- The existing Python/LibreSSL environment emits an urllib3 compatibility warning. Public API calls succeeded; the warning was not suppressed, and interpreter migration is outside this task.
- Git repository root: `/Users/romankondratenko/trading-lab/Trading Lab`.
- Branch: `main`, tracking `origin/main`. Initial commit: `ff57150` (`Initialize Trading Lab project`), pushed successfully to GitHub.
- Remote repository: [puckmandestroyer/trading-lab](https://github.com/puckmandestroyer/trading-lab).

## Current focus

Stage 8 — Strategy Robustness and Stage 8.8 — Final Stage 8 Audit + Docs are COMPLETE. Current focus: Stage 9 — Bybit Demo Exchange Adapter, awaiting explicit owner approval; NOT STARTED.

Decision 012 and all milestones 8.1–8.8 passed the final audit. Stages 5–7, fixed allocation, reserve-aware equity, regression references, and notebooks 01–06 are preserved. Stage 9 will connect the existing architecture to Bybit demo trading infrastructure through an isolated exchange adapter; it requires separate explicit approval.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Portfolio/multi-asset allocation, shorts, leverage, and risk-based sizing beyond the generic LONG/FLAT fixed-fraction single-position model.
- Exchange-specific or variable transaction-cost models.
- Drawdown duration/recovery and subsequent portfolio metrics.
- Additional reusable strategies beyond the EMA crossover strategy.
- Performance analytics beyond the 16 CLOSED-trade summary metrics, separate realized-capital drawdown, ledger-based duration/exposure, candle-level equity, candle-close portfolio drawdown, the aligned Buy-and-Hold comparison, and time-based returns/Sharpe/Sortino with support volatility/downside metrics; broader multi-strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Broader centralized risk controls beyond fixed capital allocation.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Stage 9 — Bybit Demo Exchange Adapter, only after explicit owner approval, connecting the existing architecture to Bybit demo trading infrastructure through an isolated exchange adapter.

Stage 9 has not started. No Stage 9 design or implementation is included in this closure.

## Backtesting execution contract

- The default EMA strategy uses 50 initialization-only candles, with eligibility from candle 51. Warm-up belongs to each strategy; the generic engine has no warm-up requirement.
- Signals use only completed candle data. `signal_time` is the candle opening timestamp plus one hour.
- `desired_position` is research intent: 0 wants flat and 1 wants long. Entries require previous state 0; exits require previous state 1; HOLD preserves state.
- The first model executes a valid event from candle N at candle N+1's OPEN: `execution_time = timestamp[N+1]`, `execution_price = open[N+1]`. Same-candle-close fills are forbidden.
- `signal_time` marks information availability; `execution_time` marks the simulated action. For continuous hourly data they share the same boundary timestamp, while completion and signal availability precede execution conceptually.
- Initial simulated `executed_position = 0`. An executable LONG_ENTRY requires flat state and changes 0 → 1; LONG_EXIT requires long state and changes 1 → 0. HOLD creates no execution and leaves state unchanged. Invalid executed-state transitions must be rejected.
- A final-candle signal can change desired state but cannot execute without a next candle. Do not invent a price or force a terminal entry/exit.
- `executed_position` is now calculated in memory by the backtest helper, independently of `desired_position`. Row N records the state after any prior signal fills at N's OPEN; N's own signal cannot change that row's executed state.
- `execution_time` and `execution_price` are stored on the source signal row, not the receiving candle row. A final row can receive the prior row's fill while its own event remains unexecuted. HOLD has no execution metadata, even when a preceding event changes state at that candle's OPEN.
- The reusable generic LONG/FLAT single-position backtest pipeline composes canonical validation, next-OPEN execution, the trade ledger, and independent GROSS/NET accounting. Cost adjustments preserve recorded ledger prices and execution. Existing equity/analytics helpers compose downstream, including OPEN-position marks; persistence and broader portfolio allocation remain unimplemented.
- See `decisions/002_backtest_execution_contract.md` for definitions, causal ordering, and acceptance cases A–G, now covered by synthetic tests.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

Stage 2 volatility uses sample standard deviation (`ddof=1`) of hourly returns over trailing 24/168-observation windows and is not annualized. First-return and rolling-window NaNs are expected warm-up values. Drawdown uses candle closes and excludes intrahour lows; the index is BTC buy-and-hold price analysis, not a bot backtest.

Stage 3.1 keeps `ewm(span=20/50, adjust=False)` with the first close as the seed. The 50-candle warm-up is a research convention, not an EWM mathematical requirement or a guarantee that seed effects have disappeared. No entry is synthesized merely because warm-up ends in a bullish regime; the flat strategy waits for a new bullish crossover. `desired_position` is not an executed position.

The reusable EMA strategy expects hourly candle-opening timestamps and returns signal availability one hour later. It validates datetime order/uniqueness, finite positive numeric closes, and positive integer parameters with `fast_span < slow_span`. Full OHLCV and hourly continuity validation remain upstream. Default parameters preserve Stage 3.1; custom spans and warm-up are supported but have not been optimized. All derived columns remain in memory; no processed dataset or persistence is introduced.

The execution helper requires pandas datetime timestamps with continuous one-hour spacing; it preserves timezone semantics and does not sort or fill gaps. It validates allowed signals, state transitions, and finite positive OPEN prices used for fills. Full OHLCV validation remains upstream. It does not enforce a strategy warm-up or read optional `desired_position`/`signal_time` columns; it executes only supplied events.

The generic pipeline delegates canonical validation, execution, ledger construction, and independent GROSS/NET accounting to existing components, adds alignment checks, and returns in-memory results only. It supports one LONG/FLAT position with fixed-fraction allocation, defaulting to full allocation; portfolio/multi-asset allocation, shorts, leverage, risk-based sizing, live/demo exchange runtime, and multiple autonomous bots remain unimplemented. `desired_position` is intent after a completed candle; `executed_position` is the state held during that candle after any previous signal fills at its OPEN. They legitimately differ on entry/exit signal rows. Prefix stability excludes execution metadata for a former final-row event that gains a next candle; all earlier rows and shared-prefix strategy/position values remain unchanged.

The ledger consumes the full candle state table starting flat and validates its recorded fills; it does not sort malformed input, calculate fills, or value an open trade. It preserves datetime timezone semantics and returns an empty typed ledger when no entry actually executes. The candle pipeline table and trade ledger remain separate in-memory outputs. The review notebook saves displayed excerpts and plots, but exports no dataset or separate report.

Accounting assumes consecutive trade IDs from 1, chronological non-overlapping trades, and at most one final OPEN trade. It never repairs or sorts invalid ledgers. CLOSED exit prices must be strictly positive; calculated results must remain finite with non-negative capital, and impossible quantity overflow/underflow raises an error. Floating-point tolerance is used for arithmetic checks. `trade_return` is a decimal return for one CLOSED trade; `gross_pnl` is realized PnL before costs. Compounded capital after closed trades is not a mark-to-market equity curve, and OPEN trades have no realized result or valuation.

Cost-aware accounting reuses the unchanged gross helper's ledger/capital validation, including its numerical limits, then independently sizes and compounds net results. Rates must be finite real numbers in `[0, 1)`; bools are rejected. Effective prices, entry sizing, and calculated amounts must be representable as finite floats; depleted capital cannot finance another trade. Rates are fixed research assumptions, with no exchange-specific fee tiers, minimum order sizes, or rounding. Cost-aware `gross_pnl` uses recorded prices with the cost-sized quantity, so it is not the separate Stage 4.6 simulation. OPEN `total_fees` stays missing because the round trip is incomplete; its known entry fee is reported separately.

The backtest review notebook observes the fixed EMA20/EMA50, 50-candle-warm-up sample without parameter optimization, out-of-sample testing, or walk-forward validation. Its realized-capital and realized-drawdown plots use completed trade number; the separate Stage 5.12 MTM plot uses valuation time and observes within-trade CLOSE movements, including final OPEN value. TIME remains ledger-based holding-time/exposure. No general conclusion about strategy quality follows from this single sample.

Decision 003 is implemented by the Stage 5.2 summary helpers. Arithmetic average trade return is distinct from compounded strategy return. Quote-currency expectancy describes this sample, not future profit. NaN and +infinity are intentional for documented undefined/unbounded cases. These summaries aggregate existing accounting outputs; full ledger/capital consistency validation stays upstream. Decision 004 is implemented separately by the Stage 5.5 drawdown helpers, using only explicit initial capital and CLOSED capital-after observations, and presented in notebook 03 by Stage 5.6. They can miss losses while trades are open and understate full mark-to-market drawdown. Candle-close portfolio drawdown, Buy-and-Hold comparison, and decision 009 time-based returns/Sharpe/Sortino with explicit support volatility/annualization are now available separately. Decision-010 strategy-output validation is implemented; Stage 8.2 provides independent IS/OOS composition, Stage 8.3 descriptive grids, Stage 8.4 local parameter variation, and Stage 8.5 independent expanding walk-forward research. Stage 8.6 adds neutral segment/window diagnostic tables and finite-only descriptive test-window statistics. Statistical robustness conclusions remain unestablished.

Decision 005 is implemented by the Stage 5.8 ledger-based time helpers, independently of accounting, and presented in notebook 03 by Stage 5.9. OPEN exclusion from realized PnL/drawdown does not imply exclusion from observed time in market. Exposure is binary holding time for the current single-position, non-overlapping ledger. Overlapping/multi-position, leverage/size-weighted, gross/net, and short exposure remain outside this contract; no market-value risk metric is introduced.

Decision 006 is implemented by `analytics/equity.py` and presented in notebook 03 by Stage 5.12. Stage 7 extends its original all-in model with fixed partial allocation and reserve cash. The long-only single-asset model still excludes shorts, multi-asset/multi-position allocation, leverage, funding/borrow interest, dynamic fees, liquidation value, and position-size-weighted exposure. Decision 007 is implemented by `analytics/portfolio_drawdown.py` and presented in notebook 03 by Stage 5.15. Decision 009 now supplies time-based equity returns, Sharpe/Sortino, and their support volatility/downside measures. Drawdown duration/recovery, further equity-return metrics, CAGR/Calmar, alpha/beta, intrabar MAE/MFE, and further robustness diagnostics remain deferred. Independent IS/OOS composition is available through Stage 8.2, with independent expanding walk-forward research through Stage 8.5 and downstream descriptive diagnostics through Stage 8.6. The CLOSE path can still miss intrabar risk; no continuous-time or tick-level drawdown claim is supported.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
