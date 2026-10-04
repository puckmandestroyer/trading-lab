# 005 — Trade duration and exposure

- Date: 2026-10-04
- Status: Accepted
- Scope: Stage 5.7 contract only; reusable duration/exposure implementation is pending approval.
- Related decisions: [001 — Initial architecture](001_initial_architecture.md), [002 — Backtesting execution contract](002_backtest_execution_contract.md), [003 — CLOSED-trade performance metrics](003_closed_trade_performance_metrics.md), [004 — Realized-capital drawdown](004_realized_capital_drawdown.md).

## Purpose and canonical source

Define completed trade duration and simple binary time-in-market exposure before implementation. The canonical input is `trades`, the executed trade ledger returned by Stage 4.5 `build_trade_ledger(...)`. Its `entry_time` and `exit_time` record actual simulated entry/exit fills under decision 002. A position begins when its entry fills and ends when its exit fills.

Do not derive these times from signal candles, `signal_time`, source candle timestamps, desired/executed-position transitions, or gross/net accounting. Signal intent is not a fill; even when signal availability and execution share a timestamp, the recorded ledger fill is authoritative. Unexecuted terminal events create no new observed position and do not close an existing OPEN trade.

The future component requires `trade_id`, `status`, `entry_time`, and `exit_time`, including for empty input. The canonical ledger also contains entry/exit prices, but those and any optional PnL/capital fields are irrelevant to these time metrics. Full ledger pairing, IDs, price validation, and execution-state validation remain upstream.

## One ledger-based result, without a GROSS/NET split

Stage 4.6 and Stage 4.7 consume the same ledger. Current fees/slippage change effective prices, quantity, PnL, and compounded capital; they do not change `entry_time` or `exit_time`. Calculate duration/exposure once from `trades`, not separately from `gross_results` and `net_results`. Use the neutral summary index **`TIME`**.

A future execution model that changes actual fill timing would produce a different ledger and naturally different time metrics. Duration/exposure must know nothing about EMA, RSI, momentum, ML models, or future rule-based signal generation. Any strategy/model producing the same canonical executed ledger can use this component.

## CLOSED duration and half-open position intervals

A CLOSED position occupies **`[entry_time, exit_time)`**: it is held starting at entry, and no longer held at exit. Define:

```text
closed_trade_duration = exit_time - entry_time
closed_duration_hours = closed_trade_duration.total_seconds() / 3600
```

Require `exit_time > entry_time`, so completed duration is strictly positive. Entry at 10:00 and exit at 15:00 means five elapsed hours, not six candle labels. Do not round to whole hours/candles. Hours are a numeric presentation of timestamp subtraction, not a count of rows.

Half-open intervals avoid double-counting a touching exit/entry boundary. They do not change the existing Stage 4 ledger's stricter fill-order rules.

## OPEN duration versus observed exposure

An OPEN trade has no exit fill. Its completed duration is undefined: `closed_duration_hours = NaN`. Exclude it from average, median, minimum, maximum, and total **CLOSED** duration. Never replace its ledger `exit_time` with the window end or pretend it completed.

For exposure, its already observed holding interval is known:

```text
OPEN observed interval = [entry_time, observation_end)
observed_open_time = observation_end - entry_time
```

Include this positive observed interval in total time in market. `observation_end` is an exposure boundary, not a synthetic exit or market valuation. Dropping the final OPEN contribution would understate exposure. Its future completed duration remains unknown, and no unrealized PnL or position value is introduced.

## Explicit observation window and denominator

The caller must supply **`[observation_start, observation_end)`**, with `observation_end > observation_start`. Do not infer either boundary from the first entry, last exit, first CLOSED trade, or final CLOSED trade. The window describes market observation, including flat periods, rather than trading activity.

For current fixed-interval candle research, the caller uses:

```text
observation_start = first market candle's OPEN timestamp
observation_end = last market candle's OPEN timestamp + candle_interval
observation_window_duration = observation_end - observation_start
observation_window_hours = observation_window_duration.total_seconds() / 3600
```

The entire loaded market window is the denominator, including initialization/warm-up time before trading eligibility. It includes time before the first entry, flat gaps, time after a final CLOSED trade, and time through the final candle's end. The observed portion of a final OPEN position is within that same window.

