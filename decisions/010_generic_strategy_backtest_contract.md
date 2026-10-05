# 010 — Generic strategy / backtest contract

- Date: 2026-10-05
- Status: Accepted
- Scope: Stage 6.1 contract only; no validator, generic pipeline, wrapper, or production refactor is implemented.
- Related decision: [002 — Backtesting execution contract](002_backtest_execution_contract.md), whose timing and executed-state rules remain unchanged.
- Regression baseline: `a3fde091be234fd78d216f6338752a810fa117f0` — `Complete Stage 5 analytics report`.

## Context and decision

Stage 5 — Analytics is complete. The existing stack generates EMA intent, applies next-candle-OPEN execution, builds a trade ledger, calculates independent GROSS/NET accounting, and evaluates trades/equity. Its orchestration, `run_ema_execution_pipeline(...)`, still calls `generate_ema_signals(...)` internally.

Future strategies must feed the same execution and downstream infrastructure without that infrastructure knowing their indicators or parameters. Use the existing simple design: pure strategy function → pandas DataFrame contract → generic functions. Do not introduce strategy base classes, registries, factories, plugin or dependency-injection frameworks, event buses, or async runtimes.

Stage 6 retains one long-only spot position, desired state 0/1, and no leverage. Genericization must not change existing EMA trading behavior or historical financial results.

## Layer responsibilities

| Layer | Owns |
| --- | --- |
| Strategy | WHAT position state is wanted after a completed candle; indicator logic and warm-up. |
| Execution | WHEN a valid event becomes a fill and its recorded market price; actual executed state. |
| Accounting | Quantity, capital, modeled fees/slippage, realized PnL, and accounting state. |
| Analytics | Evaluation of the resulting trades and equity using the existing Stage 5 helpers. |
| Future Stage 7 risk manager | HOW MUCH capital/risk may be used; deferred, with no implementation here. |

A strategy must not call an exchange, calculate unrestricted order quantity, choose leverage, calculate fees/PnL/drawdown/Sharpe/Sortino, or mutate portfolio accounting state. Exchange-specific code does not belong in a strategy or the generic backtest layer.

## Canonical strategy output

The strategy returns a new DataFrame containing at least these four uniquely named columns. All four names already exist in `src/trading_lab/strategies/ema_trend.py`; no EMA rename is required.

| Required field | Meaning and validation |
| --- | --- |
| `timestamp` | Source candle timestamp, aligned exactly with the supplied candle. Current candles are labeled by their OPEN time. |
| `signal_time` | First availability of this completed-candle decision: `timestamp + candle_interval`. Every row, including HOLD and the final row, carries this time. |
| `signal` | Exactly `LONG_ENTRY`, `LONG_EXIT`, or `HOLD`; no missing values or aliases. |
| `desired_position` | Integer `0` (FLAT) or `1` (LONG), representing intent AFTER processing this completed candle. Missing values, bools (including NumPy bools), floats such as `1.0`, strings, and other values are rejected without coercion. |

There is no SHORT, target quantity, leverage, execution price, or accounting state in the minimum strategy contract. The full strategy column order is not prescribed: existing EMA places diagnostic columns between canonical fields and already conforms to these names/semantics.

For the current model, `candle_interval` is one hour. The availability formula documents the fixed-interval convention; it does not add interval configuration to existing APIs or claim that the current hourly execution helper supports other intervals. Timestamp and signal-time columns must already be pandas datetime columns with no missing values. Preserve their existing datetime/timezone semantics: no string parsing, timezone conversion, or conversion of naive timestamps to aware timestamps. `signal_time` must equal the corresponding timestamp plus the model interval, not an independently chosen execution time.

### Strategy-specific extra columns

Strategies may return diagnostic/research columns, for example EMA values and crossover flags, breakout levels, or z-scores. Current EMA uses `ema_{fast_span}`, `ema_{slow_span}`, `warmup_complete`, `bullish_cross`, and `bearish_cross`; defaults retain `ema_20`/`ema_50`. These names and their contents are not requirements for other strategies.

The generic layer ignores extra columns when validating intent or deciding execution. Only canonical fields control generic strategy validation, and recorded fill prices come from supplied market candles. Extra fields cannot override market OPEN prices, signals, or execution/accounting state. In particular, the future pipeline supplies `timestamp`/`open` from candles and the validated canonical `signal` to the existing execution helper; it does not pass diagnostics as execution instructions. It must not require or inspect EMA spans, moving averages, crossovers, breakout levels, z-scores, indicator names, or strategy parameters.

## Row and candle alignment

The strategy output and supplied candles must be DataFrames with unique column names and the required fields. Alignment is positional and strict, before pandas could silently align assignments:

- Exactly one output row per supplied candle, in the same order; no extra, missing, or duplicate candle timestamps.
- Preserve the supplied candle index and its label order. Follow the current pipeline's `strategy_output.index.equals(candles.index)` check; do not reset or replace the index.
- Follow its `strategy_output["timestamp"].equals(candles["timestamp"])` check, retaining the supplied datetime dtype/timezone representation as well as values.
- Timestamps must be non-missing, unique, and chronological. Index labels need not be increasing or form a RangeIndex; chronological order comes from timestamps. Do not add an index-uniqueness requirement unrelated to the supplied candle index.
- Never sort, reindex, silently realign, fill, parse, or repair malformed output.

