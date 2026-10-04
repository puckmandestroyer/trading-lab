# Trading Lab

Trading Lab is a long-term Python project for researching cryptocurrency trading strategies and eventually running them in demo trading. It is also a learning environment for Python, data analysis, SQL, statistics, and quantitative analysis.

The long-term goal is to support historical market data, multiple independent strategies, a reusable backtesting engine, performance analysis and strategy comparison, multiple autonomous bot instances, centralized risk management, order management, PostgreSQL storage, per-bot and global dashboards, and Docker deployment.

## Current stage

**Stage 5.7 — Trade Duration and Exposure Contract (completed).**

- Stage 1 completed: reusable historical data collection and a validated BTCUSDT hourly snapshot.
- Stage 2 completed: statistical market analysis of returns, volatility, volume, extreme movements, and BTC buy-and-hold drawdown in `notebooks/01_data_exploration.ipynb`.
- Stage 3 completed: EMA20/EMA50 long-only signal research in `notebooks/02_ema_strategy.ipynb`.
- Stage 3.1 completed: a 50-candle warm-up, explicit `desired_position`, validated alternating entry/exit signals, and clarified signal availability.
- Stage 4.1 completed: the [backtesting execution contract](decisions/002_backtest_execution_contract.md) defines next-candle-OPEN fills, initial flat executed state, and final-candle behavior.
- Stage 4.2 completed: `src/trading_lab/backtest/execution.py` implements fill timing and executed state for supplied signals. Its 23 synthetic tests and all 13 existing market-data tests pass.
- Stage 4.3 completed: `src/trading_lab/strategies/ema_trend.py` provides the pure `generate_ema_signals` function, requiring only `timestamp` and `close`. The EMA notebook now uses it; 21 strategy tests bring the passing suite to 57 tests.
- Stage 4.4 completed: `src/trading_lab/backtest/pipeline.py` provides `run_ema_execution_pipeline`, requiring `timestamp`, `open`, and `close`. It composes the existing components with explicit alignment checks; 19 integration tests bring the passing suite to 76 tests.
- Stage 4.5 completed: `src/trading_lab/backtest/trades.py` provides `build_trade_ledger`, called separately after the pipeline. Its 25 tests bring the passing suite to 101 tests; the BTC snapshot has 77 CLOSED trades and one final OPEN trade.
- Stage 4.6 completed: `src/trading_lab/backtest/performance.py` provides `calculate_trade_results`, consuming the ledger to calculate quantity, CLOSED-trade returns, realized gross PnL, and compounded capital. Its 27 tests bring the passing suite to 128 tests.
- Stage 4.7 completed: `src/trading_lab/backtest/costs.py` provides `calculate_trade_results_with_costs`, adding self-financing entry sizing, adverse slippage, effective-notional fees, and net compounding. Its 21 tests bring the passing suite to 149 tests. The gross helper remains unchanged.
- Stage 4.8 completed: [`notebooks/03_backtest_review.ipynb`](notebooks/03_backtest_review.ipynb) originally added the local loader → EMA/execution pipeline → ledger → independent gross/net accounting review. Its initial 38 cells included 18 successfully executed code cells and two Matplotlib plots; all 149 tests passed at that milestone. No reusable financial logic was added.
- Stage 5.1 completed: [decision 003](decisions/003_closed_trade_performance_metrics.md) defines CLOSED-only performance metrics and their edge cases. Gross metrics use Stage 4.6 `trade_return` / `gross_pnl`; net metrics use Stage 4.7 `net_trade_return` / `net_pnl`. Classification uses return with a `1e-12` breakeven tolerance; profit factor and expectancy use PnL. OPEN trades are excluded. That stage added the contract only.
- Stage 5.2 completed: `src/trading_lab/analytics/trade_metrics.py` implements `summarize_gross_trade_performance(results)` and `summarize_net_trade_performance(results)` as separate pure functions. They return one-row `GROSS` / `NET` DataFrames with the contract's exact 16 fields and integer counts. Added 35 synthetic tests; all 184 tests pass.
- Stage 5.3 completed: notebook 03 calls those unchanged helpers on its existing accounting outputs and presents all 16 metrics in a readable Gross vs Net table. It explains the BTC results and asserts numeric references, OPEN exclusion, and input preservation. All 21 code cells executed in order; 44 total cells include 23 Markdown cells and the two existing plots. All 184 tests pass; no production code, new formulas, dependencies, or unit tests were added.
- Stage 5.4 completed: [decision 004](decisions/004_realized_capital_drawdown.md) defined realized-capital drawdown using explicit initial capital followed by capital after CLOSED trades. Gross uses Stage 4.6 `capital_after`; net uses Stage 4.7 `net_capital_after`. That documentation-only milestone passed all 184 existing tests and left implementation pending approval.
- Stage 5.5 completed: `src/trading_lab/analytics/drawdown.py` implements separate gross/net realized-capital paths and summaries. Added 32 synthetic tests, including integration with actual Stage 4 accounting outputs; all 216 tests passed. That milestone preserved accounting, the 16-metric summary, decisions, notebooks, raw data, and dependencies; notebook integration was then pending approval.
- Stage 5.6 completed: notebook 03 uses all four existing drawdown helpers on its existing gross/net results and initial capital. A separate Gross/Net table, beginner explanations, one new drawdown plot, and regression/OPEN-exclusion assertions follow the CLOSED-trade summary and precede cost analysis. All 25 code cells executed successfully: 52 cells total, 27 Markdown, three plots, sequential counts, and no errors. All 216 tests pass; production code/tests, decisions, notebooks 01/02, raw data, and dependencies are unchanged.
- Stage 5.7 completed: [decision 005](decisions/005_trade_duration_and_exposure.md) defines CLOSED duration and observed time-in-market exposure from recorded ledger fills and an explicit market window. The final OPEN trade contributes to exposure but not completed-duration statistics. This stage adds the contract only: all 216 tests pass, and production code, tests, notebooks, raw data, and dependencies remain unchanged. Implementation is pending approval.