For the existing BTC hourly sample, the conceptual window is `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. The last candle opens at `2026-09-30 23:00 UTC` and represents `[23:00, 00:00)`. Using that final OPEN timestamp as `observation_end` would omit the final hour. These dates illustrate caller-side boundaries; they must not be hardcoded into a reusable helper. That helper receives timestamps explicitly and needs no candles, interval parameter, or EMA knowledge.

## Observed time in market and exposure ratio

For each trade:

| Status | Observed interval | Observed time in market |
| --- | --- | --- |
| CLOSED | `[entry_time, exit_time)` | `exit_time - entry_time` |
| Final OPEN | `[entry_time, observation_end)` | `observation_end - entry_time` |

Define:

```text
total_closed_duration = sum(CLOSED exit_time - entry_time)
open_observed_duration = observation_end - OPEN entry_time, or zero if no OPEN trade
total_time_in_market = total_closed_duration + open_observed_duration
exposure_ratio = total_time_in_market / observation_window_duration
```

The current ledger is chronological, long-only, single-position, and non-overlapping. Under that contract, summing observed intervals equals the duration of their union. Flat gaps contribute nothing to the numerator and remain in the denominator. Exposure measures whether a position is held, not its size, leverage, capital allocation, or economic outcome.

Exposure is a decimal fraction in `[0, 1]`: `0.0` means never held a position, `0.25` means held one for 25% of the window, and `1.0` means held one throughout. Do not annualize, multiply by 100 internally, round before aggregation, add an epsilon, or clamp invalid results. Percentage formatting is presentation only. Calculate with elapsed timestamp durations before expressing hours for output.

## Worked example and denominator choice

All times below belong to the same UTC day. This is an illustrative contract example, not a BTC measurement.

Observation window: `[00:00, 10:00)`, ten hours.

| Trade | Status | Entry | Exit | CLOSED duration | Observed time in market |
| --- | --- | --- | --- | --- | --- |
| 1 | CLOSED | 01:00 | 04:00 | 3 hours | 3 hours |
| 2 | OPEN | 07:00 | Missing | Undefined / NaN | 3 hours through 10:00 |

Thus total observed time in market is `3 + 3 = 6` hours and exposure is `6 / 10 = 0.60` (60%). CLOSED average/median/minimum/maximum duration are each three hours; total CLOSED duration is three hours. The OPEN trade contributes three hours to exposure and nothing to completed-duration statistics.

Using the first entry at 01:00 as the start would incorrectly shorten the denominator to nine hours. It would report `6 / 9 ≈ 66.67%`, ignoring the initial flat hour. The correct market observation window gives 60%. The denominator must come from the explicit backtest window, not the trading activity.

## Empty, OPEN-only, and full-exposure cases

| Case | Required future behavior |
| --- | --- |
| Zero trades | Counts 0/0; four CLOSED descriptive duration statistics NaN; total CLOSED, OPEN observed, and total time-in-market hours `0.0`; exposure `0.0`. The explicit valid window still has positive duration. |
| One OPEN trade, no CLOSED trades | CLOSED count 0 / OPEN count 1; four CLOSED descriptive statistics NaN; total CLOSED hours `0.0`; OPEN observed time equals `observation_end - entry_time` and supplies the entire numerator. Exposure is positive because entry must precede the end. |
| No OPEN trade | `open_observed_duration_hours = 0.0`; exposure uses CLOSED intervals only. Any remaining flat time through the end stays in the denominator. |
| Entry exactly at window start, still OPEN at its end | Observed time equals the whole window; exposure `1.0`. CLOSED descriptive statistics remain NaN because no trade completed. |

An empty per-trade result must retain its defined schema. The summary always has one `TIME` row, including for empty input; NaN is intentional only for undefined CLOSED descriptive statistics.

## Future timestamp, window, and ledger validation

Future implementation must reject malformed input with a clear error rather than repair it:

- `trades` must be a pandas DataFrame with unique columns and all four required columns, even when empty. Statuses must be exactly `CLOSED` or `OPEN`.
- Window boundaries must be valid non-missing timestamp values with a positive elapsed duration. Do not parse strings/numbers, assume local machine time, or silently coerce invalid timestamp input.
- Every entry must be a valid non-missing timestamp. Every CLOSED exit must be a valid non-missing timestamp strictly after its entry. Every OPEN exit must be missing.
- All entries satisfy `observation_start <= entry_time < observation_end`. CLOSED exits satisfy `entry_time < exit_time <= observation_end`. Thus entry at start and CLOSED exit at end are valid; OPEN entry at end, entry before start, or CLOSED exit after end are invalid.
- Timestamps must be comparable under the timezone rule below. Calculate valid representable positive elapsed durations; reject invalid/unrepresentable window or interval arithmetic without clipping or rounding.
- Keep existing ledger order. Entries must be chronological; at most one OPEN trade may exist and it must be final. A later entry must not precede the previous CLOSED exit. Reject overlapping observed intervals even when their summed exposure would remain below 100%; never sort, merge, clip, or repair them.

The metric's non-overlap check permits a touching boundary mathematically because intervals are half-open; it does not relax upstream execution/ledger validation. Do not duplicate the entire Stage 4 validator, inspect signal/position state, or revalidate price economics. The ledger must belong wholly to the stated window; this contract does not trim a broader ledger into a smaller window.

Both future public helpers must be pure. Preserve input rows, values, index, dtypes, and column order. Do not reset/sort the input, mutate an OPEN exit, or drop malformed rows. Unrelated optional columns must not affect output.

## Timezone convention

UTC-aware timestamps remain the recommended project convention and match the current market data/BTC notebook. To keep the first implementation explicit and consistent with the ledger, all non-missing ledger timestamps and both boundaries must either be:

- All timezone-aware with the same timezone; or
- All timezone-naive, already comparable as supplied by the caller.

Reject aware/naive mixtures and differing aware timezones rather than silently normalize them. An all-naive input remains naive; it never gains the local machine's timezone. For aware timestamps, subtraction must represent actual elapsed time, including across any daylight-saving transition, rather than counting wall-clock labels. Do not localize, convert, or strip timezones for calculation or display inside reusable analytics. Missing OPEN exits do not introduce a timezone mismatch.

## Preferred future API and exact per-trade output

Chosen future function names:

```text
calculate_trade_time_breakdown(trades, observation_start, observation_end)
summarize_trade_time_metrics(trades, observation_start, observation_end)
```

Both boundaries are required explicit arguments with no inferred defaults. Both functions should return pandas DataFrames. The summary should reuse the same validated per-trade time calculation. These are contract names, not available functions; Stage 5.7 implements neither. No classes, analytics framework, strategy-specific logic, or new dependency is needed.

The per-trade table has exactly these six columns, in order:

| Column | Meaning |
| --- | --- |
| `trade_id` | Original ledger ID. |
| `status` | Original CLOSED/OPEN status. |
| `entry_time` | Original recorded entry fill timestamp. |
| `exit_time` | Original recorded exit fill timestamp; missing for OPEN. |
| `closed_duration_hours` | CLOSED elapsed duration in hours; NaN for OPEN. |
| `observed_time_in_market_hours` | CLOSED duration, or final OPEN observed duration through the window end, in hours. |

Preserve source trade order, index, IDs/status, and timestamp values/dtypes/timezones in the new table; do not require a RangeIndex or add an initial-capital observation. The two duration columns use float64, including for empty input. Add no price, fee, PnL, quantity, or capital fields.

## Preferred future summary: exact 11 fields

Return one row indexed **`TIME`**, with these exact columns in order:

| Field | Definition / empty behavior |
| --- | --- |
| `closed_trade_count` | Number of CLOSED ledger rows; integer 0 when absent. |
| `open_trade_count` | Number of OPEN rows; integer 0 or 1 under the current contract. |
| `average_closed_duration_hours` | Arithmetic mean of CLOSED durations; NaN with zero CLOSED trades. |
| `median_closed_duration_hours` | Median of CLOSED durations (mean of middle two for an even count); NaN with zero CLOSED trades. |
| `minimum_closed_duration_hours` | Minimum CLOSED duration; NaN with zero CLOSED trades. |
| `maximum_closed_duration_hours` | Maximum CLOSED duration; NaN with zero CLOSED trades. |
| `total_closed_duration_hours` | Total CLOSED elapsed duration in hours; `0.0` when absent. |
| `open_observed_duration_hours` | Final OPEN observed duration in hours; `0.0` when absent. |
| `total_time_in_market_hours` | Total CLOSED plus OPEN observed time in hours; `0.0` with no trades. |
| `observation_window_hours` | Explicit positive window duration in hours, including for empty input. |
| `exposure_ratio` | Total observed time divided by the full window duration; decimal `0.0` with no trades. |

The two count fields use int64; the other nine use float64. Summary statistics use CLOSED durations only; exposure always includes the observed final OPEN interval. Keep this separate from decision 003's exact 16-metric summaries and decision 004's drawdown path/summary.

## Relation to the architecture

```text
Canonical executed trade ledger
    ├── Trade duration / binary time-in-market exposure (decision 005)
    └── Accounting
          ├── GROSS PnL / capital (Stage 4.6)
          └── NET PnL / capital (Stage 4.7)
                ↓ independent accounting outputs
          ├── Trade outcome / performance summaries (decision 003)
          └── Realized-capital drawdown (decision 004)