Existing empty-input behavior is retained: an aligned empty output with the required typed columns is valid and produces no events. A single HOLD row is valid. No minimum warm-up or minimum number of rows belongs to the generic contract.

Full OHLCV/price validation remains upstream. The existing execution layer continues to own continuous one-hour spacing, actual fill OPEN validation, and executed-state transitions. The generic strategy validator owns canonical fields, alignment, availability, and desired-state consistency; it does not duplicate candle-loader, ledger, accounting, or analytics validation.

## Desired-state transitions

Initial strategy state BEFORE the first row is FLAT (`0`). On each row, validate its signal against the preceding row's desired state, then require its `desired_position` to equal the resulting state:

| Previous desired state | Signal | Required current desired state | Valid? |
| --- | --- | --- | --- |
| 0 | HOLD | 0 | Yes |
| 0 | LONG_ENTRY | 1 | Yes |
| 0 | LONG_EXIT | — | No: exit while flat. |
| 1 | HOLD | 1 | Yes |
| 1 | LONG_EXIT | 0 | Yes |
| 1 | LONG_ENTRY | — | No: entry while long. |

HOLD cannot change state; duplicate entries and exits while flat are invalid. These checks also apply to the final row even when it cannot execute. A first-row LONG_ENTRY is structurally valid if the strategy legitimately produces it; its fill still needs a next candle.

Warm-up belongs to each strategy. EMA's existing default first 50 initialization-only candles, eligibility from candle 51, and crossover/state behavior stay unchanged. Do not make 50 candles, EMA indicators, or any warm-up requirement an engine rule.

## Timing and intent versus execution

Preserve decision 002: candle N completes → its strategy decision becomes available → a valid event may fill at OPEN of the immediately following candle N+1. Never execute at candle N's CLOSE. Do not skip a missing hour to use a later available row or allow a strategy-specific timing bypass.

For continuous hourly candles, `signal_time[N]` and `timestamp[N+1]` share the boundary timestamp. Completion and availability precede execution conceptually; do not add another hour after `signal_time`. This is the existing idealized historical boundary-fill model, not a guaranteed exchange fill.

`desired_position` expresses intent after N completes. `executed_position` on row N is the actual simulated position DURING N, after any preceding event filled at N's OPEN. The execution layer starts FLAT independently and validates its own transitions. These states can differ because N's intent cannot fill before N+1 OPEN.

For example, a LONG_ENTRY on N changes desired state 0 → 1 while executed state during N remains 0; at N+1 OPEN it becomes 1. Preserve existing storage: `execution_time`/`execution_price` on signal row N describe its N+1 fill, while `executed_position` changes on row N+1. The entry price is N+1's recorded raw OPEN; that candle's HIGH/LOW/CLOSE/volume must not determine the fill.

### Final supplied candle

A valid final-row transition may change intent but has no next OPEN and therefore no fill. Leave its execution time/price missing and its executed state unchanged; reject structurally invalid final-row transitions as usual. Never fabricate a price, force an entry/exit, or close a position just because the dataset ends. A previously executed long remains OPEN in the ledger. Any existing Stage 5 marking of that position is valuation, not an invented execution.

## Causality and preservation

Strategy output row i may use only information available from candle i and earlier when i completes, subject to its own warm-up. It cannot use candle i+1 or later. Causality belongs to the strategy: a generic validator cannot mathematically prove an arbitrary function causal from one output DataFrame. Each strategy's tests must include causal-prefix checks, as the existing EMA tests do, without duplicating indicator logic in the engine.

Execution must not feed future information into strategy decisions. It uses the next timestamp/OPEN only for the scheduled fill, never later prices to improve that fill. Appending a next candle may legitimately populate the formerly final signal row's execution metadata; it must not change that row's strategy intent or executed state during the row, or any earlier execution results. Existing pipeline prefix tests document this distinction.

All functions must preserve supplied candle and strategy DataFrames, including diagnostic columns. Produce independent outputs. Fail with explicit `ValueError` messages identifying the malformed field, alignment, or transition; no implicit coercion or repair. A canonical valid output may still fail the execution layer's own market/state checks.

## Future generic orchestration

The intended direction, not an implemented API, is:

```text
strategy_output = strategy_function(candles, ...)
                         ↓
validated canonical strategy output aligned to candles
                         ↓
generic execution pipeline (no EMA generation or indicator logic)
                         ↓
existing apply_next_open_execution(...)
                         ↓
existing build_trade_ledger(...)
                         ↓
existing independent gross / net accounting
                         ↓
existing Stage 5 analytics
```

Later, a thin EMA compatibility wrapper may call the unchanged `generate_ema_signals(...)` and delegate to that generic pipeline. Do not implement it or change `run_ema_execution_pipeline(...)` in Stage 6.1. No new public function signature or generic combined-output schema is introduced by this decision.

