# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 7 — Risk Manager + Position Sizing.

Stage 7.2 — Position Sizing Core completed.

Stage 7.1 — Risk & Position Sizing Contract remains Accepted as Decision 011.

Stage 6 — Generic Backtesting Engine remains COMPLETE at `df72973de837ecbd4ee81f4bdaf77efd74730a56`.

Stage 5 — Analytics remains COMPLETE and frozen at `a3fde091be234fd78d216f6338752a810fa117f0` (`Complete Stage 5 analytics report`).

## Completed

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

## Risk and position-sizing contract

[Decision 011](decisions/011_risk_and_position_sizing.md) is Accepted. Stage 7's only planned policy is a scalar fixed `position_fraction` in `0 < position_fraction <= 1`, default `1.0`, constant for one backtest run. Reject zero, negatives, values above 1, Python/NumPy bools, non-finite values, strings, None, complex values, and non-scalars without coercion or clamping. No leverage, borrowing, or zero-allocation trade veto is introduced.

Strategy continues to decide Decision-010 intent. Risk determines the allowed budget from CURRENT portfolio capital at each actual executed entry: `position_budget = capital_before * position_fraction`; reserve is `capital_before - position_budget`. Accounting converts that budget into quantity using raw price for GROSS and the existing effective-price/entry-fee self-financing rules for NET. Risk does not calculate quantity, costs, or PnL. Execution timing, prices, signals, and ledger pairing remain unchanged.

Reserve belongs to the same portfolio. Future MTM equity must include reserve cash plus marked position value: 10,000 capital, fraction 0.50, entry 100, and mark 110 gives quantity 50, reserve 5,000, and equity 10,500 without costs. Next-entry budgets compound from current capital, so 10,500 at fraction 0.50 permits 5,250. OPEN trades retain known entry/budget/reserve information with missing realized exit results; final unexecuted entries allocate nothing, and final unexecuted exits leave positions OPEN. Allocation fraction is distinct from time exposure and is not a fixed loss-at-risk percentage.

Default fraction 1.0 must reproduce Stage 6 exactly, including quantities, independent GROSS/NET accounting, equity, and downstream analytics, without loosening existing tolerances. Frozen BTC reference values are recorded in Decision 011. Prefer existing accounting schemas and derive reserve safely from canonical entry accounting; any necessary new field requires an explicit reviewed decision.

Stage 7.2 implements only `calculate_position_budget(capital_before, position_fraction=1.0) -> float` under `src/trading_lab/risk/position_sizing.py`. It is not called by accounting or backtesting yet. A future 7.6 pipeline parameter will forward the fraction to risk/accounting; current accounting/pipeline signatures and equity remain unchanged. Existing production modules/tests, decisions 001–011, notebooks, dependencies, and data are preserved. The current full suite is 597 tests; no notebooks were executed.

## Position sizing core

`src/trading_lab/risk/position_sizing.py` exposes `calculate_position_budget(capital_before, position_fraction=1.0) -> float`. The pure helper returns only `capital_before * position_fraction`, using the caller's current total portfolio capital: 10,000 at 0.50 gives 5,000, while 10,500 at 0.50 gives 5,250. It calculates no quantity, costs, reserve cash, PnL, or equity and imports only standard-library `math` and `numbers`.

Capital must be a positive finite real scalar; the fraction must satisfy `0 < position_fraction <= 1` and defaults to 1.0. Python/NumPy integer and floating scalars are accepted and the result is always a positive finite Python float. Python/NumPy bools, non-scalars, strings, None, complex values, and non-finite/nonpositive values raise ValueError. Fractions above 1 are rejected using the original numeric value, even if float conversion rounds them to 1.0. Unsafe conversion overflow/underflow and multiplication underflow to zero are rejected; there is no parsing, clamping, epsilon, minimum allocation, leverage, or veto.

All 35 new methods in `tests/test_position_sizing.py` pass. The full suite passed once with 597 tests (562 unchanged baseline + 35 new), zero failures, errors, or skips. Tests cover current-capital examples, Python/NumPy scalar types, invalid inputs, exact boundaries, finite float limits, conversion/product underflow, output type, and repeatability. A valid finite float capital multiplied by a fraction at most 1 cannot overflow; conversion overflow is rejected and the final budget still has an explicit finite/positive check.

No accounting, equity, or pipeline integration is implemented. All existing production modules/tests, `risk/__init__.py`, decisions 001–011, notebooks, requirements, and raw data are unchanged; no notebook was executed. Stage 6 remains COMPLETE. Stage 7.3 — GROSS Accounting Integration awaits explicit owner approval and has not started.

