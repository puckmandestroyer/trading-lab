# 007 — Candle-Close Portfolio Drawdown

- Date: 2026-10-04
- Status: Accepted
- Scope: Stage 5.13 contract only; implementation remains pending Stage 5.14 approval.
- Related decisions: [006 — Candle-level mark-to-market equity](006_candle_level_mark_to_market_equity.md), [004 — Realized-capital drawdown](004_realized_capital_drawdown.md).

## Purpose and canonical source

Define **CANDLE-CLOSE PORTFOLIO DRAWDOWN** from the existing Stage 5.11 equity paths. It observes initial equity and every subsequent candle-CLOSE valuation, including held positions and the final OPEN position. It measures declines from the highest equity observed so far on that path.

Canonical sources are `calculate_gross_mark_to_market_equity(...)` and `calculate_net_mark_to_market_equity(...)` in `src/trading_lab/analytics/equity.py`. Each drawdown call consumes only one equity-path DataFrame, requiring `observation`, `valuation_time`, and `equity`. Extra columns are ignored; they neither select the source nor change calculations.

```text
Market candles + canonical accounting
                  ↓
Existing GROSS / NET mark-to-market equity paths
                  ↓
Independent GROSS / NET candle-close portfolio drawdown
```

Do not consume or revalidate candles, trades, accounting results, prices, fees, signals, or execution state. Do not rebuild equity, recalculate costs, resize positions, or rerun any upstream helper. The supplied equity path is authoritative for values and observation timing.

Both equity sources have identical schemas. GROSS/NET wrappers express explicit caller intent and provide summary labels; column names cannot establish provenance or detect a wrongly labelled source. Callers must pass the path from the corresponding equity helper. Both wrappers apply the same mathematical rule independently to their own path; NET is not GROSS minus costs. Costs affect the underlying equity and running peaks, so no simple ordering of GROSS/NET drawdown ratios is required.

## Formula, initial point, and causality

For each supplied observation `i`:

```text
running_peak_i    = max(equity_0, ..., equity_i)
drawdown_i        = equity_i / running_peak_i - 1
drawdown_amount_i = equity_i - running_peak_i
```

Use the negative sign convention: a 25% decline is `-0.25`; at a running peak, drawdown is `0.0`. Drawdown is a dimensionless decimal, not a percentage-formatted number. Drawdown amount is a non-positive quote-currency value, currently USDT. With positive initial equity and non-negative later equity, drawdown is in `[-1, 0]`.

Keep input observation 0 unchanged. Its equity is the initial reference, its running peak equals that equity, and both drawdown fields are `0.0`. Do not accept a separate `initial_capital`, infer another initial value, add a synthetic initial row, or drop the supplied first row. This reference captures a loss at the first candle CLOSE.

The running peak uses only observations up to and including `i`, never the eventual full-series maximum. Appending later valid observations must not change an earlier path row. A summary describes the complete supplied window; it does not feed future information into path calculations. No rounding, tolerance, epsilon, clamping, percentage conversion, or source repair belongs in these calculations or tie comparisons.

## Exact path output

Return a new independent DataFrame with exactly these six columns, in order:

| Column | Meaning | Dtype |
| --- | --- | --- |
| `observation` | Supplied ordinal `0, 1, ...` | int64 |
| `valuation_time` | Supplied initial/CLOSE observation time | Coherent datetime, preserving clock/timezone semantics |
| `equity` | Supplied portfolio equity | float64 |
| `running_peak` | Highest equity through this observation | float64 |
| `drawdown` | Equity / running peak − 1 | float64 |
| `drawdown_amount` | Equity − running peak | float64 |

Keep the same number and order of rows as input, including observation 0, and use a new `RangeIndex`. Never sort, drop, duplicate, or fill observations. The input index has no role in identifying observations and remains unchanged. The financial output columns use finite float64 values; timestamps retain the source's coherent naive or aware clock.

## Exact summary and deterministic episode selection

Return a separate one-row DataFrame, indexed `GROSS` or `NET` according to the explicitly called wrapper, with exactly these eight fields in order:

