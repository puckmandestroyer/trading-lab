# 008 — Buy-and-Hold benchmark

- Date: 2026-10-04
- Status: Accepted
- Scope: Stage 5.16 — Benchmark Comparison.
- Related contracts: existing Stage 4.6/4.7 accounting, [006 — Mark-to-market equity](006_candle_level_mark_to_market_equity.md), [007 — Candle-close portfolio drawdown](007_candle_close_portfolio_drawdown.md).

## Purpose and entry timing

Compare the existing EMA strategy's marked portfolio with investing the same
initial capital in BTC at the start of the same historical observation window
and holding it. This measures the opportunity cost of active trading in this
sample; relative performance and absolute profitability are separate questions.

Buy at the **raw OPEN of the first supplied candle**, before observing that
candle's CLOSE. Do not use the first CLOSE, an EMA signal, the first strategy
entry, or future data. For the current snapshot, entry is `2025-10-01 00:00 UTC`
at raw OPEN `114051.1 USDT`. That number is a sample reference, not a production
constant. Do not copy Stage 2's exploratory Buy-and-Hold normalization; it is not
the canonical Stage 5 benchmark.

## Reuse accounting and equity

```text
Supplied candles
      ↓
One synthetic canonical OPEN trade
      ↓
Existing independent GROSS / NET accounting
      ↓
Existing Stage 5.11 mark-to-market equity
      ↓
Existing Stage 5.14 portfolio drawdown
```

Construct exactly one trade with the existing ledger's six columns in order:
`trade_id = 1`, `entry_time = first timestamp`, `entry_price = first OPEN`,
missing `exit_time` / `exit_price`, and `status = OPEN`. This trade is benchmark
plumbing, not a strategy signal; it bypasses EMA/execution logic. It remains
OPEN through the end. Never fabricate an exit or calculate liquidation proceeds.

GROSS delegates to `calculate_trade_results(...)`, then
`calculate_gross_mark_to_market_equity(...)`. NET delegates independently to
`calculate_trade_results_with_costs(...)`, then
`calculate_net_mark_to_market_equity(...)`. Do not reimplement quantity sizing,
effective entry prices, fees/slippage, position value, unrealized PnL, cash state,
or CLOSE marking. NET is not GROSS minus a fixed amount or accumulated costs.

## Capital and costs

Both paths use the same initial capital as the strategy. Scope is one asset,
long-only spot, all-in allocation, one position, no leverage, no lot rounding,
and the existing fixed research cost model.

- GROSS has no fees or slippage.
- NET uses the same modeled fee/slippage rates as the corresponding EMA run.
  Existing Stage 4.7 self-financing entry sizing includes the entry fee; the
  benchmark incurs entry slippage and its actual entry fee once.
- No hypothetical final exit fee or sell slippage is charged. Both EMA and
  benchmark are compared using marked equity; the current EMA sample ends with
  trade 78 OPEN. Marking is valuation, not a sale.

The current test scenario uses initial capital 10,000 USDT, fee rate `0.001`
per side and adverse slippage rate `0.0005` per side. These are research
assumptions only, not current exchange rates. Buy-and-Hold pays only its single
entry cost; EMA incurs costs on each actual modeled entry/exit. Different
turnover is part of the comparison, not a reason to add unincurred costs.

## Observation alignment and exact schema

Return the existing Stage 5.11 path directly, with exactly these columns:

```text
observation
candle_timestamp
valuation_time
mark_price
position
active_trade_id
cash
quantity
position_value
unrealized_pnl
equity
```

Use its existing RangeIndex and dtypes: int64 observation/position, nullable
Int64 active ID, float64 price/financial fields, and coherent source datetimes.
No incompatible benchmark-specific equity schema is introduced.

N nonempty candles produce N + 1 observations. Observation 0 is flat initial
capital immediately **before** the first-OPEN purchase, timed at the first
candle timestamp, with initial cash/equity, no active ID, and an undefined mark.
After that OPEN, the benchmark stays long with active ID 1 and zero cash.
Observation 1 is the first candle's raw CLOSE mark at first timestamp + interval;
each later observation marks its completed candle the same way. Quantity remains
the canonical entry quantity. Entry costs are not subtracted again at each mark.

