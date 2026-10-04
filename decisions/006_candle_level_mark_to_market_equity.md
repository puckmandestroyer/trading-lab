# 006 — Candle-level portfolio equity / mark-to-market

- Date: 2026-10-04
- Status: Accepted
- Scope: Stage 5.10 contract only. Equity implementation and BTC mark-to-market measurement are pending Stage 5.11 approval.
- Related decisions: [001 — Initial architecture](001_initial_architecture.md), [002 — Backtesting execution contract](002_backtest_execution_contract.md), [003 — CLOSED-trade performance metrics](003_closed_trade_performance_metrics.md), [004 — Realized-capital drawdown](004_realized_capital_drawdown.md), [005 — Trade duration and exposure](005_trade_duration_and_exposure.md).

## Purpose and current model

Answer: "What was the portfolio worth at the end of each observed candle?" The future path includes initial capital and one portfolio valuation after **every** candle, including while a position is OPEN. Existing realized-capital analytics observes only initial capital and capital after CLOSED trades; it remains a separate valid result.

Scope is one asset, long-only spot, one position at a time, no leverage, 100% capital allocation on entry, fixed transaction-cost assumptions for NET, fixed-interval candles, and candle-CLOSE marking. Cash and value/PnL use quote currency; quantity uses base-asset units. This is an explicit contract for the current Stage 4 accounting model, not a general portfolio framework.

The component consumes market candles and canonical executed/accounting results. It knows nothing about EMA, RSI, momentum, XGBoost, neural networks, or other signal-generation methods. Any strategy producing the same execution/accounting contracts can use it. It does not generate signals, simulate fills, pair trades, download data, or call an exchange.

## Canonical inputs and independent paths

Validated market candles require at least `timestamp` and `close`. Under the project convention, `timestamp` labels the candle OPEN; `close` is its raw market mark when that candle completes. Do not use HIGH, LOW, the next candle's OPEN/CLOSE, or other future prices to construct this path.

GROSS and NET consume their own canonical Stage 4 results:

| Path | Canonical source | Minimum required columns, including empty input |
| --- | --- | --- |
| GROSS | Stage 4.6 `calculate_trade_results(...)` | `trade_id`, `status`, `entry_time`, `entry_price`, `exit_time`, `capital_before`, `quantity`, `capital_after` |
| NET | Stage 4.7 `calculate_trade_results_with_costs(...)` | `trade_id`, `status`, `entry_time`, `exit_time`, `capital_before`, `quantity`, `effective_entry_price`, `entry_fee`, `net_capital_after` |

Actual recorded `entry_time` / `exit_time` fills inherited from the Stage 4.5 ledger are authoritative. Signal times, signal-row timestamps, desired state, and execution-state transitions are not substitute event sources.

Reuse canonical quantity and capital. Do not resize from price, rebuild compounded capital from PnL, or rerun fee/slippage formulas. Each helper checks its source-specific schema and rejects the other Stage 4 output clearly rather than guessing a source or falling back to another column. Optional columns neither select the model nor change its calculations. Stage 4.7 `gross_pnl` uses the cost-sized quantity and is not the separate GROSS simulation.

Both paths use the same raw CLOSE marks. Their differences come from canonical quantity, effective entry basis, paid fees, actual realized exits, and subsequent compounded capital. Never define NET equity as GROSS equity minus cumulative costs.

## Future public functions

Finalize these names and argument order:

```python
calculate_gross_mark_to_market_equity(
    candles,
    gross_results,
    candle_interval,
    initial_capital=10_000.0,
)

calculate_net_mark_to_market_equity(
    candles,
    net_results,
    candle_interval,
    initial_capital=10_000.0,
)
```

Both will return the exact path DataFrame defined below. These functions **do not exist yet**. Use simple pure functions, no classes, generic framework, or strategy-specific API.

`candle_interval` is a required explicit finite positive fixed elapsed duration, preferably `pd.Timedelta(hours=1)`. Do not infer it from trades or guess from event spacing. Reject missing/invalid durations, calendar-dependent offsets, strings, bools, and unitless numbers. Candle spacing must exactly match the interval, and timestamp addition must remain safely representable.

`initial_capital` is an independent finite real numeric parameter, strictly positive; reject bool/np.bool_, strings, complex, missing, non-finite, or unrepresentable values. The default is 10,000, but callers must use the same value as accounting. Never infer it from the first trade, `capital_before`, cash, or PnL. Validate consistency with canonical available capital as a context check without reconstructing accounting.

## Observation window and event order

For N non-empty, contiguous candles:

```text
observation_start = first candle timestamp
observation_end   = last candle timestamp + candle_interval
path length       = N + 1
```

