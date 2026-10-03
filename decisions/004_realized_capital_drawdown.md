# 004 — Realized-capital drawdown

- Date: 2026-10-03
- Status: Accepted
- Scope: Stage 5.4 contract only; reusable drawdown implementation remains pending.
- Related decisions: [001 — Initial architecture](001_initial_architecture.md), [002 — Backtesting execution contract](002_backtest_execution_contract.md), [003 — CLOSED-trade performance metrics](003_closed_trade_performance_metrics.md).

## Purpose and observation set

Define **REALIZED-CAPITAL DRAWDOWN** before implementing it. The observations are capital before any trades at the explicit initial point, then capital after each CLOSED trade. This measures declines from previous observed realized-capital peaks. It is not full mark-to-market portfolio drawdown.

For `N` CLOSED trades, the ordered path is `C0, C1, ..., CN` and contains exactly `N + 1` observations:

- `C0 = initial_capital`.
- Each later `Ci` is the canonical capital after CLOSED trade `i`, in existing accounting order.
- Only rows with `status == "CLOSED"` produce post-trade observations. Do not sort, reorder, reconstruct chronology, or repair the input.

## Independent capital sources

| Path | Accounting source | CLOSED capital source | Required source columns |
| --- | --- | --- | --- |
| GROSS | Stage 4.6 `calculate_trade_results(...)` | `capital_after` | `status`, `capital_before`, `capital_after` |
| NET | Stage 4.7 `calculate_trade_results_with_costs(...)` | `net_capital_after` | `status`, `capital_before`, `net_capital_after` |

`capital_before` is accounting context and a schema guard, not an additional observation. The source-specific capital-after column must be required even for empty input, so passing the wrong Stage 4 output fails clearly. Stage 4.7 `gross_pnl` is not the canonical GROSS source. Never reconstruct either capital path by cumulatively summing PnL, subtracting fees from the other path, or recalculating accounting.

The future helper accepts `initial_capital` explicitly; a default of `10_000.0` may match the accounting APIs. The caller supplies the same initial capital used to generate the accounting results. Do not infer it from the first CLOSED capital-after value, a row index, or an OPEN row. Full ledger pairing and capital-continuity validation remain upstream in Stage 4.

The initial point is mandatory. For initial capital 10,000 and first CLOSED capital 8,000, the running peak is 10,000 and drawdown is `-0.20` (−20%). Omitting `C0` would incorrectly treat 8,000 as the first peak and report zero drawdown.

## OPEN exclusion

An OPEN row adds no observation. Its `capital_before` must not duplicate the last CLOSED point. In the NET path, its entry fee, entry notional, quantity, and capital before also must not become an ending-capital observation or adjust the last realized point.

The final OPEN position remains unvalued. Do not invent a closing fill or use a last-candle price. Adding or removing a valid final OPEN row must leave the entire path and maximum realized drawdown unchanged. Missing OPEN capital-after fields are expected and ignored.

## Peaks, drawdown, and signs

For each observation `Ci`, define:

```text
running_peak_i = max(C0, C1, ..., Ci)
drawdown_i = Ci / running_peak_i - 1
drawdown_amount_i = Ci - running_peak_i
max_realized_drawdown = min(drawdown_0, ..., drawdown_N)
```

At observation 0, the running peak is `initial_capital`; drawdown and drawdown amount are both `0.0`. A new capital high updates the peak. Repeated equal highs also have zero drawdown.

Drawdown uses the **negative sign convention**, matching Stage 2's sign convention while observing a different population. It is a dimensionless decimal in `[-1, 0]` for non-negative capital and positive initial capital: `0.0` means no decline, `-0.10` means 10% below the peak, and `-0.25` means 25% below the peak. Store a 25% drawdown as `-0.25`, never positive `0.25`; percentage formatting is display only.

Drawdown amount is quote currency, currently USDT, and is always `<= 0`. For peak 12,000 and capital 9,000, it is −3,000 USDT while decimal drawdown is `-0.25`. The term “maximum drawdown” means the largest decline from peak; numerically it is the **most negative**, or minimum, drawdown value.

An optional `max_realized_drawdown_amount` is the drawdown amount at the observation selected by `max_realized_drawdown`. It is not necessarily the minimum currency amount across the path, because peaks can differ. If multiple observations share the exact minimum unrounded drawdown, select the earliest in input order for this associated amount. Do not round, apply the trade-breakeven tolerance, add an epsilon, or clamp source values or results.

## Worked example

This illustrative path is not a BTC result:

| Observation | Capital | Running peak | Drawdown | Drawdown amount |
| --- | ---: | ---: | ---: | ---: |
| 0 | 10,000 | 10,000 | 0.00 | 0 |
| 1 | 11,000 | 11,000 | 0.00 | 0 |
| 2 | 9,900 | 11,000 | -0.10 | -1,100 |
| 3 | 12,000 | 12,000 | 0.00 | 0 |
| 4 | 9,000 | 12,000 | -0.25 | -3,000 |

Therefore `max_realized_drawdown = -0.25`. If reported, the associated `max_realized_drawdown_amount = -3_000` in quote currency.

## Empty, flat, increasing, and depleted paths