| Field | Meaning | Dtype |
| --- | --- | --- |
| `max_portfolio_drawdown` | Minimum, most negative, path drawdown | float64 |
| `max_portfolio_drawdown_amount` | Currency decline at the selected trough | float64 |
| `peak_observation` | Associated peak's observation ordinal | int64 |
| `trough_observation` | Selected trough's observation ordinal | int64 |
| `peak_valuation_time` | Associated peak's supplied time | Coherent datetime |
| `trough_valuation_time` | Selected trough's supplied time | Same coherent datetime clock |
| `peak_equity` | Associated peak's equity | float64 |
| `trough_equity` | Selected trough's equity | float64 |

“Maximum drawdown” means the largest decline, numerically the **minimum** drawdown, not Python's maximum. Select its episode as follows:

1. If several observations attain the exact minimum unrounded percentage drawdown, select the **earliest trough** in supplied order.
2. The associated peak value is that trough's `running_peak`. Among observations at or before that trough with equity exactly equal to that peak, select the **most recent peak occurrence**.

All summary trough fields, including the currency amount, come from that same trough. Do not separately minimize currency drawdown: its most negative value can belong to a different episode. Peak fields come from the selected associated peak. Comparisons use exact calculated/source values without tolerances or rounded display values.

For `100 → 120 → 120 → 100`, trough observation 3 is associated with peak observation 2, not observation 1. For `100 → 80 → 100 → 80`, the tied minimum selects trough 1 and peak 0. These rules establish an unambiguous episode origin for possible future duration metrics without calculating duration now.

For a flat or increasing path, every drawdown is zero. The earliest minimum is observation 0; its associated peak is also observation 0. Both summary drawdown fields are `0.0`, both ordinals are 0, both times are the initial supplied time, and both equity values are the initial equity. The same rule applies to an initial-only path.

## Worked synthetic example

These values illustrate the contract, not BTC results. Displayed decimals are rounded for readability only.

| Observation | Equity | Running peak | Drawdown | Drawdown amount |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1,000 | 1,000 | 0.0 | 0 |
| 1 | 1,100 | 1,100 | 0.0 | 0 |
| 2 | 900 | 1,100 | -0.1818181818 | -200 |
| 3 | 1,200 | 1,200 | 0.0 | 0 |
| 4 | 1,000 | 1,200 | -0.1666666667 | -200 |

The maximum portfolio drawdown is approximately **−18.181818%**, from peak observation 1 (equity 1,100) to trough observation 2 (equity 900). The summary amount is −200 from observation 2. Equal currency declines can have different percentage declines because their running peaks differ.

## Edge cases

| Supplied equity path | Required result |
| --- | --- |
| `1,000` only | One unchanged initial observation; zero drawdown/amount and initial-point summary. Canonical Stage 5.11 paths normally have at least two rows, but this minimum valid input is supported. |
| `1,000 → 1,000 → 1,000` | Flat; maximum drawdown zero, summary peak/trough both observation 0. |
| `1,000 → 1,100 → 1,200` | Increasing; maximum drawdown zero, summary peak/trough both observation 0. |
| `1,000 → 900` | First-CLOSE loss captured: `-0.10`, amount −100. |
| `1,000 → 0` | Full loss: `-1.0` (−100%), amount −1,000. The positive historical peak prevents division by zero. |
| `1,000 → 800 → 1,000` | Recovery gives current drawdown zero; historical minimum remains `-0.20`. |
| `1,000 → 800 → 1,200` | New high updates running peak to 1,200 and current drawdown to zero; historical minimum remains `-0.20`. |
| Repeated exact minimum drawdowns | Earliest trough wins. |
| Repeated exact equal running peaks before that trough | Latest peak at or before the selected trough wins. |

No trade input is needed to handle any of these cases. An empty path is invalid because it has no initial reference.

## Future validation and preservation

Validate only the equity-path contract:

- Require a pandas DataFrame with unique column names, all three required fields even before checking values, and at least one row.
- Require canonical integer observations exactly `0, 1, ..., len(path) - 1` in supplied order, representable as int64. Reject bool/np.bool_, floats, strings, missing, duplicate, negative, skipped, or reordered ordinals. Do not derive observation numbers from index labels or silently repair them.
- Require valid, non-missing, safely representable datetime valuation times, strictly increasing without duplicates. Preserve one coherent clock: all naive or all aware with matching timezone implementation/zone, as in the equity layer. Same-zone DST offset changes are valid when actual elapsed time increases. Reject mixed clocks, incompatible zones/implementations, strings, numeric epochs, missing/unsafe times; never parse, localize, convert, or strip timezones.
- Require finite real numeric equity, rejecting bool/np.bool_, strings, complex, missing, NaN, infinity, and unsafe float64 conversion. Initial equity must remain strictly positive; later equity may be zero but never negative under the current long-only spot model.
- Require all computed financial fields to remain finite and representable as float64. With a positive initial reference, every running peak is positive, including after equity reaches zero.

