# 003 — CLOSED-trade performance metrics

- Date: 2026-10-03
- Status: Accepted
- Scope: Stage 5.1 metric contract only; analytics functions are not implemented.
- Related decisions: [001 — Initial architecture](001_initial_architecture.md), [002 — Backtesting execution contract](002_backtest_execution_contract.md).

## Context and population

Stage 4.5 produces a trade ledger; Stages 4.6 and 4.7 independently account for the same trades. Stable metric definitions will let Stage 5.2 produce reproducible summaries across notebooks and future strategies without changing those accounting layers.

Every performance statistic below uses rows with `status == "CLOSED"` only. OPEN rows do not enter counts, rate denominators, averages, extrema, realized PnL, expectancy, or profit factor. Their entry fees are also excluded from these CLOSED-trade statistics. An optional future `open_trade_count` is context only, outside the core summary. Never mark an OPEN trade to market or invent a closing fill.

Use the existing accounting outputs as inputs; do not recalculate returns, sizing, PnL, or costs. Their ledger ordering, pairing, and validation assumptions remain unchanged. CLOSED source returns and PnL must be finite numeric values; missing/invalid CLOSED values are errors, not observations to silently drop or fill. Expected missing realized fields on OPEN rows are excluded with those rows. Summaries must preserve their inputs and must not infer a source from a shared column name.

## Independent sources of truth

| Summary | Accounting source | Return column | PnL column | Capital context |
| --- | --- | --- | --- | --- |
| GROSS | Stage 4.6 `calculate_trade_results(...)` | `trade_return` | `gross_pnl` | `capital_before`, `capital_after` |
| NET | Stage 4.7 `calculate_trade_results_with_costs(...)` | `net_trade_return` | `net_pnl` | `capital_before`, `net_capital_after` |

**Stage 4.7 `gross_pnl` is not the canonical gross strategy result.** It uses the cost-aware quantity, which differs from the independent Stage 4.6 zero-cost sizing path. Both summaries start from the same ledger and initial capital, but each path compounds its own results. Never mix their returns, PnL, or capital columns, or classify net trades using gross returns.

Returns normalize outcomes relative to capital, so they govern classification and return comparisons. PnL measures realized quote-currency outcomes on the actual compounded sizing path, so it governs total PnL, expectancy, and profit factor. Return/rate values are dimensionless decimal fractions (`0.40 = 40%`); PnL and expectancy use quote currency, currently USDT. Profit factor is dimensionless. Capital context is not a new metric in this stage.

## Classification and tolerance

For each CLOSED trade, let `r` be its selected source return and `p` its selected source PnL. Define the fixed dimensionless convention **`BREAKEVEN_TOLERANCE = 1e-12`**:

| Class | Rule |
| --- | --- |
| WIN | `r > +1e-12` |
| LOSS | `r < -1e-12` |
| BREAKEVEN | `abs(r) <= 1e-12` |

The boundaries `-1e-12` and `+1e-12` are BREAKEVEN. Classify full-precision source returns, before any display rounding. Return is canonical; PnL sign should normally agree because capital is positive. The tolerance is not a quote-currency PnL threshold and does not rewrite source values.

For example, with an entry price of 100, exit price of 100.1, zero slippage, and a research fee of 0.001 per side, the zero-cost gross return is approximately `+0.001` (WIN), while the self-financing net return is approximately `-0.001` (LOSS). Gross/net win rates, average wins/losses, profit factors, and expectancy must therefore be calculated independently.

## Core future summary and formulas

Let `N` be the number of CLOSED trades; `W`, `L`, and `B` are their WIN, LOSS, and BREAKEVEN subsets under the selected source return. The following 16 names define the core Stage 5.2 summary, without choosing a framework or implementing a function:

| Metric | Definition | Empty/subset behavior |
| --- | --- | --- |
| `closed_trade_count` | `N` | Integer 0 when no CLOSED trades |
| `winning_trade_count` | Number in `W` | Integer 0 when no wins |
| `losing_trade_count` | Number in `L` | Integer 0 when no losses |
| `breakeven_trade_count` | Number in `B` | Integer 0 when no breakevens |
| `win_rate` | `winning_trade_count / N` | NaN if `N == 0` |
| `loss_rate` | `losing_trade_count / N` | NaN if `N == 0` |
| `breakeven_rate` | `breakeven_trade_count / N` | NaN if `N == 0` |
| `average_trade_return` | Arithmetic mean of all CLOSED `r` | NaN if `N == 0` |
| `median_trade_return` | Median of all CLOSED `r`; mean of the two middle values for even `N` | NaN if `N == 0` |
| `average_win_return` | Arithmetic mean of `r` in `W` only | NaN if `W` is empty |
| `average_loss_return` | Arithmetic mean of `r` in `L` only; remains negative | NaN if `L` is empty |
| `best_trade_return` | Maximum CLOSED `r` | NaN if `N == 0` |
| `worst_trade_return` | Minimum CLOSED `r` | NaN if `N == 0` |
| `total_realized_pnl` | Sum of all CLOSED `p` | 0.0 for the empty sum |
| `expectancy_pnl` | Arithmetic mean of all CLOSED `p` | NaN if `N == 0` |
| `profit_factor` | WIN PnL sum divided by absolute LOSS PnL sum | Cases below |