Use the same explicit fixed `candle_interval`, initial capital, and supplied
candles as EMA. The current 8,760-hour snapshot produces 8,761 observations,
with final valuation at `2026-10-01 00:00 UTC`. Observation numbers and all
valuation times must align exactly with the EMA equity paths, including the
initial reference. No first-CLOSE rebasing or shorter strategy-entry window is
allowed. Future valid candles cannot change earlier benchmark valuations.

## Public APIs and validation boundary

Module: `src/trading_lab/analytics/benchmark.py`.

```python
calculate_gross_buy_and_hold_benchmark(
    candles: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame

calculate_net_buy_and_hold_benchmark(
    candles: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
) -> pd.DataFrame
```

Use simple pure functions and a small private trade-construction helper. Require
a pandas DataFrame, unique columns, `timestamp` / `open` / `close`, and at least
one candle. Check the first OPEN is a finite real positive entry price, rejecting
bool/np.bool_, strings, complex, missing, non-finite, and unsafe values. Guard the
first timestamp against strings/numeric epochs or missing values before building
the canonical datetime column, so inference cannot silently parse bad input.

Delegate established capital/rate, ledger, timestamp/clock, interval/spacing,
CLOSE, allocation, and finite-arithmetic validation to existing accounting/equity
helpers. Do not duplicate the full candle/accounting validator or validate later
OPENs as new fills: only the first OPEN creates an entry. Extra columns are
irrelevant. Preserve all input rows, values, dtypes, columns, order, and index;
do not sort, repair, interpolate, parse malformed data, or reset the input index.
Return independent DataFrames, with no downloads, exchange calls, or persistence.

## Drawdown and focused comparison

Feed each benchmark equity path to the corresponding existing Stage 5.14
calculate/summary portfolio-drawdown helpers. They supply the unchanged
candle-close drawdown formulas and exact episode-selection conventions. Add no
new drawdown formula or benchmark drawdown implementation.

For EMA GROSS, Buy & Hold GROSS, EMA NET, and Buy & Hold NET, present:

- Initial equity and final marked equity.
- Whole-window total marked return: `final_equity / initial_equity - 1`.
- Maximum candle-close portfolio drawdown from the existing summary.
- Observation count.

This total return is one holding-period result, **not** an hourly/time-based
return series. Also compare EMA minus benchmark final equity and total-return
difference in percentage points, separately for GROSS and NET. No annualization
or new risk-adjusted metric is implied. Values must come from actual helper
outputs, not Stage 2 results, guessed outcomes, or hardcoded production values.

Notebook 03 adds compact comparison/relative tables and exactly one time-aligned
marked-equity plot with all four paths starting from the same initial capital.
Keep all five existing plot cells/images unchanged, yielding six plots; do not
add a separate benchmark drawdown plot. Check observation/time alignment,
initial/long/final state, fixed BTC regressions, and input/raw preservation.

## Interpretation, tests, and deferred work

The sample contains a substantial BTC price decline. A strategy can lose money
yet perform better than holding, or make money while lagging holding. Report the
measured absolute and relative results without claiming general superiority from
one sample. Costs, compounding, exposure, and the first-OPEN opportunity window
matter; neither path is inferred from the other.

Both paths measure candle-CLOSE equity/drawdown and can miss intrabar/tick losses.
Final values are marks, not immediately liquidated proceeds. The comparison
uses the current all-in single-position spot model and fixed research cost
assumptions; it does not model bid/ask spreads or a richer execution market.

Focused tests cover exact schema/dtypes, N + 1 timing/initial state, first-OPEN
entry, permanent long/ID 1, canonical GROSS/NET sizing, incurred-once costs,
no forced exit, final CLOSE marks, exact zero-cost NET/GROSS equivalence,
validation delegation, preservation/output independence, causal prefixes,
existing drawdown compatibility, and actual BTC/EMA observation alignment.
Run the new module first during development, then the full suite once at the end.

Stage 5.16 does not change existing production modules/tests, decisions 001–007,
notebooks 01/02, raw data, or dependencies. Do not commit automatically.
Deferred: hourly/time-based returns, Sharpe/Sortino, risk-free rates,
annualization, volatility, CAGR/Calmar, alpha/beta, tracking error/information
ratio, duration/recovery, optimization, out-of-sample testing, and Stage 6.

Next: **Stage 5.17 — Time-Based Returns + Sharpe / Sortino**, using the aligned
EMA and Buy-and-Hold equity paths, only after owner approval. Then Stage 5.18 —
Final Stage 5 Analytics Notebook / Report completes the remaining Stage 5
roadmap. No later stage starts here.