## Accepted Stage 7 roadmap

| Milestone | Status |
| --- | --- |
| 7.1 — Risk & Position Sizing Contract | Completed; documentation/architecture only. |
| 7.2 — Position Sizing Core | Completed; standalone budget helper only. |
| 7.3 — GROSS Accounting Integration | Awaits explicit owner approval; not started. |
| 7.4 — NET Accounting Integration | Deferred; not started. |
| 7.5 — MTM Equity / Reserve Cash | Deferred; not started. |
| 7.6 — Generic Backtest Integration | Deferred; not started. |
| 7.7 — Exact Regression + Analytics Compatibility | Deferred; not started. |
| 7.8 — Position Sizing Notebook | Deferred; not started. |
| 7.9 — Final Stage 7 Audit + Docs | Deferred; not started. |

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

Stage 6.7 changes documentation only. No production code, tests, notebooks, decisions, dependencies, raw data, or financial formulas changed. Stage 7.1 has accepted the sizing contract; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## Generic backtest notebook

[Notebook 04](notebooks/04_generic_backtest_engine.ipynb) demonstrates candles → strategy-specific intent → the Decision-010 contract → `run_backtest_pipeline(...)` → `execution`, `trades`, `gross_results`, and `net_results`. Existing EMA20/50 is one intent producer; a five-candle manually supplied contract example reaches the same shared engine without EMA calculations or a new production strategy. Small views explain availability, desired versus executed state, next-OPEN fills, trade pairing, and independent GROSS/NET sizing/compounding.

The notebook loads only the existing frozen local 8,760-candle BTC snapshot through `load_ohlcv_csv(...)`, checking its canonical window, first raw OPEN, and accepted SHA-256. It has no downloader or external API calls and fails clearly when the file is absent. Frozen sanity checks preserve 78 ENTRY / 77 EXIT signals, 78 trades (77 CLOSED / one OPEN), first fill at `2025-10-13 03:00 UTC` for 115,332.3, and last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 USDT.

Existing equity helpers compose downstream; the generic engine still stops at accounting. Each path has 8,761 observations, ending at GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT. The final OPEN holding is marked without liquidation. Modeled fee/slippage rates remain frozen research assumptions, not current exchange fees. The notebook copies no production financial formulas; Stage 6.5 remains the authoritative exact compatibility regression.

Executed top to bottom using the existing parent-workspace `.venv/`: 23 total cells, 11 code, 12 Markdown, sequential execution counts 1–11, zero saved errors, and one rendered plot. All intended outputs are saved; the plot was visually inspected. Candles, strategy output, and raw bytes are preserved. The full unchanged suite passed once with 562 tests; no new tests, dependencies, or production modules were added or changed. Notebooks 01–03 and all existing `.py` placeholders are unchanged; notebook 03 was not executed. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## EMA exact regression / compatibility