Do not require `candle_interval`, infer an hourly duration, enforce equal spacing, or revalidate candle/event/fee/accounting rules. Timing has already been established upstream; this layer checks the supplied clock and chronology. Extra columns remain irrelevant, including any position/trade fields.

All four public helpers must be pure. Return new DataFrames and preserve every input value, row, dtype, column order, and index. Do not sort, reset the input index, mutate columns, repair values, rebuild upstream data, or perform file/network I/O.

## Realized drawdown and final OPEN semantics

Decision 004 and `src/trading_lab/analytics/drawdown.py` remain unchanged:

| Metric | Observation population | Final OPEN |
| --- | --- | --- |
| Realized-capital drawdown | Initial capital plus one canonical capital-after point per CLOSED trade | Excluded and unvalued |
| Candle-close portfolio drawdown | Supplied initial equity plus every supplied candle-CLOSE equity observation | Its existing marked equity is naturally included |

Do not replace or rename the realized-capital metric, add fields to its output, or claim both metrics observe the same population. Candle-close equity can expose losses while positions are held, which realized-capital observations can miss.

Drawdown does not inspect trade status, exclude OPEN rows, value a position, or force a closing fill. It includes every supplied equity observation, including the final OPEN mark already produced by the equity layer. Future exits known in historical accounting must not influence earlier equity/drawdown. No special final-OPEN handling or hypothetical exit costs belong here.

## Candle-CLOSE risk limitation

This is **CANDLE-CLOSE PORTFOLIO DRAWDOWN**, not continuous-time or tick-level maximum drawdown. Suppose previous-CLOSE equity is 10,000, equity briefly reaches 7,000 within the next candle, and its CLOSE equity is 9,500. The observed path `10,000 → 9,500` shows about −5%; it cannot see the temporary 7,000. Other earlier peaks could change the observed ratio, but cannot reveal that missing intrabar point.

HIGH/LOW cannot reconstruct the exact portfolio time path and must not be used to repair or enrich this path. MAE/MFE, intrabar excursions/stress, and tick-level risk remain separate future work.

## Finalized future API and implementation location

Future module: `src/trading_lab/analytics/portfolio_drawdown.py`. Do not create it during this contract stage. Finalize these four functions, each taking only the corresponding equity-path DataFrame and returning a DataFrame:

```python
calculate_gross_portfolio_drawdown(gross_equity_path)
calculate_net_portfolio_drawdown(net_equity_path)
summarize_gross_portfolio_drawdown(gross_equity_path)
summarize_net_portfolio_drawdown(net_equity_path)
```

The calculate functions return the exact six-column path; the summarize functions return the exact eight-field summary. Summaries reuse the validated path calculation. A small private implementation may share validation and mathematics; no classes or generic framework are needed. Do not introduce an initial-capital parameter or attempt source guessing from identical schemas. These APIs are defined but do not exist yet.

## Deferred work and next milestone

Stage 5.13 changes documentation only. Do not change production code, tests, notebooks, raw data, dependencies, or decisions 001–006. Do not calculate or hardcode BTC portfolio drawdown. Run the unchanged existing 304-test suite to verify preservation; do not commit automatically.

No extra summary fields or calculations for drawdown duration, time under water, recovery duration, average drawdown, Ulcer Index, Calmar, Sharpe, Sortino, volatility, equity returns, CAGR, benchmark comparison, alpha/beta, MAE/MFE, intrabar drawdown, rolling drawdown, leverage, or liquidation are included.

Recommended next: **Stage 5.14 — Reusable Candle-Close Portfolio Drawdown Implementation**, only after owner approval. Future tests should cover exact path/summary schemas and dtypes, initial-point retention and initial-only input, the worked example, flat/increasing paths, first-CLOSE loss, zero equity/full loss, recovery/new highs, earliest-trough/latest-peak ties, associated currency amount versus an independent minimum amount, prefix causality/no lookahead, independent GROSS/NET calls, invalid schemas/observations/times/timezones/equity, complete input preservation, real Stage 5.11 equity integration, and natural final-OPEN inclusion. No tests are added now; BTC measurement follows implementation, not this contract stage.
