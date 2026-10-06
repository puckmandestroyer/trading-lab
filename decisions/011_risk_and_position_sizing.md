# 011 — Risk and position sizing

- Date: 2026-10-06
- Status: Accepted
- Scope: Stage 7.1 contract only; sizing, accounting, equity, and pipeline changes are not implemented.
- Stage 6 compatibility baseline: `df72973de837ecbd4ee81f4bdaf77efd74730a56` — `Complete Stage 6 generic backtesting engine`.
- Frozen Stage 5 accounting/analytics baseline: `a3fde091be234fd78d216f6338752a810fa117f0`.
- Related decisions: [002 — Backtesting execution contract](002_backtest_execution_contract.md) and [010 — Generic strategy / backtest contract](010_generic_strategy_backtest_contract.md).

## Context and decision

Stage 6 is COMPLETE. Its generic pipeline accepts canonical strategy intent, validates it, applies next-OPEN execution, builds a ledger, and delegates independent GROSS/NET accounting. Optional analytics consume those outputs downstream. Accounting currently allocates all available capital at every executed entry. EMA20/50 remains the only reusable production strategy.

Stage 7 separates capital allocation policy from strategy intent and quantity calculation. Its only sizing model is a fixed `position_fraction`: the fraction of CURRENT portfolio capital permitted for each actually executed LONG entry. It is constant for one backtest run. Unallocated capital remains reserve cash in the same portfolio.

This is the first centralized risk layer's capital-allocation policy, not a complete operational risk manager. No production functionality is added in Stage 7.1.

## Responsibilities

| Layer | Owns |
| --- | --- |
| Strategy | Trading intent: when it wants LONG or FLAT. It continues to produce `timestamp`, `signal_time`, `signal`, and `desired_position` under Decision 010. |
| Risk / position sizing | HOW MUCH current portfolio capital is permitted for a new executed entry: a capital budget calculated from `position_fraction`. It does not calculate asset quantity. |
| Execution | Next-candle OPEN timing, recorded execution prices, fills, and `executed_position`. |
| Accounting | Converts the permitted budget into quantity, calculates costs/PnL, and compounds total portfolio capital independently for GROSS and NET. |
| Equity | Reconciles reserve cash plus marked position value while a position is OPEN; observes total cash while FLAT. |

Strategies must not choose capital allocation, quantity, fees, leverage, or portfolio exposure limits. Sizing must not modify signals, signal/execution timestamps, recorded execution prices, LONG_ENTRY/LONG_EXIT events, ledger pairing, or executed-position semantics. Strategy validation and execution do not validate `position_fraction`.

A risk policy knows current capital and the allocation fraction, so it can return a budget. Final quantity also depends on raw/effective entry price, slippage, and fees; those remain downstream accounting responsibilities. Do not move cost mathematics into the risk module.

## Position-fraction contract

`position_fraction` is a scalar finite real number satisfying `0 < position_fraction <= 1`, with default **`1.0`**.

| Input | Contract |
| --- | --- |
| `1`, `1.0`, `0.5`, `0.25` | Accepted: allocate 100%, 100%, 50%, or 25% respectively. |
| Zero, negatives, values greater than 1 | Rejected. |
| Python bool, NumPy bool, NaN, infinity, strings, None, complex values, non-scalars | Rejected without coercion or clamping. |

The upper bound forbids leverage or borrowing. Zero is excluded because Stage 7 does not implement trade veto or signal suppression: every valid executed entry must receive a positive budget. Invalid parameters fail explicitly; they must not silently turn an entry into HOLD or remove a trade.

The policy does not vary per candle, signal, strategy callback, or observed risk score. It does not rebalance an OPEN position to restore the fraction. An actual exit closes the existing position; the fraction applies again only at the next executed entry.

## Capital definitions and compounding

At an executed entry, `capital_before` (also called `portfolio_capital_before`) means total currently available portfolio capital before allocation, not just the position budget and not cash remaining after entry.

```text
position_budget = capital_before * position_fraction
reserve_cash = capital_before - position_budget
```

With 10,000 capital and fraction 0.50, the position budget is 5,000 and reserve cash is 5,000. Reserve is part of the same portfolio, not a second account. It stays outside the position and does not earn modeled interest.

Each new entry uses CURRENT capital after prior completed trades, not the original initial capital. If the portfolio grows to 10,500, the next 0.50 budget is 5,250, not 5,000. The fraction is fixed, but the absolute budget compounds. GROSS and NET use their own independently compounded current capital, so their budgets and quantities may differ.

## Planned GROSS accounting — Stage 7.3

The following formulas define future integration, not an implementation in this milestone:

```text
position_budget = capital_before * position_fraction
quantity = position_budget / entry_price
reserve_cash = capital_before - position_budget

gross_pnl = quantity * (exit_price - entry_price)
capital_after = capital_before + gross_pnl
exit_position_value = quantity * exit_price
capital_after = reserve_cash + exit_position_value
```

Raw ledger entry/exit prices remain unchanged. The next entry uses total `capital_after`, including reserve. Existing ledger validation and financial numerical checks remain accounting responsibilities.