The reusable strategy preserves the notebook's first 50 initialization-only candles; signals become eligible on candle 51 and use only completed candle data. `desired_position` is research intent, and `signal_time` is the candle timestamp plus one hour. Snapshot results remain 78 bullish/78 bearish crossovers, 78 entries/77 exits, and final desired state 1. Both EMA notebook charts and inspection tables remain available.

The independent execution helper consumes pre-generated signals, starts flat, and applies valid events at the next candle's OPEN. Execution time/price are recorded on the source signal row N; `executed_position` changes on row N+1. A valid final-candle signal has no fill, and invalid flat/long transitions raise `ValueError`.

The pipeline combines market, strategy, and execution columns after verifying equal row counts, indexes, timestamps, and chronological order. Strategy logic and execution logic remain in their own modules. `desired_position` is intent after a candle completes; `executed_position` is what is held during that candle, so they can differ on signal rows. Appending a next candle can give a formerly final signal its fill metadata without changing earlier results.

The separate ledger turns recorded execution fills into one row per trade: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, and `status`. CLOSED means an entry and exit actually executed; OPEN means an entry executed with no exit yet. An unexecuted final entry creates no trade, and an unexecuted final exit leaves a trade OPEN. The ledger uses recorded fill times/prices and never invents a terminal exit.

The Stage 4.6 zero-cost accounting helper adds `capital_before`, `quantity`, `trade_return`, `gross_pnl`, and `capital_after`. It defaults to 10,000 USDT and deploys 100% of current capital into each long spot trade, with no leverage, fees, commissions, slippage, or quantity rounding. Quantity equals capital before divided by entry price. Each CLOSED trade's gross result compounds into the next trade. OPEN trades have capital before and quantity but missing realized return, PnL, and capital after; no unrealized valuation is calculated.

The BTC snapshot's 77 CLOSED trades leave realized capital of 9,641.111388344 USDT before its final OPEN entry, which holds quantity 0.1130341406801 BTC. This is closed-trade accounting under the stated zero-cost model, not a valuation of that open position or a candle-level equity curve. Full portfolio simulation, further performance analytics, and demo trading remain future work.

The separate cost-aware helper defaults both rates to zero, reproducing the gross baseline economically. It preserves the six ledger columns and adds 14 financial columns. For long trades, effective entry is recorded entry times `(1 + slippage_rate)` and effective exit is recorded exit times `(1 - slippage_rate)`. Quantity is `capital_before / (effective_entry_price * (1 + fee_rate))`, so entry notional plus entry fee consumes exactly the available capital within floating-point tolerance. Each side's fee is its effective notional times `fee_rate`. CLOSED net PnL is the effective-price PnL minus both fees; net return divides by capital before, and net capital after compounds into the next trade. Cost-aware `gross_pnl` uses recorded prices and the cost-sized quantity; it differs from running the separate zero-cost model. Rates must be finite real numbers in `[0, 1)`, excluding bools. Initial capital must be positive and finite.

