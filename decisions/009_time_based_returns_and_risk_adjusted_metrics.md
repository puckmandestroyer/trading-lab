# 009 — Time-based returns and risk-adjusted metrics

- Date: 2026-10-04
- Status: Accepted
- Scope: Stage 5.17 — Time-Based Returns + Sharpe / Sortino.
- Sources: [006 — Portfolio equity](006_candle_level_mark_to_market_equity.md) and [008 — Buy-and-Hold benchmark](008_buy_and_hold_benchmark.md).

## Purpose and source boundary

Trade-level statistics answer “How did completed trades behave?” Time-based
portfolio returns answer “How did portfolio value change through time?” Sharpe
and Sortino belong to the second category, measuring return relative to total
and downside return variability respectively.

The sole financial source is an existing marked portfolio equity path. Apply
the same pure analytics independently to EMA GROSS, Buy & Hold GROSS, EMA NET,
and Buy & Hold NET. Do not consume candles, raw BTC returns, signals, individual
trade PnL/returns, CLOSED-trade accounting, or realized-capital paths. NET returns
are not GROSS returns minus costs: each comes from its own equity path.

The current paths already contain costs actually incurred, cash periods, and
final OPEN marks. Never rebuild sizing, fees, fills, liquidation, or valuation.
The final OPEN EMA trade 78 naturally contributes its marked-equity change to
the final return, without a forced exit or hypothetical liquidation costs.

## Simple returns and exact timing

For consecutive equity observations `E_0, E_1, ..., E_N`, calculate:

```text
r_i = E_i / E_(i-1) - 1, for i = 1, ..., N
```

Use simple returns, not log returns, `trade_return`, `net_trade_return`,
`gross_pnl`, or `net_pnl`. Retain every interval, including unchanged cash periods
whose return is exactly zero. Removing those periods would measure something
closer to returns conditional on investment, rather than the whole portfolio
over time, and would break the common EMA/Buy-and-Hold observation window.

Each return belongs to previous `valuation_time` → current `valuation_time`.
N + 1 equity observations produce N returns, with ending ordinals 1..N.
Observation 0 has no standalone return: do not prepend a fake zero or drop the
first actual return. Current 8,761 equity observations produce 8,760 hourly
periods, first 0 → 1 and last 8,759 → 8,760. The clock runs from first period
`2025-10-01 00:00 → 01:00 UTC` through final end `2026-10-01 00:00 UTC`.

## APIs and exact outputs

Module: `src/trading_lab/analytics/risk_adjusted.py`.

```python
calculate_time_based_returns(equity_path: pd.DataFrame) -> pd.DataFrame

summarize_risk_adjusted_performance(
    equity_path: pd.DataFrame,
    periods_per_year: float,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
    label: str = "PORTFOLIO",
) -> pd.DataFrame
```

The summary calls the return helper, never a second return calculation. Use
simple pure functions, no classes, framework, new dependency, network access,
or persistence. Preserve source values, dtypes, columns, order, and index;
return independent DataFrames.

Return exactly these six columns on a new RangeIndex 0..N-1:

| Column | Meaning | dtype |
| --- | --- | --- |
| `observation` | Ending equity ordinal 1..N | int64 |
| `period_start_time` | Valuation time of observation i-1 | Coherent datetime |
| `period_end_time` | Valuation time of observation i | Same datetime dtype |
| `starting_equity` | E_(i-1) | float64 |
| `ending_equity` | E_i | float64 |
| `period_return` | E_i / E_(i-1) - 1 | float64 |

Summary is one row indexed by the supplied label, with exactly these fields in
order: `period_count`, `mean_period_return`, `period_return_std`,
`annualized_volatility`, `downside_deviation`, `annualized_downside_deviation`,
`sharpe_ratio`, `sortino_ratio`. Count is int64; all other fields are float64.
Do not round, format percentages, or relabel periods as hours inside the module.

## Validation and fixed elapsed spacing

Require a pandas DataFrame, unique columns, `observation` / `valuation_time` /
`equity`, and at least two equity observations. Extra columns are irrelevant.
Ordinals must be canonical consecutive integers exactly 0..N; reject bools,
strings, floats, missing values, duplicates, and reordered/skipped ordinals.

Times must be existing valid, non-missing, safely representable datetimes,
strictly increasing, unique, and equally spaced by actual elapsed time. Use
one coherent all-naive or same-timezone-implementation/zone-aware clock,
consistent with decision 006. Same-zone DST offset changes are valid when
elapsed spacing is equal; naive DST labels do not supply missing elapsed-time
information. Preserve coherent timezone semantics in both output columns.
Never silently parse, localize, convert, sort, interpolate, or repair input.

Equity must be finite real numeric and safely representable as float64; reject
bool/np.bool_, strings, complex, missing/non-finite/unsafe values. First equity
is strictly positive; later equity may be non-negative. Every starting equity
must be strictly positive. A final positive → zero transition is valid and
returns -1.0; any earlier zero is rejected because a subsequent interval would
require division by zero. Do not replace zero denominators or invent returns.
Reject non-finite calculated returns or unsupported non-finite arithmetic.

`periods_per_year` must be explicit positive finite real numeric, rejecting
bools and malformed strings. Per-period risk-free return and MAR must be finite
real numeric, rejecting bools and malformed strings. Label must be a nonempty
string; whitespace-only labels are invalid, and valid labels remain unchanged.

## Time basis, risk-free rate, and target

Current hourly 24/7 crypto research uses exactly:

```text
periods_per_year = 365 * 24 = 8760
risk_free_return_per_period = 0.0
minimum_acceptable_return_per_period = 0.0
annualization_factor = sqrt(periods_per_year)
```