Observation 0 is at `observation_start`, immediately **before** any fill at the first candle OPEN. It is flat with initial cash/equity and no market mark. Include it even when an entry fills at that same OPEN; otherwise a first-candle loss could lose its starting reference for future drawdown.

For each candle opening at t:

1. Carry the state from the previous candle.
2. Process any actual EXIT fill scheduled at t.
3. Process any actual ENTRY fill scheduled at t.
4. Observe that candle through completion.
5. Mark any remaining position at that candle's raw CLOSE.
6. Record the row at `valuation_time = t + candle_interval`.

The CLOSE valuation of candle t occurs **before** processing the next candle's OPEN fills, even though both phases share the timestamp t + interval. Do not revise the preceding CLOSE row using those next-OPEN events. This preserves decision 002's causal order: completion/information availability precedes next-OPEN execution. Observation 0 similarly precedes the first OPEN's events.

If a future valid ledger has `old.exit_time == new.entry_time`, process EXIT then ENTRY at that shared OPEN. Ownership intervals are half-open `[entry_time, exit_time)`; there is never a simultaneous second long position. Current upstream execution/ledger validation remains unchanged, including its strict recorded-fill ordering; this ordering rule does not make the current pipeline produce shared-OPEN replacements or authorize repairing invalid ledgers.

All entry and CLOSED exit fills must match an actual supplied candle OPEN, within `[observation_start, observation_end)`. The exclusive window end is a final CLOSE valuation, not an extra supplied OPEN: reject a fill there without a corresponding candle. Decision 005's duration window may allow an exit at its end; this additional candle-alignment requirement is specific to equity and does not change that time contract.

## Cash, entry basis, marks, and incurred costs

After an entry, set `position = 1`, `active_trade_id` to that trade's ID, `quantity` to its canonical quantity, and `cash = 0.0`. All available capital has been allocated under the current model. While flat, position and quantity are zero, active ID is missing, position value/unrealized PnL are zero, and equity equals cash.

For every candle row, `mark_price` is that candle's **raw CLOSE**, even while flat. For a held position:

```text
position_value = quantity * mark_price
equity         = cash + position_value
```

GROSS uses recorded `entry_price` as its entry basis. NET uses canonical `effective_entry_price`; entry slippage has already affected that basis and the canonical quantity. NET entry fee has already been paid and is not subtracted again when marking.

Define `unrealized_pnl` as **price-based** PnL on the currently held position:

| State | Unrealized PnL |
| --- | --- |
| GROSS long | `quantity * (mark_price - entry_price)` |
| NET long | `quantity * (mark_price - effective_entry_price)` |
| Flat | `0.0` |

NET unrealized PnL excludes the already-paid entry fee. Conceptually, the existing self-financing accounting gives:

```text
quantity * effective_entry_price = capital_before - entry_fee
NET equity = capital_before - entry_fee + unrealized_pnl  (while long)
```

These identities explain/reconcile the model; the implementation must still use canonical quantity and mark-based position value. When the mark equals the effective entry basis, price-based unrealized PnL is zero, but NET equity is already lower than `capital_before` by the paid entry fee. Do not subtract that fee twice or keep `capital_before` as cash after entry.

Marking is not liquidation. Do not apply a hypothetical exit fee, sell slippage, spread estimate, or bid/ask adjustment to a CLOSE mark. Do not create an exit or realized PnL. NET marked equity reflects costs actually incurred so far, not immediate-liquidation proceeds after future exit costs.

## Actual exits, reconciliation, and final OPEN

At an actual exit OPEN, set GROSS cash directly to canonical `capital_after`, or NET cash directly to canonical `net_capital_after`. Set position/quantity/position value/unrealized PnL to zero and clear the active ID. Do not re-sell the quantity or recalculate exit proceeds. NET realized capital already includes actual modeled exit slippage and exit fee; apply neither again.

If the portfolio remains flat through that candle, its CLOSE equity equals that completed trade's canonical capital-after value. This is the realized-capital reconciliation rule. With a shared-OPEN replacement entry, cash reconciles immediately after the exit, then the new position is marked at CLOSE; that end-of-candle equity need not equal the old trade's realized capital. Never force that equality while a position is held.

The final OPEN trade remains OPEN and is marked on each remaining candle, including the last CLOSE. Final equity is cash plus held quantity times the last raw CLOSE. It is a marked portfolio value, not realized ending capital. Do not fabricate `exit_time`, realized PnL, `capital_after`, or `net_capital_after`, and do not modify the ledger/accounting outputs.

## Exact future path schema