Average trade return is the arithmetic outcome of one CLOSED trade, not compounded strategy return, annualized return, geometric mean, or portfolio return. Average win/loss excludes BREAKEVEN trades. Best/worst uses return rather than absolute PnL because compounded position sizes differ. Best remains negative in an all-loss sample; worst remains positive in an all-win sample. No trade-ID tie rule is needed because this summary returns values, not IDs.

Total realized PnL uses Stage 4.6 `gross_pnl` for GROSS and Stage 4.7 `net_pnl` for NET. Expectancy is descriptive sample realized PnL per CLOSED trade, not a forecast or statistically guaranteed future profit. Do not add `expectancy_return`; it would duplicate `average_trade_return`.

Breakeven classification does not round or zero source returns/PnL. Such residuals remain in all-trade means, median, extrema, total realized PnL, and expectancy. Only the profit-factor aggregation gives BREAKEVEN trades zero contribution.

## Profit factor

Use selected-source PnL with the return-based class masks:

```text
positive_pnl_sum = sum(p for WIN trades)
absolute_negative_pnl_sum = abs(sum(p for LOSS trades))
```

BREAKEVEN trades contribute zero to both sums, even if their source PnL has a tiny residual. Do not select the subsets using raw PnL sign instead of the canonical return classification. Conventional names `gross_profit` / `gross_loss` mean these same aggregates; in a NET summary they aggregate NET PnL, not Stage 4.6 values.

| Eligible PnL aggregates | `profit_factor` |
| --- | --- |
| Positive numerator and positive loss magnitude | `positive_pnl_sum / absolute_negative_pnl_sum` |
| Positive numerator, zero loss magnitude | `+infinity` |
| Zero numerator, positive loss magnitude | `0.0` |
| Both aggregates zero: all breakeven, no CLOSED trades, or zero eligible PnL | NaN |

Preserve mathematically meaningful NaN and infinity. Do not substitute an arbitrary finite value, add an epsilon to the denominator, or apply the dimensionless return tolerance to these currency sums.

## Empty and degenerate populations

| CLOSED population | Required behavior |
| --- | --- |
| Zero CLOSED trades, including OPEN-only input | Four counts 0; total realized PnL 0.0; all rates, return statistics, expectancy, and profit factor NaN |
| Only wins | Rates 1/0/0 for win/loss/breakeven; average loss NaN; profit factor `+infinity` when positive PnL exists |
| Only losses | Rates 0/1/0; average win NaN; profit factor 0.0 when negative PnL exists |
| Only breakevens | Rates 0/0/1; average win/loss NaN; profit factor NaN; other statistics use the unmodified source values, which may contain small residuals |
| One CLOSED trade | All-trade mean, median, best, and worst equal its return; total PnL and expectancy equal its PnL; class rates and profit-factor edge case follow the rules above |
| CLOSED trades plus a final OPEN trade | Same CLOSED metrics as when that OPEN row is omitted; OPEN stays unvalued |

## Stage 5.2 validation invariants

- `closed_trade_count = winning_trade_count + losing_trade_count + breakeven_trade_count`.
- For `N > 0`, each rate is in `[0, 1]` and `win_rate + loss_rate + breakeven_rate ≈ 1`.
- For `N > 0`, `expectancy_pnl ≈ total_realized_pnl / closed_trade_count`.
- With positive numerator and loss magnitude, profit factor equals their ratio within floating-point tolerance.
- OPEN rows do not change any CLOSED statistic; missing OPEN realized fields must not contaminate the summary.
- Test exact tolerance boundaries and values on either side; display rounding must not affect classification.
- Cover empty, all-win, all-loss, all-breakeven (including residual PnL), single-trade, and CLOSED-plus-OPEN cases.
- Costs may change a gross WIN to a net LOSS; classify each path independently. Do not require every net rate, ratio, subset average, or count to be lower than its gross counterpart; these statistics can change non-monotonically.
- Do not modify inputs or silently omit malformed CLOSED financial values.

These are future acceptance cases, not new tests or claims that analytics has been implemented.

## Deferred work and next milestone

Stage 5.1 does not define or implement realized-capital/max drawdown, trade duration, exposure/time in market, benchmark return, alpha, beta, Sharpe, Sortino, volatility, annualization, candle-level equity, mark-to-market/unrealized PnL, CAGR, Calmar ratio, parameter optimization, out-of-sample testing, or walk-forward testing. They require later substages or strategy validation.

After approval, Stage 5.2 may implement a small reusable CLOSED-trade summary under `src/trading_lab/analytics/`, using explicit gross/net source selection and focused tests for this contract. Existing accounting functions remain unchanged; no complete analytics framework is needed. Do not begin Stage 5.2 during this documentation stage.