8760 is an explicit analytics convention, not inferred from sample row count,
252 trading days, 365.25 days, or the current calendar year. Future non-hourly
callers must supply their own appropriate basis; spacing validation does not
guess annualization. Flat cash earns no modeled interest/funding/treasury yield,
so this stage introduces no external rate assumption. Do not download rates or
convert an external annual risk-free rate. The API accepts explicit finite
per-period parameters for the formulas below; constructing a nonzero cash-yield
or target model is deferred. All four current comparisons use zero rf/MAR.

## Sharpe and volatility convention

```text
excess_i = r_i - rf
mean_excess = arithmetic_mean(excess_i)
sample_std_excess = std(excess_i, ddof=1)
Sharpe = mean_excess / sample_std_excess * sqrt(periods_per_year)

mean_period_return = arithmetic_mean(r_i)
period_return_std = std(r_i, ddof=1)
annualized_volatility = period_return_std * sqrt(periods_per_year)
```

Use sample standard deviation, not population standard deviation. Apply the
single square-root scaling to the ratio; do not inconsistently annualize its
mean and standard deviation. This measures return relative to total return
variability on the supplied portfolio clock, not dispersion of trade outcomes.

## Sortino convention

```text
MAR = minimum_acceptable_return_per_period
downside_i = min(r_i - MAR, 0)
downside_deviation = sqrt(mean(downside_i ** 2))
annualized_downside_deviation = downside_deviation * sqrt(periods_per_year)
Sortino = (mean(r_i) - MAR) / downside_deviation * sqrt(periods_per_year)
```

The downside mean is over **ALL periods**; non-downside observations contribute
zero. Do not take standard deviation only over negative-return observations.
This exact definition matters because Sortino has multiple conventions.
Scaling the RMS computation to avoid squaring overflow/underflow is permitted;
it preserves the same all-period mean and introduces no epsilon or new metric.

## Degenerate cases and numerical outputs

With fewer than two returns, sample standard deviation cannot be estimated:
`period_return_std`, `annualized_volatility`, and Sharpe are NaN. One actual
return is retained; Sortino still uses its defined downside calculation.

When sample excess standard deviation is exactly zero, Sharpe is +inf for
positive mean excess, -inf for negative mean excess, and NaN for zero mean
excess. When downside deviation is exactly zero, Sortino is +inf for positive
mean return minus MAR, or NaN for zero numerator. A negative numerator with zero
downside cannot occur under the all-period definition.

Do not add epsilons, clamp infinities, or silently substitute zero. NaN/±inf
ratios are intentional only for these documented cases; undefined single-return
std/volatility are the associated sample-estimation exception. All other
intermediates must be finite; reject unrepresentable arithmetic rather than
mislabeling overflow as a legitimate degenerate ratio. Normal BTC results must
come from actual calculations, not guessed references or Stage 2 statistics.

## Notebook, interpretation, testing, and preservation

Apply analytics independently to all four existing aligned equity paths. Before
comparison verify 8,761 equity observations, 8,760 returns, identical ordinal
arrays, valuation times, and start/end return clocks. Deep-copy all four sources
before new calls and assert preservation after analytics/presentation, alongside
candle and raw CSV hash preservation.

Notebook 03 presents one compact four-column/eight-row helper-output table,
clearly labeled periods/year 8760, hourly rf 0, hourly MAR 0. Format percentage
fields separately from raw ratios. Show compact first/flat-EMA/nonzero-invested/
final return previews with all six return fields; never print all periods.
Add exactly one Matplotlib diagnostic from existing NET hourly returns, using
end time and return, with transparency to handle density. If unreadable, use
one simple histogram comparison instead. Do not add a reusable rolling metric,
rolling Sharpe, KDE, seaborn, or multiple plots. Keep all six existing plot
sources/images unchanged, yielding seven plots. Execute every code cell
sequentially, saving no errors. Regression references belong only in assertions,
not production constants or display calculations.

Explain Sharpe as reward relative to total variability and Sortino as reward
relative to downside deviations below MAR. Here signs are relative to zero
hourly return because rf = MAR = 0. Ratios depend on sampling interval,
annualization convention, modeled costs, exposure, and selected sample. Retain
EMA flat periods. A higher ratio alone proves neither general superiority nor
statistical significance; make no confidence or significance claims.

Focused tests cover schemas/dtypes/initial timing/formula/zeros, validation and
equally spaced coherent clocks including DST, preservation/output independence,
causal prefixes, summary conventions/parameters/degenerate ratios, actual
Stage 5.11 EMA and Stage 5.16 benchmark integration, full clock alignment, and
final OPEN mark inclusion. Run only the new test module during development,
then the full suite once at the end. The prior suite has 397 tests.

Create only this decision, `analytics/risk_adjusted.py`, and
`tests/test_risk_adjusted.py`; modify notebook 03 and current sections of
PROJECT_STATE/README, plus a concise top CHANGELOG entry. Preserve existing
production modules/tests, decisions 001–008, notebooks 01/02, raw data, and
requirements. No automatic commit.

Deferred: CAGR, Calmar, Omega, Treynor, alpha/beta, tracking error/information
ratio, VaR/CVaR, drawdown duration/recovery, MAE/MFE, rolling Sharpe,
optimization, statistical tests/confidence intervals, out-of-sample analysis,
and Stage 6.

Next: **Stage 5.18 — Final Stage 5 Analytics Notebook / Report**, consolidating
and reviewing existing analytics without another major financial metric family.
Do not start it here. Stage 6 begins only after Stage 5.18 is completed,
reviewed, committed, and explicitly approved by the owner.
