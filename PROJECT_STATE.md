# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 5.6 — Realized-Capital Drawdown Notebook Integration (completed).

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
- All 216 existing unit tests passed; no new unit tests or dependencies were needed. Production modules including `drawdown.py` and `trade_metrics.py`, all tests, decisions, notebooks 01/02, and raw BTC CSV remain byte-identical. No new financial metric formulas were introduced; Stage 5.7 has not started.

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

Stage 5.6 presents the existing Stage 5.5 gross/net realized-capital paths and summaries in notebook 03, with a separate comparison table, one new plot, beginner explanations, and integration assertions. All 25 notebook code cells and all 216 unit tests pass. Production financial logic is unchanged. Stage 5.7's duration/exposure contract awaits approval.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Full backtesting engine and candle-level portfolio/equity simulation.
- Exchange-specific or variable transaction-cost models and unrealized/mark-to-market PnL.
- Additional reusable strategies beyond the EMA crossover strategy.
- Performance analytics beyond the 16 CLOSED-trade summary metrics and separate realized-capital drawdown, and strategy comparison.
- Live/demo execution and exchange integration.
- Multiple autonomous bot instances and order management.
- Centralized risk engine.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Proposed Stage 5.7 — Trade Duration and Exposure Contract: define entry/exit timestamp conventions, treatment of the final OPEN position, the observation window, and the time-in-market denominator before implementation. No duration/exposure calculations or contract definitions have been added. Do not start Stage 5.7 until the owner approves it.

No processed dataset or reusable preprocessing module is needed yet. Keep strategy generation and execution separate; no strategy classes or framework are needed.

## Backtesting execution contract

- The first 50 candles are initialization-only; no events occur in them, and eligibility starts on candle 51.
- Signals use only completed candle data. `signal_time` is the candle opening timestamp plus one hour.
- `desired_position` is research intent: 0 wants flat and 1 wants long. Entries require previous state 0; exits require previous state 1; HOLD preserves state.
- The first model executes a valid event from candle N at candle N+1's OPEN: `execution_time = timestamp[N+1]`, `execution_price = open[N+1]`. Same-candle-close fills are forbidden.
- `signal_time` marks information availability; `execution_time` marks the simulated action. For continuous hourly data they share the same boundary timestamp, while completion and signal availability precede execution conceptually.
- Initial simulated `executed_position = 0`. An executable LONG_ENTRY requires flat state and changes 0 → 1; LONG_EXIT requires long state and changes 1 → 0. HOLD creates no execution and leaves state unchanged. Invalid executed-state transitions must be rejected.
- A final-candle signal can change desired state but cannot execute without a next candle. Do not invent a price or force a terminal entry/exit.
- `executed_position` is now calculated in memory by the backtest helper, independently of `desired_position`. Row N records the state after any prior signal fills at N's OPEN; N's own signal cannot change that row's executed state.
- `execution_time` and `execution_price` are stored on the source signal row, not the receiving candle row. A final row can receive the prior row's fill while its own event remains unexecuted. HOLD has no execution metadata, even when a preceding event changes state at that candle's OPEN.
- A separate trade ledger pairs recorded fills, followed by independent gross and cost-aware CLOSED-trade accounting. Cost adjustments preserve recorded ledger prices and do not change execution. No full backtesting engine, unrealized PnL, candle-level portfolio simulation, or persistence exists yet.
- See `decisions/002_backtest_execution_contract.md` for definitions, causal ordering, and acceptance cases A–G, now covered by synthetic tests.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

Stage 2 volatility uses sample standard deviation (`ddof=1`) of hourly returns over trailing 24/168-observation windows and is not annualized. First-return and rolling-window NaNs are expected warm-up values. Drawdown uses candle closes and excludes intrahour lows; the index is BTC buy-and-hold price analysis, not a bot backtest.

Stage 3.1 keeps `ewm(span=20/50, adjust=False)` with the first close as the seed. The 50-candle warm-up is a research convention, not an EWM mathematical requirement or a guarantee that seed effects have disappeared. No entry is synthesized merely because warm-up ends in a bullish regime; the flat strategy waits for a new bullish crossover. `desired_position` is not an executed position.