With test assumptions of a 0.10% fee per side and 0.05% adverse slippage per side, the same snapshot leaves 7,652.530163437 USDT after its last CLOSED trade, 1,988.581224907 USDT below the gross baseline. This difference includes slippage, fees, and their effect on compounded sizing; it is not just the sum of fees. These are research assumptions, not current Bybit fees. The final OPEN trade has capital before of 7,652.530163437 USDT, quantity 0.0895852306473 BTC, and entry fee 7.644885278 USDT. Its exit, round-trip total fees, net PnL, net return, and net capital after remain missing. No OPEN trade is valued, and the realized-capital comparison is before that final entry.

The backtest review notebook makes these stages visible without duplicating their logic. Starting from 10,000 USDT, the gross/net realized returns are -3.588886% / -23.474698%. It displays dataset and execution checks, first/last ledger rows, accounting previews, the unchanged 16-metric CLOSED summary, a separate realized-capital drawdown section, descriptive costs, and the final OPEN entry. Drawdown follows the performance summary and precedes cost analysis. Counts/ordinals display as integers, rates/returns/drawdown as percentages, and amounts/capital as USDT; underlying values remain unchanged. Three plots show realized capital, realized-capital drawdown with derived trough markers, and accumulated modeled costs. The drawdown chart includes observation 0 and uses CLOSED-trade number rather than a candle/time axis; none of these plots values positions during candles. The notebook requires the existing local snapshot and never downloads or overwrites it.

These results describe this historical sample under the stated assumptions and do not prove general strategy quality. EMA parameters were not optimized; no out-of-sample or walk-forward validation exists yet. The recommended next milestone is Stage 5.8 — Reusable Trade Duration and Exposure Implementation, following decision 005 with two simple ledger-based helpers and synthetic tests. Stage 5.8 has not started and requires approval.

The new time contract uses actual recorded entry/exit fills from `build_trade_ledger(...)`, not signals, desired/executed position, or accounting. A CLOSED trade occupies `[entry_time, exit_time)` and its strictly positive duration is `exit_time - entry_time`; hours express actual elapsed time rather than candle counts. An OPEN trade has no completed duration and is excluded from CLOSED duration statistics, but its observed `[entry_time, observation_end)` interval must count toward exposure. No exit or valuation is fabricated.

The observation window is explicitly `[observation_start, observation_end)`. For candle research, start is the first candle OPEN and end is the final candle OPEN plus the interval, including the final candle, warm-up, and flat periods. Total time in market is the sum of non-overlapping CLOSED intervals plus the final OPEN observed interval; exposure is that total divided by the full window duration, stored as a decimal `[0, 1]`. Using first/last trades to infer the denominator would omit flat time and inflate exposure. No trades means zero exposure and NaN CLOSED descriptive duration statistics; OPEN-only input has positive exposure, and an OPEN position held throughout the window gives `1.0`.

Duration/exposure will be calculated once from the ledger, with a separate `TIME` summary: current fees/slippage change economics but not fill timestamps, so no GROSS/NET split is needed. The future per-trade table has six fields; its summary has 11, separate from the existing 16 metrics and drawdown. Any strategy/model producing the canonical executed ledger can share it. UTC-aware timestamps are recommended; future helpers will reject incompatible timezones, invalid window boundaries, malformed order/overlap, and invalid OPEN/CLOSED times without sorting, clipping, or repair. See decision 005 for the exact schemas and future function names. No duration/exposure helper or BTC time-metric result exists yet, and notebook 03 is unchanged in this contract stage.

The reusable drawdown module provides `calculate_gross_realized_drawdown`, `calculate_net_realized_drawdown`, `summarize_gross_realized_drawdown`, and `summarize_net_realized_drawdown`. All accept `results` and explicit `initial_capital` (default 10,000). GROSS requires `status`, `capital_before`, `capital_after`; NET requires `status`, `capital_before`, `net_capital_after`. They read canonical CLOSED capital directly from their own accounting source, without inferring initial capital or reconstructing PnL. Summaries reuse the paths.

Exact path columns are `observation`, `closed_trade_number`, `capital`, `running_peak`, `drawdown`, `drawdown_amount`. The first two are int64 ordinals; the others are float64, with a RangeIndex. Initial capital is observation 0, then each CLOSED trade adds a point in existing input order. Running peak is the maximum capital observed so far; drawdown is `capital / running_peak - 1`, and its currency amount is `capital - running_peak`. A 25% decline is `-0.25`. Exact summary columns are `max_realized_drawdown`, `max_realized_drawdown_amount`, both float64 in one row indexed GROSS or NET. The amount comes from the earliest exact minimum percentage drawdown, which need not be the minimum currency decline.