```

Time analytics consumes the ledger directly. Economic trade-outcome/performance summaries and realized-capital drawdown continue to consume their own accounting sources; this decision changes none of their formulas or schemas. OPEN exclusion in those components does not imply OPEN exclusion from observed time in market.

## Future acceptance cases, preservation, and deferred work

Stage 5.8 should cover the worked example, denominator choice, fractional elapsed durations, empty/OPEN-only/full-exposure cases, valid/invalid boundaries, missing or incompatible timestamps, aware elapsed time, order/overlap rejection, exact schemas/dtypes, input preservation, irrelevant optional fields, and integration with the unchanged trade-ledger helper. These are future expectations, not implemented tests or BTC duration/exposure measurements.

Stage 5.7 changes documentation only. Production code, tests, notebooks, raw data, dependencies, the 16-metric summary, and realized-capital drawdown remain unchanged. No duration/exposure code or notebook integration is introduced.

Explicitly deferred: candle-level mark-to-market equity, mark-to-market drawdown, unrealized PnL, Sharpe, Sortino, volatility, CAGR, Calmar, benchmark, alpha/beta, average drawdown, drawdown duration, recovery duration, time under water, overlapping multi-position exposure, leverage-adjusted exposure, gross/net exposure, position-size-weighted exposure, short exposure, parameter optimization, out-of-sample testing, and walk-forward testing. Only elapsed trade duration and simple binary observed time-in-market exposure are defined here.

Recommended next: **Stage 5.8 — Reusable Trade Duration and Exposure Implementation**, implementing this contract with the two explicit helpers and focused synthetic tests. Do not start Stage 5.8 until the owner approves it.
