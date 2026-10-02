# 002 — Backtesting execution contract

- Date: 2026-10-02
- Status: Accepted
- Scope: Stage 4.1 contract for the first long-only historical execution model. No execution helper, backtest engine, or PnL implementation is introduced.
- Related decision: [001 — Initial architecture](001_initial_architecture.md).

## Context

Stage 3.1 produces completed-candle EMA signals and `desired_position`. Future historical execution needs a precise timing convention so research intent cannot be mistaken for a fill. This decision fixes that boundary before a backtest is implemented.

## Core terms

| Term | Meaning |
| --- | --- |
| `signal` | Strategy event: LONG_ENTRY, LONG_EXIT, or HOLD. |
| `desired_position` | Strategy intent after a completed candle: 0 wants flat, 1 wants long. It is not a fill or an executed position. |
| `signal_time` | Time when the completed candle's final close and resulting signal become available; for hourly candle N, its opening timestamp plus one hour. |
| `execution` | A future simulated action applying a valid signal at the next candle's open and changing the simulated position. |
| `executed_position` | The simulated state after an execution: 0 flat or 1 long. It belongs to backtest execution, not strategy generation. |
| `execution_time` | Opening timestamp of candle N+1, if that candle exists and an event is executable. |
| `execution_price` | OPEN of candle N+1. Its high, low, close, and volume must not influence this fill. |

These define the future model; executed positions and execution prices are not currently calculated or stored.

## Execution timing

The first model executes a valid signal from candle N at **OPEN of the immediately following candle N+1**. Never use the close of candle N as its execution price. Use validated, chronologically ordered, continuous hourly OHLCV data; do not silently skip a missing hour to fill on a later available row.

| Step | Time in the example | Information or action |
| --- | --- | --- |
| Candle N opens | 12:00 UTC | Its final close and EMA signal are not known. |
| Candle N finishes | 13:00 UTC | Its close is known; the signal becomes available at `signal_time`. |
| Candle N+1 opens | 13:00 UTC | The model applies the valid signal at that candle's OPEN; this is `execution_time`. |

For continuous hourly candles, signal_time and execution_time have the **same boundary timestamp**, but describe different events. Do not add another hour after signal_time: the one-candle delay is from candle N's opening label to candle N+1's opening label. Causal order is candle completion, signal availability, then execution at the next open.

This is an explicit idealized boundary-fill convention, not a claim about a guaranteed live exchange fill. Same-close execution would assume a fill at the already completed price needed to generate the signal, without establishing that an order could have existed before that price was known. That would introduce look-ahead bias in this model. A different timing model would require an explicit later decision.

## Initial state and long-only rules

Initial `executed_position = 0`. There is no simulated entry before the first successfully executable LONG_ENTRY. At each future candle open, apply any valid event scheduled by the preceding completed candle before evaluating the new candle's eventual close.

| Signal from candle N | Required executed state | Action at N+1 OPEN | Resulting executed state |
| --- | --- | --- | --- |
| LONG_ENTRY | 0 (flat) | Simulated entry | 1 (long) |
| LONG_EXIT | 1 (long) | Simulated exit | 0 (flat) |
| HOLD | 0 or 1 | No execution; no execution time or price | Unchanged |

The execution layer must validate its own state. An entry while already long or an exit while flat is an invalid event: reject it clearly rather than fabricate an execution. Do not reinterpret strategy intent, create shorts, or add sizing or leverage. A desired-state change alone is not evidence that execution occurred.

Stage 3.1 remains unchanged: the first 50 candles are initialization-only, signals become eligible on candle 51, entries require previous desired state 0, exits require previous desired state 1, and HOLD preserves desired state. Consequently no warm-up event is scheduled for execution.

## Final-candle edge case

A signal on the last available candle may exist and may change `desired_position`. Without candle N+1, there is no available next open: no execution, execution time, or execution price exists for that signal. Leave `executed_position` unchanged. Do not invent a price or force-open or force-close because the dataset ended. Any previously executed long state remains long in this conceptual model; no terminal valuation is introduced.

## Layer boundary

```text
Market Data → Strategy → Signal / desired_position
                               ↓
                       Backtest Execution
                               ↓
                        executed_position
```

Strategy generation answers what position is wanted. Backtest execution answers when and at what price a valid event can be simulated. Keep any later timing helper under `src/trading_lab/backtest/`; strategies must not simulate fills or call exchanges. Exchange-specific code remains in the exchange layer.

## Validation cases for a future helper

| Case | Input or check | Required outcome |
| --- | --- | --- |
| A | LONG_ENTRY on N while flat, with N+1 available | Execute at N+1 timestamp/OPEN; state 0 → 1. |
| B | LONG_EXIT on N while long, with N+1 available | Execute at N+1 timestamp/OPEN; state 1 → 0. |
| C | HOLD | No execution; executed state unchanged. |
| D | Event on final candle | Preserve the signal and desired state; no execution or invented time/price. |
| E | Change N+1 high/low/close/volume or any later candles | The event's execution time, price, and transition remain unchanged; only N+1 timestamp/OPEN is used for the fill. |
| F | First 50 initialization candles | HOLD only; no scheduled or actual execution. |
| G | Entire event sequence | Initial state 0; executed state always in {0, 1}; reject invalid state transitions. |

These are documented acceptance cases, not claims that execution code has been tested. Stage 4.1 adds no helper or new tests. Existing market-data tests should continue to pass, and the Stage 3.1 notebook and raw CSV must remain unchanged.

## Consequences and deferred work

The execution convention is explicit and reusable across future strategy backtests while preserving the existing strategy/execution separation. Desired and executed states may differ, especially for an unexecutable final-candle signal.

There is no backtest loop, PnL, capital, equity curve, trade ledger, fees, slippage, commissions, trade returns, performance analytics, position sizing, risk engine, or exchange execution in this stage. Stage 4.2 may implement a small pure timing/state helper and tests for the cases above, after approval.