`src/trading_lab/strategies/ema_trend.py` remains the canonical EMA implementation. Do not move or duplicate it or add reusable code under the top-level legacy `strategies/` directory. Future strategy files may live under `src/trading_lab/strategies/`, but no new strategy is added now.

## Frozen EMA regression gate

Genericization must preserve Stage 5 execution, ledger, accounting, equity, and downstream analytics. The references below describe the existing BTC snapshot and established setup: hourly candles, EMA20/EMA50, 50-candle warm-up, initial capital 10,000 USDT, and NET research assumptions of fee rate `0.001` / adverse slippage rate `0.0005`. These rates are test assumptions, not current exchange fees.

| Baseline reference | Existing result |
| --- | --- |
| Candles | 8,760 |
| Executed entries / exits | 78 / 77 |
| CLOSED / OPEN trades | 77 / 1 |
| Last CLOSED GROSS realized capital | 9,641.111388344 USDT |
| Last CLOSED NET realized capital | 7,652.530163437 USDT |
| Final marked EMA GROSS equity | 9,451.485313939314 USDT |
| Final marked EMA NET equity | 7,490.776562851941 USDT |
| Final trade | Trade 78 remains OPEN, with no fabricated exit. |
| Existing test baseline | 458 tests; no new tests in Stage 6.1. |
| Frozen notebook 03 | 104 cells: 51 code / 53 Markdown, seven plots, sequential execution, no saved errors. |

These are future regression assertions only, never constants controlling production behavior. Compare EMA intent, row/index/timestamp alignment, fill timing/prices, executed state, ledger OPEN semantics, quantities/capital, and all downstream analytics with the frozen baseline, using existing numerical precision/tolerances rather than relaxing them to mask changed behavior. No new BTC calculation or notebook execution occurs in Stage 6.1.

## Synthetic acceptance cases for future validation

All cases assume otherwise aligned canonical output and valid hourly candles. They define future Stage 6.2/6.3 checks; no tests are implemented here.

| Case | Input or condition | Required outcome |
| --- | --- | --- |
| A | All HOLD from initial FLAT, all desired states 0 | Valid; no executions. |
| B | LONG_ENTRY → HOLD, desired states 1 → 1, from FLAT | Valid; first-row entry is permitted and needs a next OPEN to fill. |
| C | After a valid entry, LONG_EXIT → HOLD, desired states 0 → 0 | Valid; exit returns LONG to FLAT. |
| D | ENTRY / EXIT alternation, desired states 1 / 0 | Valid. |
| E | LONG_ENTRY while already LONG | Invalid, including on the final row. |
| F | LONG_EXIT while FLAT | Invalid, including on the final row. |
| G | HOLD changes desired state | Invalid. |
| H | LONG_ENTRY with desired 0, or LONG_EXIT with desired 1 | Invalid signal/state disagreement. |
| I | Timestamp differs from the corresponding supplied candle | Invalid alignment. |
| J | Missing, extra, duplicate-timestamp, or reordered rows; changed index | Invalid; never sort or realign. |
| K | Invalid or missing signal | Invalid; no aliases or filling. |
| L | Desired state outside integer {0,1}, missing, bool, float, or string | Invalid; no coercion. |
| M | Missing/non-datetime/incorrect signal_time | Invalid; availability must equal timestamp + one hour. |
| N | Valid transition on final supplied candle | Valid intent; no next OPEN means no fill, missing execution metadata, unchanged executed state. |
| O | Additional strategy diagnostics, or changed diagnostic values with unchanged canonical fields | Valid; generic validation/execution outcomes unchanged. |
| P | Aligned empty typed output, or a single HOLD row | Valid; no invented events or fills. |

Future tests should also cover missing/duplicate required columns, input preservation, non-RangeIndex alignment, datetime/timezone preservation, and strategy-specific causal prefixes. Preserve the existing lower-layer execution tests instead of duplicating indicator, accounting, or analytics tests in the generic validator.

## Deferred sequence and scope

| Stage | Milestone | Status after this decision |
| --- | --- | --- |
| 6.1 | Generic Strategy / Backtest Contract | Completed; documentation only. |
| 6.2 | Generic Strategy Signal Validation | Awaits owner approval; not started. |
| 6.3 | Generic Execution Pipeline | Deferred. |
| 6.4 | Generic End-to-End Backtest Integration | Deferred. |
| 6.5 | EMA Exact Regression / Compatibility | Deferred. |
| 6.6 | Generic Backtest Notebook | Deferred. |
| 6.7 | Final Stage 6 Audit | Deferred. |

Only decision 010 and the current README/PROJECT_STATE/CHANGELOG status are added or updated now. Production code, tests, notebooks, dependencies, data, and decisions 001–009 remain unchanged. The existing full test suite is the documentation-only verification gate; do not execute or modify frozen notebook 03.

No new strategy, risk manager, configurable sizing, leverage, shorts, multi-position/multi-asset portfolio, parameter optimization, walk-forward/out-of-sample testing, exchange/demo API, WebSocket, database/SQL persistence, web framework/dashboard, Docker, or VPS work belongs to Stage 6.1. Stage 6.2 is the only recommended next milestone and requires approval. Stage 7 has not started.