The reusable EMA strategy expects hourly candle-opening timestamps and returns signal availability one hour later. It validates datetime order/uniqueness, finite positive numeric closes, and positive integer parameters with `fast_span < slow_span`. Full OHLCV and hourly continuity validation remain upstream. Default parameters preserve Stage 3.1; custom spans and warm-up are supported but have not been optimized. All derived columns remain in memory; no processed dataset or persistence is introduced.

The execution helper requires pandas datetime timestamps with continuous one-hour spacing; it preserves timezone semantics and does not sort or fill gaps. It validates allowed signals, state transitions, and finite positive OPEN prices used for fills. Full OHLCV validation remains upstream. It does not enforce a strategy warm-up or read optional `desired_position`/`signal_time` columns; it executes only supplied events.

The pipeline delegates validation and calculations to those components, adds alignment checks, and returns in-memory results only. `desired_position` is intent after a completed candle; `executed_position` is the state held during that candle after any previous signal fills at its OPEN. They legitimately differ on entry/exit signal rows. Prefix stability excludes execution metadata for a former final-row event that gains a next candle; all earlier rows and shared-prefix strategy/position values remain unchanged.

The ledger consumes the full candle state table starting flat and validates its recorded fills; it does not sort malformed input, calculate fills, or value an open trade. It preserves datetime timezone semantics and returns an empty typed ledger when no entry actually executes. The candle pipeline table and trade ledger remain separate in-memory outputs. The review notebook saves displayed excerpts and plots, but exports no dataset or separate report.

Accounting assumes consecutive trade IDs from 1, chronological non-overlapping trades, and at most one final OPEN trade. It never repairs or sorts invalid ledgers. CLOSED exit prices must be strictly positive; calculated results must remain finite with non-negative capital, and impossible quantity overflow/underflow raises an error. Floating-point tolerance is used for arithmetic checks. `trade_return` is a decimal return for one CLOSED trade; `gross_pnl` is realized PnL before costs. Compounded capital after closed trades is not a mark-to-market equity curve, and OPEN trades have no realized result or valuation.

Cost-aware accounting reuses the unchanged gross helper's ledger/capital validation, including its numerical limits, then independently sizes and compounds net results. Rates must be finite real numbers in `[0, 1)`; bools are rejected. Effective prices, entry sizing, and calculated amounts must be representable as finite floats; depleted capital cannot finance another trade. Rates are fixed research assumptions, with no exchange-specific fee tiers, minimum order sizes, or rounding. Cost-aware `gross_pnl` uses recorded prices with the cost-sized quantity, so it is not the separate Stage 4.6 simulation. OPEN `total_fees` stays missing because the round trip is incomplete; its known entry fee is reported separately.

The backtest review notebook observes the fixed EMA20/EMA50, 50-candle-warm-up sample without parameter optimization, out-of-sample testing, or walk-forward validation. Capital and drawdown plots use completed trade number, not time; within-trade movements and the final OPEN position are not valued. Stage 5.3 presented existing trade summaries; Stage 5.6 presents existing drawdown paths/summaries. No general conclusion about strategy quality follows from this single sample.

Decision 003 is implemented by the Stage 5.2 summary helpers. Arithmetic average trade return is distinct from compounded strategy return. Quote-currency expectancy describes this sample, not future profit. NaN and +infinity are intentional for documented undefined/unbounded cases. These summaries aggregate existing accounting outputs; full ledger/capital consistency validation stays upstream. Decision 004 is implemented separately by the Stage 5.5 drawdown helpers, using only explicit initial capital and CLOSED capital-after observations, and presented in notebook 03 by Stage 5.6. They can miss losses while trades are open and understate full mark-to-market drawdown. Mark-to-market drawdown, duration/exposure, benchmarks, Sharpe/Sortino, volatility, annualization, equity/valuation, and strategy-validation methods remain deferred.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