## Planned NET accounting — Stage 7.4

Risk allocates a capital budget, not a quantity or a raw notional excluding fees. Existing adverse-slippage and self-financing fee conventions remain authoritative:

```text
position_budget = capital_before * position_fraction
reserve_cash = capital_before - position_budget
effective_entry_price = entry_price * (1 + slippage_rate)
effective_exit_price = exit_price * (1 - slippage_rate)

quantity = position_budget / (effective_entry_price * (1 + fee_rate))
entry_notional = quantity * effective_entry_price
entry_fee = entry_notional * fee_rate
entry_notional + entry_fee = position_budget

exit_notional = quantity * effective_exit_price
exit_fee = exit_notional * fee_rate
price_adjusted_pnl = quantity * (effective_exit_price - effective_entry_price)
total_fees = entry_fee + exit_fee
net_pnl = price_adjusted_pnl - total_fees
net_trade_return = net_pnl / capital_before
net_capital_after = capital_before + net_pnl
net_capital_after = reserve_cash + exit_notional - exit_fee
```

The budget includes the entry fee; reserve cash must not finance that fee a second time. Raw ledger prices remain unchanged, and cost-aware `gross_pnl` continues to use recorded prices with the NET-sized quantity. Fixed fee/slippage validation and economics remain in accounting. These formulas are not implemented in Stage 7.1.

## Planned equity and reserve cash — Stage 7.5

While LONG, portfolio equity is `reserve_cash + quantity * raw_close`, using the existing candle-close valuation clock. It is not the marked position alone. Reserve remains cash during the holding period; NET entry fees are already paid through the self-financing budget and must not be deducted again. Do not charge hypothetical exit fees or fabricate liquidation for an OPEN position. While FLAT after a real exit, the entire resulting portfolio capital is cash.

Example without costs: capital 10,000, fraction 0.50, entry price 100 gives quantity 50 and reserve 5,000. At mark 110, position value is 5,500 and portfolio equity is **10,500**. Treating equity as 5,500 would incorrectly discard reserve.

At fraction 1.0, reserve is zero and the existing all-in equity paths must be exactly preserved. Stage 7.5 extends the current all-in assumption; it must preserve existing valuation timing, schemas where safely possible, and downstream analytics. No equity code changes occur in Stage 7.1.

## OPEN trades and final unexecuted signals

An executed entry that remains OPEN has known `capital_before`, budget, reserve, and downstream quantity. NET also has its known entry-side accounting. Exit fields and realized results remain missing; incomplete round-trip `total_fees` stays missing. Equity may mark reserve plus the holding, but that mark is not a realized result. Never force a final close.

- Final LONG_ENTRY without N+1: no execution, no trade, and no sizing/allocation.
- Final LONG_EXIT without N+1: no exit fill; the existing position and its reserve remain OPEN.
- HOLD or a desired-state change alone is not an allocation trigger. Sizing attaches to ACTUAL EXECUTED ENTRY, not merely strategy intent.

The engine remains LONG/FLAT, one position at a time, with spot-style economics. No shorts, pyramiding, simultaneous positions, or multiple assets sharing capital are introduced.

## Planned APIs and validation ownership

Stage 7.2 production location is `src/trading_lab/risk/position_sizing.py`. Prefer a pure scalar helper without classes. Its first API concept is:

```python
calculate_position_budget(capital_before, position_fraction=1.0)
```

The exact name/signature may be finalized in Stage 7.2 after checking project conventions. Its behavior is a permitted positive capital budget, not quantity, fees, execution metadata, or an order. Neither this module nor function is created in Stage 7.1.

| Component | Planned validation ownership |
| --- | --- |
| Risk helper | Positive finite real `capital_before`, valid fraction, and a positive finite numerically representable budget. Reject bools and invalid numeric results, including unsafe conversion/product underflow to zero; do not clamp or invent a minimum allocation. |
| GROSS accounting | Ledger validity, quantity, GROSS financial calculations, and capital consistency. |
| NET accounting | Ledger validity, fee/slippage rules, self-financing quantity, and NET capital consistency. |
| Equity | Reserve cash plus marked-position reconciliation, with existing timing and valuation validation. |
| Pipeline | Parameter forwarding and orchestration only. |

The eventual Stage 7.6 API concept adds the parameter at the end:

```python
run_backtest_pipeline(
    candles,
    strategy_output,
    initial_capital=10_000.0,
    fee_rate=0.0,
    slippage_rate=0.0,
    position_fraction=1.0,
)
```

This parameter affects risk/accounting only; it must not affect strategy validation, signal generation, execution timing/prices, or ledger pairing. The current pipeline signature and its exact four keys (`execution`, `trades`, `gross_results`, `net_results`) are unchanged in Stage 7.1. No risk or equity object is added to the return contract here.

## Accounting schema policy

Prefer preserving the existing GROSS/NET schemas. `capital_before` continues to represent total portfolio capital; do not repurpose it as position budget. Reserve can conceptually be derived from canonical entry accounting:

```text
GROSS reserve = capital_before - quantity * entry_price
NET reserve = capital_before - (quantity * effective_entry_price + entry_fee)
```

Stages 7.3/7.4 must validate numerical reconciliation and existing return-field semantics explicitly. No new output columns or silent changes to field meaning are committed by this decision. If implementation proves an explicit field necessary, make an explicit reviewed decision before changing the schema.

## Analytics and terminology

Existing trade metrics consume accounting outputs; realized drawdown consumes `capital_after` / `net_capital_after`. Ledger duration and time exposure remain unchanged because fixed allocation does not change fills or holding periods. Risk-adjusted metrics consume the updated total-portfolio equity paths. Buy-and-Hold remains a separate benchmark; this policy does not alter its model.

`position_fraction` is a capital allocation fraction, not time exposure. A strategy invested for 50% of the year with fraction 0.25 allocates 25% of current capital while invested; these are different dimensions. Existing time exposure is not redefined as size-weighted exposure.

Do not describe fraction 0.25 as “risking 25%.” It allocates 25% to a position; actual loss depends on price movement and any future risk controls. Stage 7 has no stop loss or fixed loss-at-risk sizing.

In historical backtests, accounting applies the budget when converting an actual executed entry into a financial position. A future live/demo runtime may use the same policy to determine an allowed budget BEFORE submitting an order. No live integration or exchange concerns are added to the research backtester now.

## Hard backward-compatibility gate

At default `position_fraction=1.0`, Stage 7 must reproduce Stage 6 exactly: signals, executions, ledger, quantities, GROSS/NET results, equity paths, schemas/dtypes, and downstream analytics. Keep existing exact-frame checks and scalar tolerances; do not loosen them to accommodate changes. The budget equals all current capital and reserve is zero.

| Frozen local BTC reference | Required at fraction 1.0 |
| --- | ---: |
| Candles | 8,760 |
| ENTRY / EXIT signals and executed fills | 78 / 77 |
| Trades | 78 |
| CLOSED / OPEN | 77 / 1 |
| Last CLOSED GROSS capital | 9,641.111388344 USDT |
| Last CLOSED NET capital | 7,652.530163437 USDT |
| Final GROSS MTM | 9,451.485313939314 USDT |
| Final NET MTM | 7,490.776562851941 USDT |

These are regression references only, never production constants. The existing local BTC snapshot and frozen Stage 5 references remain authoritative. NET reference assumptions are fee rate 0.001 and adverse slippage rate 0.0005, not claims about current exchange fees. Stage 7.7 enforces full analytics compatibility and partial-allocation reconciliation.

## Accepted Stage 7 roadmap

| Milestone | Planned work | Status after Stage 7.1 |
| --- | --- | --- |
| 7.1 — Risk & Position Sizing Contract | Decision 011 and project documentation. | Completed; documentation/architecture only. |
| 7.2 — Position Sizing Core | Pure positive capital-budget helper. | Awaits explicit owner approval; not started. |
| 7.3 — GROSS Accounting Integration | Budget-based quantity and total-capital compounding. | Deferred; not started. |
| 7.4 — NET Accounting Integration | Budget-based self-financing quantity with existing costs. | Deferred; not started. |
| 7.5 — MTM Equity / Reserve Cash | Preserve reserve while marking OPEN positions. | Deferred; not started. |
| 7.6 — Generic Backtest Integration | Expose and forward `position_fraction`. | Deferred; not started. |
| 7.7 — Exact Regression + Analytics Compatibility | Fraction 1.0 exact Stage 6 gate and partial-allocation compatibility. | Deferred; not started. |
| 7.8 — Position Sizing Notebook | Educational comparison of allocation fractions. | Deferred; not started. |
| 7.9 — Final Stage 7 Audit + Docs | Final scope, regression, and documentation audit. | Deferred; not started. |

Stage 7.1 adds no tests. Run the existing 562-test suite once after the documentation is finished, plus `git diff --check`; do not execute notebooks. Future milestones must test their own numerical and integration contracts before advancing. Stage 7.2 is the only recommended next milestone and requires explicit approval.

## Out of scope and protected files

Stage 7 does not add short selling, leverage, margin, borrowing, stop loss, take profit, trailing stops, ATR/stop-distance sizing, volatility targeting, Kelly sizing, risk parity, portfolio optimization, multi-asset/multi-position or multi-bot capital allocation. It also excludes per-row fractions, per-signal risk scores, drawdown-dependent/adaptive risk, and strategy-specific sizing callbacks.

Trade veto, maximum daily loss, kill switches, portfolio risk aggregation, margin checks, exchange order limits, reconciliation, Bybit/live/demo runtime, databases, parameter optimization, walk-forward, and out-of-sample validation remain future work.

Stage 7.1 creates only this decision and updates `PROJECT_STATE.md`, `README.md`, and `CHANGELOG.md`. All production modules, tests, notebooks, decisions 001–010, requirements, and data remain unchanged. No dependencies, new strategy, production API, or sizing implementation are introduced; no commit is made automatically.