Initial capital must be finite real numeric and strictly positive; CLOSED capital must be finite real numeric and non-negative. Bools/np.bool_, strings, complex, missing, and non-finite capital values are rejected. Required columns, unique column names, and exact CLOSED/OPEN statuses are checked; full accounting validation stays upstream. Inputs are preserved without sorting or repair, and optional columns are ignored. Empty/OPEN-only inputs have one initial point and zero summaries; zero CLOSED capital is valid and gives drawdown `-1.0`. OPEN rows add no point, their entry costs do not adjust the realized path, and they remain unvalued.

The offline BTC check and executed notebook have 77 CLOSED trades and 78 observations for each path: initial capital plus one point per CLOSED trade. Maximum realized-capital drawdown is -0.267234254550 (-26.723425%) GROSS at observation/CLOSED trade 33, with capital 7,327.657454501 USDT and amount -2,672.342545499 USDT; NET is -0.371855332627 (-37.185533%) at observation/CLOSED trade 66, with capital 6,281.446673733 USDT and amount -3,718.553326267 USDT. Both troughs have a 10,000 USDT running peak. Final capitals match 9,641.111388344 GROSS and 7,652.530163437 NET; removing the final OPEN row leaves paths and summaries identical. Notebook assertions also confirm unchanged accounting inputs and the raw-file hash. NET uses the research fee/slippage assumptions above. See `PROJECT_STATE.md` for the comparison.

This measures REALIZED-CAPITAL drawdown only. It misses losses while trades are open and can understate full mark-to-market portfolio drawdown. Notebook 03 explains that limitation beside the new table and in its conclusions. No drawdown column is added to the existing 16-metric summary, and no new financial metric formulas or valuation are introduced.

The summary helpers implement decision 003 without recalculating accounting. Each requires its explicit source's status, return, PnL, capital-before, and capital-after columns; passing the other Stage 4 output fails clearly. They classify WIN/LOSS/BREAKEVEN using unrounded source returns. Return averages and best/worst trades compare normalized outcomes; total realized PnL, sample expectancy, and profit factor describe quote-currency outcomes on each independent sizing path. Stage 4.7 `gross_pnl` is not the canonical gross strategy result. Invalid CLOSED financial values raise errors; OPEN rows and optional columns do not affect the metrics, and inputs are unchanged.

The exact output is four counts, win/loss/breakeven rates, average/median trade return, average winning/losing return, best/worst return, total realized PnL, `expectancy_pnl`, and profit factor. WIN/LOSS use returns above/below ±`1e-12`; boundaries are BREAKEVEN. Profit factor uses WIN PnL divided by absolute LOSS PnL, with +infinity for profit-only, zero for loss-only, and NaN for no eligible PnL. Breakeven residuals stay in total PnL/expectancy but are excluded from profit factor. Empty/OPEN-only summaries have zero counts/total PnL and NaN statistical fields.

The executed notebook gives 77 CLOSED trades per summary: 20 WIN, 57 LOSS, zero BREAKEVEN, and 25.974026% win rate. Average gross winning/losing returns are +3.865162% / -1.346661%; net values are +3.554033% / -1.642178%. Gross/net total PnL is -358.888611656 / -2,347.469836563 USDT; sample expectancy is -4.660891060 / -30.486621254 USDT per CLOSED trade; profit factor is 0.945165760246 / 0.675088667158. Costs happened to leave classification unchanged in this sample; that is not guaranteed elsewhere. The slightly positive gross arithmetic average return (+0.007059%) differs from its negative compounded outcome. Removing the final OPEN row leaves all 16 metrics unchanged, and that trade remains unvalued. See `PROJECT_STATE.md` for the full comparison. Stage 5.3 preserved reusable analytics, Stage 4 accounting, earlier notebooks, raw CSV, and dependencies; Stage 5.5 adds drawdown as a separate component.

The platform currently uses no real money. Public data collection requires no API key. Exchange trading and demo trading integration will be added later.

The first snapshot, `data/raw/BTCUSDT_1h.csv`, contains 8,760 hourly Bybit spot BTCUSDT candles from 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC. It contains only timestamp, open, high, low, close, and volume. See `data/README.md` for provenance and validation results.

## Directory guide