| Case | Required behavior |
| --- | --- |
| Zero CLOSED trades, including OPEN-only input | Exactly one point: initial capital, its peak, drawdown `0.0`, and amount `0.0`; maximum realized drawdown is `0.0`. |
| Capital only increases or stays exactly flat | Every observation is at a running peak; maximum realized drawdown is `0.0`. |
| Capital returns exactly to a previous peak | Drawdown at that observation is `0.0`; an earlier decline still remains in the path's maximum drawdown. |
| Post-CLOSED capital reaches zero | The positive historical peak remains; drawdown is `-1.0` (−100%). This is valid. |
| Negative post-CLOSED capital | Invalid; reject it without clamping or repair. |

Zero-CLOSED maximum drawdown is not NaN: no realized decline has been observed on the defined path. This differs from undefined empty trade statistics in decision 003. Initial capital must still be strictly positive; allowing zero after a CLOSED trade does not allow zero initial capital or change upstream trading/sizing rules.

## Future validation and preservation

Future implementation must validate at least:

- Input is a pandas DataFrame with unique column names and the required source-specific columns above.
- Every status is `CLOSED` or `OPEN`.
- Initial capital is finite real numeric and strictly positive, including for empty/OPEN-only input.
- Every CLOSED capital-after value is finite real numeric and non-negative. Missing values are errors.
- Booleans, numeric strings, complex values, missing values, and non-finite values are rejected as numeric capital; strings are never silently parsed.

Filter the defined CLOSED population without silently dropping malformed CLOSED rows. Expected missing OPEN capital-after values are ignored with their rows. Do not fill, sort, reorder, or repair input, and do not repeat the complete ledger/accounting validator. Preserve all input rows, values, index, dtypes, and column order; unrelated optional columns must not affect the result.

Future acceptance checks should cover the worked example, the initial-loss example, empty/OPEN-only input, OPEN removal, increasing/flat/repeated peaks, zero capital, invalid capital/schema/status, wrong accounting source, independent gross/net paths, and input preservation. If the optional associated amount is exposed, also check tied minima and the distinction from minimum currency drawdown. These are contract expectations, not implemented tests.

## Preferred future API and output

Prefer two explicit public functions with accounting results and explicit initial capital:

- `calculate_gross_realized_drawdown(results, initial_capital=10_000.0)`.
- `calculate_net_realized_drawdown(results, initial_capital=10_000.0)`.

These are proposed names, not available functions. A small private helper may share path calculations; avoid source guessing, classes, or an analytics framework. Prefer a path DataFrame with these columns in this order:

| Column | Meaning |
| --- | --- |
| `observation` | Integer ordinal `0..N`. |
| `closed_trade_number` | Integer CLOSED-trade ordinal: 0 initially, then `1..N` in input order. It does not require a ledger ID or use input index labels. |
| `capital` | Explicit initial capital, then source-specific CLOSED capital-after values. |
| `running_peak` | Maximum capital observed through this point. |
| `drawdown` | Negative decimal decline from that peak. |
| `drawdown_amount` | Non-positive quote-currency difference from that peak. |

Observation 0 has both ordinals 0, capital and peak equal to initial capital, and both drawdown fields `0.0`. Each later row represents one CLOSED trade. Timestamps are not required; this is observation order, not a time/duration metric.

Make `max_realized_drawdown` available in a small separate summary, optionally with its associated `max_realized_drawdown_amount`. Confirm simple path/summary return packaging during Stage 5.5 implementation. Keep this component separate from the existing Stage 5.2 summary: its exact 16 fields remain unchanged, with no 17th drawdown column.

## Interpretation and limits

**Realized-capital drawdown can understate full mark-to-market portfolio drawdown.** It observes only initial capital and capital after CLOSED trades. It does not observe unrealized losses during a position, intratrade adverse movement, candle-by-candle portfolio value, or the final OPEN position's current value. Do not label it “true maximum drawdown” or present it as full portfolio drawdown.

For example, capital starts at 10,000, a position temporarily has unrealized value 7,000, then recovers and closes at 9,500. The two realized observations show −5%, whereas a mark-to-market path including that temporary value could show −30%. This is a hypothetical illustration; Stage 5.4 defines no valuation method and calculates no such portfolio path.

GROSS and NET use their own capital paths and running peaks. Do not describe NET maximum drawdown as GROSS drawdown minus costs, or require a simple monotonic relationship between their ratios. Costs change compounding and peak levels. BTC drawdown will be measured only after implementation in Stage 5.5; no BTC drawdown value is calculated or hardcoded here.

## Deferred work and next milestone

Stage 5.4 defines these realized-capital conventions only. It introduces no production code, tests, notebook changes, raw-data changes, dependencies, or framework. Existing accounting functions and the Stage 5.2 metric contract remain unchanged.

Still deferred: mark-to-market drawdown, candle-level equity, unrealized PnL, recovery time, drawdown duration, time under water, average drawdown, Ulcer Index, trade duration, exposure, benchmarks, Sharpe/Sortino, volatility, annualization/CAGR, Calmar, alpha/beta, parameter optimization, out-of-sample testing, and walk-forward testing.

Recommended next: **Stage 5.5 — Reusable Realized-Capital Drawdown Implementation**, using a small separate analytics component and focused synthetic tests for this contract. Do not start Stage 5.5 without the owner's approval.