Return only these 11 columns, in this order, on a new `RangeIndex`. N candles produce observations 0..N. No input index is reset or changed.

| Column | Meaning after a candle | Preferred dtype | Initial row (observation 0) |
| --- | --- | --- | --- |
| `observation` | Sequential observation number | int64 | `0` |
| `candle_timestamp` | Source candle OPEN timestamp | Coherent datetime | `NaT` |
| `valuation_time` | Source OPEN timestamp + interval | Same datetime/timezone semantics | `observation_start` |
| `mark_price` | Source raw CLOSE | float64 | `NaN` |
| `position` | 0 flat / 1 long | int64 | `0` |
| `active_trade_id` | Canonical ID while long; missing flat | Nullable Int64 for current integer IDs | `pd.NA` |
| `cash` | Quote-currency cash | float64 | `initial_capital` |
| `quantity` | Held base-asset quantity; zero flat | float64 | `0.0` |
| `position_value` | Quantity times mark while long; zero flat | float64 | `0.0` |
| `unrealized_pnl` | Price-based open-position PnL; zero flat | float64 | `0.0` |
| `equity` | Cash + position value | float64 | `initial_capital` |

Timestamp columns preserve the coherent input clock/timezone semantics, including the typed initial `NaT`. No rounding, percentage conversion, or currency formatting is part of this output.

## Worked GROSS example

This is a synthetic explanation, not a BTC measurement. Initial capital is 1,000; interval is one hour. A canonical GROSS trade enters at 00:00 OPEN at price 100 with quantity 10, then exits at 02:00 OPEN at price 120 with `capital_after = 1,200`.

| Observation | Candle OPEN | Valuation time | Mark | Position | Cash | Quantity | Position value | Unrealized PnL | Equity |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | Missing | 00:00, before entry | Undefined | 0 | 1,000 | 0 | 0 | 0 | 1,000 |
| 1 | 00:00 | 01:00 | 110 | 1 | 0 | 10 | 1,100 | +100 | 1,100 |
| 2 | 01:00 | 02:00, before exit | 90 | 1 | 0 | 10 | 900 | -100 | 900 |
| 3 | 02:00 | 03:00 | This candle's CLOSE | 0 | 1,200 | 0 | 0 | 0 | 1,200 |

The 02:00 valuation belongs to the preceding candle and precedes the 02:00 OPEN exit. After that actual exit, the 02:00 candle is flat; its CLOSE price is still recorded but cannot change held value because quantity is zero.

Mark-to-market equity: **1,000 → 1,100 → 900 → 1,200**. Realized capital: **1,000 → 1,200**, missing the temporary decline.

## Future validation, no lookahead, and preservation

Candle validation must require:

- A pandas DataFrame with unique columns, required `timestamp` / `close`, and at least one candle. Extra columns are irrelevant.
- Valid non-missing datetime timestamps, strictly increasing chronological order, no duplicates, exact spacing matching the supplied fixed interval, and safely representable valuation/window timestamps.
- Finite real numeric strictly positive CLOSE values; reject bool/np.bool_, strings, complex, missing, non-finite, or unsafe float values. Never sort, repair, infer missing candles, or fill gaps.

Accounting/event validation must require:

- A DataFrame with unique columns and the correct path-specific required fields, even when there are no trades; statuses exactly CLOSED/OPEN.
- Current canonical integer IDs and chronological trade order, at most one final OPEN trade, and no overlapping positions. CLOSED exit is strictly after its entry; next entry may equal the previous exit, with the ordering defined above.
- Valid non-missing entry times and CLOSED exit times matching supplied candle OPENs inside the window. OPEN exit time and its source-specific capital-after field remain missing.
- Finite real numeric strictly positive canonical quantities, entry bases, and `capital_before`; finite non-negative CLOSED capital-after values, and finite non-negative NET entry fees consistent with all-in entry allocation. Reject bools and malformed/unsafe financial values.
- Supplied initial capital agrees with initial available cash and each `capital_before` agrees with available canonical realized cash at its entry. All-in allocation must reconcile with canonical basis/quantity (including the paid NET entry fee). Floating-point tolerance may check these identities; never change, round, clamp, repair, or recompute source amounts to force agreement.
- Calculated position value, unrealized PnL, and equity remain representable finite floats. Full Stage 4 ledger pairing and fee/capital computation stay upstream; do not duplicate every upstream rule or call accounting to rebuild the path.