```text
Trading Lab/
├── AGENTS.md              # Instructions for future coding work
├── README.md              # Project overview
├── CHANGELOG.md           # Meaningful changes
├── PROJECT_STATE.md       # Current progress and next milestone
├── .gitignore             # Files excluded from Git
├── .env.example           # Empty credential variable examples
├── requirements.txt       # First-stage research dependencies
├── decisions/             # Important architecture decisions
├── notebooks/             # Exploration and experiments
├── data/
│   ├── raw/               # Original market data
│   ├── processed/         # Cleaned or transformed copies
│   └── proceseed/         # Existing misspelled directory, preserved
├── src/trading_lab/
│   ├── data/              # Reusable data loading and preprocessing
│   ├── strategies/        # Strategy signal generation
│   ├── backtest/          # Fill timing, trade ledger, gross/net accounting
│   ├── analytics/         # CLOSED-trade summaries and realized-capital drawdown
│   ├── exchange/          # Future exchange-specific adapters
│   ├── execution/         # Future order and execution management
│   ├── risk/              # Future centralized risk checks
│   ├── database/          # Future storage integration
│   └── config/            # Future application configuration
├── strategies/            # Existing Python placeholders, preserved
├── dashboard/             # Future dashboards; documentation only
├── results/               # Generated experiment and backtest output
├── tests/                 # Offline checks for reusable code
└── scripts/               # Future small command-line utilities
```

The data package contains `market_data.py`, the exchange package contains the public HTTP adapter `bybit_market_data.py`, the strategies package contains `ema_trend.py`, the backtest package contains `execution.py`, `pipeline.py`, `trades.py`, `performance.py`, and `costs.py`, and the analytics package contains `trade_metrics.py` and `drawdown.py`. Other application packages remain placeholders. Existing `.py` files in `notebooks/` and the top-level `strategies/` are preserved. New reusable strategy code belongs in `src/trading_lab/strategies/`.

## Research and reusable code

Use `notebooks/` to explore datasets, make plots, and try ideas. Use `src/trading_lab/` for stable Python code that can be reused in multiple notebooks or application workflows. Move research code there when it becomes useful and well understood; there is no need to build abstractions ahead of that point.

## Data and results

`data/raw/` contains original datasets and must never be manually edited. Read these files, then write cleaned or transformed copies to `data/processed/`. The existing `data/proceseed/` directory is retained; use the correctly spelled `processed/` for new work.

Store generated reports, plots, and backtest outputs in `results/`. Dataset and result contents are ignored by Git, while `.gitkeep` files preserve the intended empty directories. Document useful dataset provenance in `data/README.md`.

## Architecture

The planned flow is:

```text
Market Data → Strategy → Signal → Risk Manager → Execution Engine → Exchange
```

A strategy will produce BUY, SELL, or HOLD signals. The same strategy logic should eventually be usable in both historical backtesting and demo trading. Independent risk controls will govern position sizes and leverage. Exchange-specific code will stay in the exchange package. See `decisions/001_initial_architecture.md` for the boundaries.

## Research environment

`requirements.txt` lists pandas, NumPy, Matplotlib, JupyterLab, and requests. requests is the small HTTP library used to read the public API; no exchange SDK is needed. In the current workspace, the virtual environment lives one directory above this project:

```sh
source ../.venv/bin/activate
jupyter lab notebooks/01_data_exploration.ipynb
```

To review the complete existing backtest instead, open `notebooks/03_backtest_review.ipynb` with the same kernel and run its cells from top to bottom.

Select that virtual environment's Python kernel in a notebook-capable editor. The notebook adds `src/` to its import path, uses the reusable loader, and reads the local CSV when it already exists. It downloads only when the snapshot is absent, preserving consistent inputs for future research and backtests.

This project uses a `src/` layout without package installation configuration. To run the offline tests from this directory:

```sh
PYTHONPATH=src ../.venv/bin/python -m unittest discover -s tests -v
```

The loader supports Bybit's fixed minute-based intervals. It paginates backward through newest-first API pages, converts millisecond timestamps to UTC datetimes and numeric strings to floats, and sorts oldest first. It warns when removing identical duplicates and rejects conflicting duplicates, invalid candles, and incomplete interval coverage. Saving refuses to overwrite an existing snapshot. Daily, weekly, and monthly intervals are not supported in this first version.

`.env.example` contains empty variable names for future exchange configuration. Never add real credentials to source files or commit a local `.env` file. Credentials are not needed at this stage.

Read `PROJECT_STATE.md` before starting new work. Git is initialized at the project root (`/Users/romankondratenko/trading-lab/Trading Lab`). The initial commit has been pushed to [GitHub](https://github.com/puckmandestroyer/trading-lab), and `main` tracks `origin/main`. The CSV is ignored by the project's `.gitignore`.