Stage 6.5 is a regression gate only. The canonical local `data/raw/BTCUSDT_1h.csv` loads through `load_ohlcv_csv(...)` with the explicit hourly window `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. Before EMA calculations, the new regression module checks the existing frozen SHA-256 from notebook 03, 8,760 rows, first/last timestamps, and first raw OPEN 114,051.1. No download, network call, or raw-file modification occurs. Established local-snapshot test policy permits skipping only when the file is absent on another clone; this environment ran all 16 methods with zero skips.

Using unchanged EMA20/EMA50 and 50 initialization candles, separately generated strategy output exactly matches the legacy combined frame's strategy subset. `run_execution_pipeline(...)` and `run_backtest_pipeline(...)["execution"]` exactly match its six execution columns; generic ledger and independent GROSS/NET accounting exactly match the direct legacy helper path. Frame checks use `check_exact=True`; frozen scalar checks retain notebook 03's established tolerances. Full outputs are cached once per test class.

Bullish/bearish crossovers remain 78/78; ENTRY/EXIT signals and fills remain 78/77; final desired position remains 1. First ENTRY intent is `2025-10-13 02:00 UTC`, filled at the next OPEN `2025-10-13 03:00 UTC` for 115,332.3. The ledger remains 78 trades: 77 CLOSED and one final OPEN with missing exit fields and entry-only accounting. No terminal liquidation is introduced.

Last CLOSED realized capital remains GROSS 9,641.111388344 / NET 7,652.530163437 USDT. Existing equity helpers produce 8,761 observations and final OPEN marks of GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT, exactly matching legacy equity paths. Existing CLOSED-trade summaries, realized/portfolio drawdown, duration/exposure, hourly returns, Sharpe/Sortino, and Buy-and-Hold comparison pass frozen Stage 5 references. NET rates 0.001 fee / 0.0005 adverse slippage remain research assumptions, not current exchange fees.

All 16 Stage 6.5 methods and all 562 tests pass. Candles, strategy output, accounting/equity sources, and raw bytes are preserved. All production Python modules, the existing EMA compatibility function, old tests, decisions 001–010, earlier notebooks, and dependencies are unchanged. Stage 6.6 adds the separate notebook 04 demonstration above. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## Generic end-to-end backtest pipeline

`run_backtest_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0) -> dict`

Any valid Decision-010 strategy output can pass through validation/execution, the trade ledger, and independent GROSS/NET accounting. The function owns call order only: `run_execution_pipeline(...)` → `build_trade_ledger(...)` → `calculate_trade_results(...)` → `calculate_trade_results_with_costs(...)`. Both accounting functions receive the same ledger and unchanged parameters; NET is not derived from the returned GROSS results. Existing helpers own validation, timing, trade pairing, financial mathematics, and output schemas.

The new dictionary contains exactly four separate DataFrames: `execution`, `trades`, `gross_results`, and `net_results`, each the corresponding helper's exact output. Strategy diagnostics are ignored; inputs remain unchanged. No strategy generation, analytics summary, equity path, or mark-to-market valuation is included.

An executed entry may remain OPEN with entry-only accounting and missing exit/realized fields. A final unexecuted ENTRY creates no trade; a final unexecuted EXIT leaves the existing trade OPEN. No terminal fill or close is forced. All-HOLD and typed empty inputs retain helper-defined schemas and dtypes.

All 15 new Stage 6.4 methods pass; that milestone's full suite passed with 546 tests. These tests use only synthetic data, including a non-EMA CLOSED trade at recorded prices 100 → 110, multiple trades with independent compounding, zero/nonzero cost parameters, exact four-frame parity, call order, error propagation, preservation, and index/timezone checks. The existing EMA pipeline remains internally unchanged. Stage 6.5 now proves exact EMA compatibility on the frozen BTC snapshot; notebooks 01–03 were neither modified nor executed. Stage 5 remains COMPLETE and frozen. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## Generic execution pipeline

`src/trading_lab/backtest/pipeline.py` now exposes:

`run_execution_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

The function calls `validate_strategy_output(...)` before `apply_next_open_execution(...)`. The validator owns intent/alignment/availability; execution owns continuous hourly spacing, valid fill OPEN prices, next-OPEN timing, executed state, and final-row no-fill rules. No indicator logic, warm-up rule, close requirement, or duplicated execution algorithm is added.

Candles supply `timestamp` and authoritative market `open`. Only validated `signal` is transferred into a deep candle copy, replacing any unrelated candle signal locally. Arbitrary strategy diagnostics, including `open` or execution-like names, are ignored and not merged into execution output. Both source DataFrames remain unchanged; ordinary scalar edits to the result do not affect them.

The return is the existing execution helper's exact schema/order/dtypes/index: `timestamp`, `open`, `signal`, `execution_time`, `execution_price`, `executed_position`. Reused alignment checks verify row count, index, and timestamps; additional postconditions verify unchanged validated signals and market OPEN values. Direct-helper parity, non-RangeIndex/duplicate-label alignment, typed empty output, and naive/aware clock checks pass. Valid final entries/exits remain unfilled without forced closing; a newly appended next candle may populate former-final fill metadata without changing earlier rows or state during that candle.

All 25 Stage 6.3 test methods pass; that milestone's full suite passed once with 531 tests (506 earlier + 25 new). `run_ema_execution_pipeline(...)` is not refactored into a wrapper and its source is unchanged. This execution-only API stops before the ledger; Stage 6.4 adds the separate ledger/accounting composition API above. Analytics remain separate downstream components. Stage 5 remains COMPLETE and frozen; notebooks 01–03 were neither modified nor executed. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## Generic strategy output validation

Decision 010 is implemented by `src/trading_lab/backtest/strategy_validation.py`:

`validate_strategy_output(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

Candles need only `timestamp`; strategy output requires `timestamp`, `signal_time`, `signal`, and `desired_position`. Both DataFrames need unique column names. Row counts, indexes (`Index.equals`), and timestamp Series (`Series.equals`) must match exactly. Timestamps must already be non-missing, unique, chronological pandas datetimes; compatible datetime/timezone representation is preserved. Non-RangeIndex and duplicate index labels are valid when aligned. No parsing, sorting, repair, OHLCV checks, candle-spacing enforcement, or warm-up rules are added.

Every signal_time equals its timestamp plus one elapsed hour, including HOLD/final rows and DST transitions. Start desired state FLAT (0); LONG_ENTRY changes 0 → 1, LONG_EXIT changes 1 → 0, and HOLD preserves state. Require Python/NumPy integer 0/1; reject bools, floats, strings, missing values, invalid signals, and inconsistent transitions with ValueError. Valid final-row events and aligned empty typed frames remain valid intent. Causality stays the strategy's responsibility.

The return value is a new full DataFrame copy: canonical and diagnostic columns, values, dtypes, index, and column order are unchanged. Both inputs are preserved; ordinary scalar output edits do not mutate the source. Synthetic EMA output passes without modifying EMA logic. No execution helper is called and no fills or financial fields are added. `run_execution_pipeline(...)` now delegates to this validator; the existing EMA pipeline remains unchanged.

All 48 Stage 6.2 test methods pass; that milestone's full suite passed once with 506 tests (458 earlier + 48 new). Stage 5 remains COMPLETE and frozen, including notebook 03 (104 cells, 51 code / 53 Markdown, seven plots), which was neither modified nor executed. Stage 6.4 now composes execution, ledger, and independent accounting. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

## Final Stage 5 analytics report

Notebook 03 brings together CLOSED-trade performance, realized-capital drawdown, duration/exposure, candle-level MTM equity, candle-close portfolio drawdown, Buy-and-Hold comparison, time-based returns, volatility, and Sharpe/Sortino. Its final report reads existing outputs for setup, a seven-row/four-portfolio comparison, EMA behavior, costs, benchmark opportunity cost, drawdown, time, and risk-adjusted interpretation. Explicit limitations cover this single BTC sample, fixed modeled costs, hourly marks, final OPEN positions, and absent out-of-sample validation.

The final audit checks the 8,760-candle snapshot, 78 executed entries / 77 exits, 77 CLOSED / one final OPEN trade, all four 8,761-observation equity paths and 8,760-return clocks, financial/risk/time references, raw CSV hash, and preservation of 31 report-source DataFrames. All seven existing plot sources/images and earlier calculations are preserved. The notebook has 104 cells (51 code / 53 Markdown), sequential execution, and no saved errors. All 458 existing tests pass; Stage 5.18 adds no tests or metric logic. Production code/tests, decisions, notebooks 01/02, raw data, and dependencies are unchanged.

Stage 5 — Analytics remains complete and frozen at the committed Stage 5.18 baseline. Stage 6.5 proves exact EMA compatibility through generic execution, ledger, accounting, and existing analytics; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

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

Notebook 03 snapshots all four equity sources before calling the reusable helpers, displays one compact eight-row comparison and representative first/flat/invested/final return previews, and retains one transparent NET hourly-return scatter plot. Its final Stage 5.18 report brings the notebook to 104 cells (51 code / 53 Markdown), executed sequentially without errors, with seven plots and all seven prior plot sources/images unchanged. Assertions check all 8,760 periods, full clocks, spot formulas, cash zeros, final OPEN marks, actual summary references, all four equity sources, candles, and raw CSV hash. The 61 Stage 5.17 tests cover these contracts, synthetic conventions/degenerate cases, strict validation/DST/preservation/causal prefixes, and actual EMA/benchmark integration. All 458 tests pass. Stage 5.18 preserves production code/tests, decisions, notebooks 01/02, raw data, and dependencies; Stage 5 remains complete; Stage 6.5 proves exact EMA regression through the generic path; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

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

Notebook 03 uses helper outputs for the tables and existing equity-comparison plot, with reference assertions for rows, full valuation-time alignment, first-OPEN timing, final OPEN marks, benchmark drawdowns, unchanged EMA/candle inputs, and raw CSV hash. The final Stage 5.18 report preserves the benchmark and time-based analytics sections: 104 cells (51 code / 53 Markdown), seven plots, sequential execution, no saved errors, and all seven prior plot sources/images unchanged. The 38 benchmark tests include exact schemas, delegated sizing/costs, paid-once/no-exit behavior, zero-cost equality, validation, input/output independence, causal prefixes, existing drawdown integration, and actual BTC alignment. All 458 tests pass, including these unchanged 38 benchmark tests. Decision 009 supplies time-based returns and Sharpe/Sortino; Stage 6.4 provides generic execution/ledger/accounting composition; analytics remain separate, Stage 6.5 exact EMA regression is complete, and Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 awaits explicit owner approval and has not started.

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

[Decision 006](decisions/006_candle_level_mark_to_market_equity.md) is implemented by `src/trading_lab/analytics/equity.py`. Consume validated market candles with at least `timestamp` (OPEN time) and `close`, plus independent canonical GROSS results from Stage 4.6 `calculate_trade_results(...)` or NET results from Stage 4.7 `calculate_trade_results_with_costs(...)`. Reuse each path's quantity and realized capital without resizing, reconstructing PnL/capital, or rerunning cost formulas; Stage 4.7 `gross_pnl` is not the independent GROSS simulation.

Public functions: `calculate_gross_mark_to_market_equity(candles, gross_results, candle_interval, initial_capital=10_000.0)` and `calculate_net_mark_to_market_equity(candles, net_results, candle_interval, initial_capital=10_000.0)`. Both return new independent path DataFrames. GROSS requires `trade_id`, `status`, `entry_time`, `entry_price`, `exit_time`, `capital_before`, `quantity`, `capital_after`; NET requires `trade_id`, `status`, `entry_time`, `exit_time`, `capital_before`, `quantity`, `effective_entry_price`, `entry_fee`, `net_capital_after`, even for empty input. Wrong accounting sources fail clearly. Initial capital is an independent positive finite real parameter, never inferred; use the same value as accounting.

The required explicit positive fixed `candle_interval` defines `observation_start = first timestamp` and `observation_end = last timestamp + interval`. N contiguous candles give N + 1 observations. Initial observation 0 is immediately before any first-OPEN fill. For each candle: carry state → actual EXIT at its OPEN → actual ENTRY at its OPEN → observe completed CLOSE → mark remaining quantity → record at OPEN timestamp + interval. A preceding CLOSE observation occurs before the next OPEN's fills at the same boundary timestamp. If a future valid ledger shares exit/entry time, EXIT precedes ENTRY; current upstream validation stays unchanged. Fills must match supplied candle OPENs; the exclusive window end is not an extra OPEN.

Both paths mark at the same raw market CLOSE. Current scope is one asset, long-only spot, one position, no leverage, all-in entry allocation, fixed NET cost assumptions, and fixed-interval candle-CLOSE marking. After entry, cash is zero and quantity is canonical; `position_value = quantity * close` and `equity = cash + position_value`. GROSS price-based `unrealized_pnl = quantity * (close - entry_price)`; NET uses `effective_entry_price` instead and excludes the already-paid entry fee. NET entry slippage/fee already affect canonical basis/quantity; do not charge entry fee again. Conceptually `quantity * effective_entry_price = capital_before - entry_fee`; at that basis mark, NET unrealized PnL is zero while equity is lower than capital before by the paid fee.

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

Stage 7.3 — GROSS Accounting Integration awaits explicit owner approval and has not started.

Stage 7.2's scalar budget helper is complete and independently tested. Current production accounting/equity/backtesting still uses the unchanged Stage 6 all-in model.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Portfolio/multi-asset allocation, shorts, leverage, and risk-based sizing beyond the generic LONG/FLAT all-in single-position model.
- Exchange-specific or variable transaction-cost models.
- Drawdown duration/recovery and subsequent portfolio metrics.
- Additional reusable strategies beyond the EMA crossover strategy.
- Performance analytics beyond the 16 CLOSED-trade summary metrics, separate realized-capital drawdown, ledger-based duration/exposure, candle-level equity, candle-close portfolio drawdown, the aligned Buy-and-Hold comparison, and time-based returns/Sharpe/Sortino with support volatility/downside metrics; broader multi-strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Position-sizing integration into accounting, equity, and generic backtesting; broader centralized risk controls.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Stage 7.3 — GROSS Accounting Integration, only after explicit owner approval. Integrate the accepted budget policy into GROSS accounting; NET, equity, and generic pipeline integration remain later milestones.

Stage 7.3 has not started.

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

The generic pipeline delegates canonical validation, execution, ledger construction, and independent GROSS/NET accounting to existing components, adds alignment checks, and returns in-memory results only. It supports one LONG/FLAT all-in position; portfolio/multi-asset allocation, shorts, leverage, integrated capital-allocation sizing, live/demo exchange runtime, and multiple autonomous bots remain unimplemented. `desired_position` is intent after a completed candle; `executed_position` is the state held during that candle after any previous signal fills at its OPEN. They legitimately differ on entry/exit signal rows. Prefix stability excludes execution metadata for a former final-row event that gains a next candle; all earlier rows and shared-prefix strategy/position values remain unchanged.

The ledger consumes the full candle state table starting flat and validates its recorded fills; it does not sort malformed input, calculate fills, or value an open trade. It preserves datetime timezone semantics and returns an empty typed ledger when no entry actually executes. The candle pipeline table and trade ledger remain separate in-memory outputs. The review notebook saves displayed excerpts and plots, but exports no dataset or separate report.

Accounting assumes consecutive trade IDs from 1, chronological non-overlapping trades, and at most one final OPEN trade. It never repairs or sorts invalid ledgers. CLOSED exit prices must be strictly positive; calculated results must remain finite with non-negative capital, and impossible quantity overflow/underflow raises an error. Floating-point tolerance is used for arithmetic checks. `trade_return` is a decimal return for one CLOSED trade; `gross_pnl` is realized PnL before costs. Compounded capital after closed trades is not a mark-to-market equity curve, and OPEN trades have no realized result or valuation.

Cost-aware accounting reuses the unchanged gross helper's ledger/capital validation, including its numerical limits, then independently sizes and compounds net results. Rates must be finite real numbers in `[0, 1)`; bools are rejected. Effective prices, entry sizing, and calculated amounts must be representable as finite floats; depleted capital cannot finance another trade. Rates are fixed research assumptions, with no exchange-specific fee tiers, minimum order sizes, or rounding. Cost-aware `gross_pnl` uses recorded prices with the cost-sized quantity, so it is not the separate Stage 4.6 simulation. OPEN `total_fees` stays missing because the round trip is incomplete; its known entry fee is reported separately.

The backtest review notebook observes the fixed EMA20/EMA50, 50-candle-warm-up sample without parameter optimization, out-of-sample testing, or walk-forward validation. Its realized-capital and realized-drawdown plots use completed trade number; the separate Stage 5.12 MTM plot uses valuation time and observes within-trade CLOSE movements, including final OPEN value. TIME remains ledger-based holding-time/exposure. No general conclusion about strategy quality follows from this single sample.

Decision 003 is implemented by the Stage 5.2 summary helpers. Arithmetic average trade return is distinct from compounded strategy return. Quote-currency expectancy describes this sample, not future profit. NaN and +infinity are intentional for documented undefined/unbounded cases. These summaries aggregate existing accounting outputs; full ledger/capital consistency validation stays upstream. Decision 004 is implemented separately by the Stage 5.5 drawdown helpers, using only explicit initial capital and CLOSED capital-after observations, and presented in notebook 03 by Stage 5.6. They can miss losses while trades are open and understate full mark-to-market drawdown. Candle-close portfolio drawdown, Buy-and-Hold comparison, and decision 009 time-based returns/Sharpe/Sortino with explicit support volatility/annualization are now available separately. Decision-010 strategy-output validation is implemented; statistical strategy validation, including out-of-sample and walk-forward methods, remains deferred.

Decision 005 is implemented by the Stage 5.8 ledger-based time helpers, independently of accounting, and presented in notebook 03 by Stage 5.9. OPEN exclusion from realized PnL/drawdown does not imply exclusion from observed time in market. Exposure is binary holding time for the current single-position, non-overlapping ledger. Overlapping/multi-position, leverage/size-weighted, gross/net, and short exposure remain outside this contract; no market-value risk metric is introduced.

Decision 006 is implemented by `analytics/equity.py` and presented in notebook 03 by Stage 5.12. Its all-in long-only single-asset model excludes shorts, partial/multi-asset/multi-position allocation, leverage, funding/borrow interest, dynamic fees, liquidation value, and position-size-weighted exposure. Decision 007 is implemented by `analytics/portfolio_drawdown.py` and presented in notebook 03 by Stage 5.15. Decision 009 now supplies time-based equity returns, Sharpe/Sortino, and their support volatility/downside measures. Drawdown duration/recovery, further equity-return metrics, CAGR/Calmar, alpha/beta, intrabar MAE/MFE, out-of-sample testing, and walk-forward validation remain deferred. The CLOSE path can still miss intrabar risk; no continuous-time or tick-level drawdown claim is supported.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