Use one coherent timestamp system across candle timestamps and non-missing event times: all naive, or all aware with matching timezone implementation/zone, following decision 005. UTC-aware input remains recommended. Same-zone DST offset changes are valid; interval spacing and addition measure fixed actual elapsed time, not wall-clock label differences. Reject aware/naive mixing, incompatible zones/implementations, strings/numeric epochs, and missing/unsafe event timestamps. Do not silently localize, convert, parse, or strip a timezone. Missing OPEN exits are not time events; supplied inputs and their dtypes stay unchanged.

At a CLOSE valuation, use only already-occurred OPEN fills and that completed candle's CLOSE. Do not use the next OPEN/CLOSE or future exit information. A historically CLOSED accounting row can contain a later exit and capital-after value; the position must still remain held until that recorded exit_time occurs. That future realized value cannot influence an earlier mark. Validation may inspect the complete input, but state valuation must follow this causal order.

Both public helpers must be pure: preserve candles and accounting tables, including rows, values, dtypes, columns, order, and indexes. Do not sort, reset their indexes, or overwrite columns. Return a new independent DataFrame.

## Boundary and population cases

| Case | Required behavior |
| --- | --- |
| Zero trades, valid candles | N + 1 rows, all flat with constant initial cash/equity; zero quantity/value/unrealized PnL and missing active ID. Each candle row still records its CLOSE mark; initial mark remains NaN. |
| OPEN-only | Flat initial state and cash before entry; from its entry candle onward, long with zero cash and canonical quantity, marked at each CLOSE. Final equity is marked; realized ending capital is absent. |
| Entry fills on final candle OPEN | Valid actual fill; mark it once at the final CLOSE. Keep the trade OPEN; fabricate no exit. A final-candle signal without an executed fill creates no position, per decision 002. |
| Exit fills on final candle OPEN | Apply canonical realized cash, then final CLOSE equity equals that cash while flat. If a valid replacement entry shares the OPEN, mark the replacement instead. |
| Exit followed by entry at a shared OPEN | EXIT then ENTRY, never overlapping ownership; reconcile exit cash before the new all-in entry. |

## Separate analytics layers and risk limitations

Decisions 003–005 and their implementations remain unchanged:

```text
Trade Ledger ───────────────────────→ duration / exposure

Canonical GROSS / NET accounting ───→ CLOSED-trade metrics
                                  └→ realized-capital drawdown (decision 004)

Market candles + canonical accounting
              ↓
Future candle-level mark-to-market equity
              ├→ independent GROSS equity path
              └→ independent NET equity path
                         ↓
Future candle-close portfolio drawdown / equity returns
Future volatility / Sharpe / Sortino
```

Decision 004 observes initial capital plus post-CLOSED capital only; OPEN rows add no point. The new path observes initial capital plus every candle CLOSE and can reveal declines within a trade. Future portfolio drawdown will use this equity series: conceptually `running_peak = maximum equity observed so far` and `portfolio_drawdown = equity / running_peak - 1`. The initial observation supplies a starting peak for a first-candle loss. This is not implemented here and must be named separately from realized-capital drawdown; do not change `analytics/drawdown.py`.

This is **candle-close** equity and future candle-close drawdown, not continuous-time or tick-level risk. For example, equity at the previous CLOSE may be 10,000, briefly fall to 7,000 within the next hourly candle, and close at 9,500. This path records 9,500 and misses the temporary 7,000; its future drawdown can still understate intrabar/tick-level losses. HIGH/LOW cannot reconstruct the exact time path and must not be used for this equity curve. MAE/MFE, high/low excursions, and intrabar stress are separate deferred analytics.

## Deferred work and next milestone

Stage 5.10 creates documentation only: no equity code, new tests, notebook changes, or BTC mark-to-market calculations. Existing production code, tests, notebooks, raw data, requirements, and decisions 001–005 must remain unchanged. Run the existing 257-test suite to verify preservation; do not commit automatically.

Deferred: equity implementation and notebook integration; portfolio drawdown; equity-return metrics, Sharpe, Sortino, volatility, annualization, CAGR, Calmar, benchmarks, alpha/beta; intrabar MAE/MFE/stress; hypothetical liquidation value; shorts, leverage, funding, borrow interest, partial allocation, multiple assets/positions, dynamic fee tiers, position-size-weighted exposure; out-of-sample testing and walk-forward validation.

Recommended next is **Stage 5.11 — Reusable Candle-Level Mark-to-Market Equity Implementation**, only after owner approval. Implement the two pure functions and synthetic acceptance tests for exact schema/dtypes/N + 1 length, initial losses, event phases/no lookahead, independent canonical sources, paid-fee semantics, realized-capital reconciliation, zero trades, OPEN-only/final fills, malformed inputs/timezones, arithmetic identities, and input preservation. This decision does not authorize starting that work.
