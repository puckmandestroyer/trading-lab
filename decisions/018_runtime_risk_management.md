# 018 — Runtime Risk Management Contract

- Date: 2026-10-15
- Status: Accepted
- Scope: Stage 11.1 architecture/documentation only
- Owner-reviewed Stage 10 baseline: `87888719c3e2c87bd3b8979dd9c4ecc33db6cb65` — `Complete Stage 10 final audit`; COMPLETE / FROZEN.
- Governing decisions: [010](010_generic_strategy_backtest_contract.md), [011](011_risk_and_position_sizing.md), [012](012_strategy_robustness.md), [013](013_bybit_demo_exchange_adapter.md), [014](014_read_only_account_and_order_state.md), [015](015_spot_market_order_lifecycle.md), [016](016_manual_demo_smoke.md), [017](017_demo_trading_runtime_contract.md), all unchanged.

## Status and authority

This Accepted decision defines the contract for future staged implementation. It does **not** authorize production code, activation or an authenticated Demo operation. Each Stage 11 implementation milestone still requires explicit owner approval/review. Stage 11.1 is documentation only, COMPLETE / owner review pending; Stage 11 overall is INCOMPLETE. Stage 10 and all accepted Stage 9/10 contracts and corrections remain frozen except for the future extensions explicitly described here, which must themselves be reviewed before implementation.

No Python API, enum, SQL table, schema migration, dependency or test is introduced now. Names below are contract concepts; concrete records, signatures and failure mappings belong to their implementation milestones.

## Architecture and responsibilities

```text
Closed market data → Strategy → desired position
→ Stage 10 planner → proposed action
→ STAGE 11 RISK GATE → durable risk verdict / authorization
→ Stage 10 durable PREPARED → ATTEMPT_STARTED
→ Stage 9.5 Demo mutation
```

**Strategy intent != planner action != permission to take risk.** The strategy decides when it wants LONG/FLAT; the planner proposes a fixed quote BUY or confirmed owned-base SELL; risk independently permits or refuses that exact proposal. Risk is separate from EMA, research sizing, broker parsing, execution receipts and reconciliation. The exchange adapter retains normalization and broker communication; reconciliation retains ownership/fill truth.

Initial scope stays one Demo account, one bot, one strategy, one symbol, hourly timeframe `60`, Spot LONG/FLAT, MARKET only, no short, leverage, margin or borrowing. Stage 11 does not expand the Stage 9 mutation surface or Stage 10 execution scope. Frozen historical next-OPEN accounting remains separate from actual broker-reported executions.

**Stage 7 `position_fraction` = historical research allocation policy. Stage 11 = operational runtime safety policy.** Decision 011 stays unchanged. Do not import/reuse `position_fraction` as runtime capital sizing or describe Stage 7 as the Demo/live risk manager. The configured Stage 10 BUY budget remains fixed; Stage 11 vetoes without resizing.

The future pure engine receives already-normalized validated configuration, durable risk state, confirmed ownership, authoritative mark and proposed planner action. It does not call Bybit, inspect SDK/raw payloads, fetch market data, inspect environment variables, access SQLite, place or cancel. Orchestration supplies facts and persists results; no framework or second execution/reconciliation engine is required.

## Configuration and capital envelope

The initial policy requires these concepts, with no architectural numeric deployment defaults:

| Configuration | Meaning |
| --- | --- |
| `risk_capital_quote` | Fixed operator-authorized quote-currency capital envelope for this bot instance. |
| `max_entry_notional_quote` | Maximum pre-normalization quote authorization per ENTRY. |
| `max_position_notional_quote` | Maximum projected marked bot-owned exposure, including conservative pending reservations. |
| `max_daily_loss_fraction` | UTC daily MTM loss threshold as a fraction of the fixed risk capital. |
| `max_drawdown_fraction` | MTM decline threshold relative to the active epoch's high-water mark. |
| `max_entries_per_utc_day` | Maximum number of unique durable ENTRY ALLOW authorizations per UTC day. |

Financial values use finite exact Decimal semantics, never persisted Python float or float-derived approximations. Require a positive integer entry limit, rejecting bool. Reject invalid/inconsistent configuration without clamping or silent repair:

```text
risk_capital_quote > 0
0 < buy_quote_budget
  <= max_entry_notional_quote
  <= max_position_notional_quote
  <= risk_capital_quote
0 < max_daily_loss_fraction <= 1
0 < max_drawdown_fraction <= 1
max_entries_per_utc_day >= 1
```

Risk capital is not total wallet equity, all available USDT, wallet BTC, Bybit USD-equivalent account value or a dynamically compounded budget. Profits, deposits and unrelated assets never automatically enlarge the envelope, allowed entry size or exposure limit. Withdrawals do not automatically rewrite it. Actual broker availability remains a separate preflight/broker concern; the risk envelope does not promise spendable funds. Configuration identity is durable; changing it needs an explicit reviewed procedure, not restart or rearm defaults.

## Bot-owned equity and exact execution accounting

Use only durable bot-owned actions/executions, confirmed bot-owned base inventory, the approved risk capital and authoritative closed-candle marks. Wallet observations provide coverage checks, not ownership, capital allocation or risk-equity substitution. Unrelated assets never increase bot equity or permitted exposure.

The bot-owned accounting book starts with `virtual_quote_cash = risk_capital_quote` at its durable accounting anchor. Apply each reconciled owned execution exactly once:

```text
BUY:  virtual_quote_cash -= executed_base_quantity * execution_price
SELL: virtual_quote_cash += executed_base_quantity * execution_price
quote fee/rebate: virtual_quote_cash -= signed_quote_fee

risk_equity = virtual_quote_cash
            + confirmed_owned_base_quantity * mark_price
```

Positive fees reduce cash; negative quote rebates increase it. Signed base fees/rebates affect exact reconciled owned-base inventory and are not deducted from cash a second time. An ACK, requested quantity or order average is not an execution. Pending EXIT reduces no exposure until reconciled fills occur. No hypothetical exit, future fee, research slippage or wallet-total cash enters this book.

An epoch is a risk-measurement period, not a fresh credit of capital. On rearm, carry forward or reconstruct the same cash/inventory book from its original approved anchor and retained owned executions; do not reset cash to `risk_capital_quote`, double-credit existing LONG inventory or apply fills twice. New epoch baseline/peak start at fresh **current** equity. Initial Stage 11 activation over existing Stage 10 history must establish an explicit complete durable accounting anchor and reconcile the retained owned execution history; unavailable history cannot be replaced by free holdings or wallet totals. Concrete anchor/cutoff records are reviewed in 11.2/11.3.

If a nonzero execution fee has unknown currency or is neither base nor quote, and no accepted exact conversion contract exists, equity is not exactly knowable: fail closed. Never ignore the fee, infer its currency or convert through account USD aggregates. Stage 11.1 introduces no conversion mechanism.

## Mark, valuation time and replay

The mark is the **exact close of the latest accepted authoritative closed candle** supplied by the frozen Stage 10 market-data gate. Use its symbol, hourly identity, closure and freshness evidence. No ticker/mid-price endpoint, WebSocket, local wall-clock price, historical backtest fill or account USD mark is introduced.

Risk equity/drawdown observations occur at accepted closed-candle boundaries, including HOLD candles. This is an **hourly closed-candle risk system**: it makes no claim of intrabar maximum drawdown, tick-level risk control or intrabar stop-loss protection. Circuit breakers observe marks; they cannot guarantee loss containment between marks or during downtime.

After downtime, replay every required closed candle chronologically, using the durable owned execution history appropriate to each boundary. Do not apply the latest inventory retroactively to earlier marks. Preserve execution IDs/timestamps, valuation cutoffs and observed evidence so repeated replay cannot double-apply fills. Precise equal-boundary execution ordering, late-discovered fill handling and immutable correction lineage require explicit 11.2/11.3 design/test review; incomplete or conflicting evidence blocks authorization rather than silently rewriting accepted history.

Replay restores daily baselines, equity history and the epoch high-water mark and latches any missed breach, even if the latest equity has recovered. Historical risk replay may update durable risk accounting/latches but **never authorizes historical broker actions**. Stage 10 BOOTSTRAP/REPLAY_ONLY classifications, durable cutoffs and no historical resend remain authoritative.

## UTC daily loss

The risk day is fixed to UTC `[00:00:00, next 00:00:00)`; no configurable timezone initially.

```text
daily_pnl = current_risk_equity - utc_day_start_risk_equity
daily_loss_limit_quote = risk_capital_quote * max_daily_loss_fraction
TRIP when daily_pnl <= -daily_loss_limit_quote
```

The comparison is inclusive. PnL includes realized and unrealized bot-owned changes; realized-only accounting is insufficient. The quote threshold uses fixed approved capital, not the wallet, current profits or a changing daily budget.

For an already-running epoch, reconstruct the day's opening equity from durable owned executions through the UTC boundary and accepted closed-candle history at that boundary. A restart at 03:00 UTC cannot redefine 03:00 equity as the opening baseline. For the first partial UTC day of a newly created epoch, its first accepted valuation may supply the initial day baseline. Missing required history is a failure, not permission to reset. Midnight can open a new daily bucket but never clears a trip latch.

## MTM drawdown and risk epochs

```text
peak_risk_equity = max(previous peak, current accepted risk equity)
drawdown_fraction = (peak_risk_equity - current_risk_equity) / peak_risk_equity
TRIP when drawdown_fraction >= max_drawdown_fraction
```

Persist the high-water mark within the current epoch. Use exact Decimal arithmetic and require a valid positive denominator and consistent valuation. For the trip decision, the equivalent comparison `(peak - equity) >= peak * max_drawdown_fraction` with positive peak avoids rounding a nonterminating quotient across the threshold. Future diagnostic ratio precision must be explicit and must not change this inclusive decision. No float, epsilon, silent clamp or fabricated zero equity is permitted. This is MTM drawdown, not realized-capital-only drawdown.

A risk epoch begins at first valid risk activation or explicit operator rearm. Retain its identity/start time, starting risk equity, peak, UTC daily baselines, trip reason/time and rearm lineage. New epochs do not erase historical records. Invalid starting equity/denominator cannot create a healthy epoch.

## Verdicts and independent safety latches

The initial pure policy returns only **ALLOW, BLOCK, TRIP**. There is no REDUCE and no silent order resizing.

| Verdict | Contract |
| --- | --- |
| ALLOW | Current risk policy permits this exact proposed action. It does not prove broker funds, acceptance, a fill, profitability or safe resend. Stage 9/10 downstream safety remains required. |
| BLOCK | Nonfatal policy refusal. Typical ENTRY reasons: ENTRY_NOTIONAL_LIMIT, POSITION_NOTIONAL_LIMIT, ENTRY_COUNT_LIMIT, RISK_LATCH_ACTIVE. No PREPARED, ATTEMPT_STARTED or send; later future candles can be evaluated. |
| TRIP | A durable risk circuit breaker latches. Initial automatic reasons: DAILY_LOSS_LIMIT and MAX_DRAWDOWN. A future manual pause may use the same latch with a distinct reason. |

Stage 10 `RuntimeState.HALTED` means system/evidence/integrity/configuration cannot be trusted and blocks all mutation under frozen rules. Stage 11 risk TRIPPED means policy forbids increasing risk. These are independent concepts. Risk TRIP does not automatically cause runtime HALT, cancellation, liquidation or a SELL.

**TRIPPED + confirmed LONG + valid planner PLACE_SELL may ALLOW the exact owned-base EXIT**, provided all Stage 10 reconciliation, ownership, pending-action, freshness and safety checks pass and risk accounting is valid. Do not enlarge SELL or transform it into BUY/rebalance. HALT, uncertainty or broken risk evidence cannot be bypassed even for an EXIT.

Valuation/latch updates and the proposed action's verdict are separate facts. A new daily/drawdown breach can be durably latched while a valid risk-reducing EXIT receives ALLOW; this needs neither a fourth verdict nor a risk-generated exit signal. On HOLD or historical replay, account for the breach without manufacturing a broker action.

Initial Stage 11 has no automatic emergency SELL, forced liquidation, stop loss, take profit, trailing stop or risk-engine-created exit signal. A trip while LONG blocks future risk increase and leaves the existing strategy to produce a normal EXIT. Forced exits would change accepted strategy/execution semantics and need a separate reviewed contract.

## Exposure caps and conservative pending reservations

For proposed ENTRY, compare the **pre-normalization authorized quote amount**:

```text
authorized_entry_quote <= max_entry_notional_quote
owned_exposure_quote = confirmed_owned_base_quantity * mark_price
projected_exposure_quote = owned_exposure_quote + authorized_entry_quote
projected_exposure_quote <= max_position_notional_quote
```

Exceeding a cap gives BLOCK, not clipping or automatic resizing. Stage 9 normalization may reduce submission under its existing rules, never increase authorization. Caps do not authorize pyramiding: Stage 10 still permits ENTRY only from safe FLAT with no unresolved lifecycle. Price appreciation beyond an entry cap does not itself manufacture liquidation; the defined automatic trip causes remain daily loss and drawdown.

An unresolved ENTRY reserves its **full durable authorized quote amount** until terminally resolved. ACK, partial fills, wallet changes or unknown remaining quantity cannot shrink that reservation or free authorization capacity. When inspecting committed exposure, retain the full reservation alongside actual owned exposure conservatively; Stage 10 independently forbids another action while pending. The reservation is an authorization-capacity constraint, not an extra cash debit or duplicate execution/PnL. Actual cash/inventory change only through reconciled fills. Pending EXIT authorization/send/ACK never reduces exposure; only reconciled executions do.

## Daily ENTRY throttle

Count unique durable **ALLOW authorizations for ENTRY**, attributed to the UTC day of their authorization timestamp, not fill time. Enforce `max_entries_per_utc_day` before committing a new authorization. BLOCK, TRIP, HOLD and EXIT consume no ENTRY slot.

After durable authorization, preflight rejection, ABANDONED_UNSENT, broker rejection, partial fill and restart **do not refund the slot**. Reuse of the same authorization is not another slot, and recovery cannot create a second authorization. Retain the day's consumed authorizations across risk rearm/epoch changes as well; rearm is not a throttle reset. The next UTC day has its own count, without clearing the risk latch.

Do not include a consecutive-loss breaker initially: trade-pair semantics are arbitrary around partial fills and dust; daily MTM loss and drawdown provide portfolio-level controls without inventing round trips. Any later extension needs separate review.

## Durable truth and crash-consistent authorization

Future risk persistence belongs under the **same canonical account lock and durable runtime journal boundary**. Retain risk configuration identity, epochs, closed-candle valuations, virtual cash, equity, peak, UTC baseline, daily PnL, drawdown, verdicts, ENTRY authorizations, trip reason/time and explicit rearm history. Values cannot be recreated from process memory alone. Records need stable identities/evidence cutoffs and deduplication; audit history cannot silently change.

An ALLOWed ENTRY requires one atomic crash-consistent commit before ATTEMPT_STARTED:

```text
candle decision + risk valuation/verdict + risk authorization
+ PREPARED action + frontier advance
```

No risk-increasing action may exist durably without the approval that allowed it. A refused planner ENTRY requires atomic `decision + risk verdict + frontier` (including its valuation/latch effects) with **no PREPARED action**. The candle is consumed so restart cannot treat it as a new entry opportunity. EXIT permissions and their latch/valuation evidence must likewise be journaled coherently; receipts remain separate later observations. No SQLite transaction spans broker I/O.

Risk approval binds configuration/epoch, candle, exact proposed intent, ownership evidence and authoritative mark. Before a possible attempt, the future integration must still validate current latch and frozen freshness/deadline/ownership rules; a withdrawn or stale known-unsent approval cannot license a send or refund a consumed slot. Indeterminate persistence stops for reopening/reconciliation, not further reads/writes, abandonment or resend.

| Crash point | Required recovery |
| --- | --- |
| Before durable verdict | No action exists; reevaluation using the same durable evidence is allowed. |
| After BLOCK/TRIP commit | Candle consumed, no action; never reinterpret it as a fresh ENTRY opportunity. |
| After ALLOW + PREPARED commit | Authorization/slot consumed. Frozen Stage 10 action recovery applies; never create another approval/action for the same logical intent. |
| At/after ATTEMPT_STARTED | Original IDs and possible-send uncertainty remain authoritative; never automatically resend. |

Stage 9.5 ordering stays metadata/validation/normalization → `before_submit()` → durable ATTEMPT_STARTED → at most one mutation → ACK/REJECTED/UNKNOWN_OUTCOME. Risk does not move the durable attempt marker before preflight, bypass the callback, change IDs/units, turn ACK into fill or broaden place/cancel capability.

## Required future integration review against frozen code

The current planner produces an in-memory action proposal plus ENTRY_PREPARED/EXIT_PREPARED event; the cycle then atomically commits the decision/action/frontier. Future 11.4 must insert risk **before applying/committing** that proposed action/event. A BLOCK cannot leave a pending-action reference, ACTION disposition or fake HALT with no corresponding authorized action. Concrete persistence APIs/dispositions are deferred to 11.3/11.4; no frozen API or enum changes now.

The frozen planner currently HALTs on a LIVE HOLD when desired LONG differs from confirmed FLAT. After a legitimate risk BLOCK, that mismatch is expected and desired LONG must remain unchanged. Future 11.4 therefore needs a reviewed additive planner/orchestration extension using durable refused-intent provenance, so this specific policy refusal does not cause a false HALT on later HOLD. It must preserve genuine integrity/HALT and missed-exit guards. Never work around it by editing strategy output, clearing desired intent, faking a holding/fill or ignoring a genuine HALT. It must not buy late on HOLD or replay the blocked candle; only a genuinely new eligible future strategy event can propose a new action.

These are explicit future Stage 11 extensions, not permission to modify frozen planner/cycle/store in 11.1. The Stage 10.2 state machine and its closed transition table stay frozen; proposed risk statuses are separate from runtime/order/action-phase enums. Existing action identities, phase graph, exact Decimal storage, checkpoint CAS, deadlines/budgets, locking and no-resend behavior remain authoritative.

## Schema evolution

Stage 11.1 changes **no SQLite schema**. Existing schema-v1 journals remain readable by unchanged Stage 10 without migration. Stage 11.3 requires an explicit persistence/schema design review; this decision does not assume risk records already fit v1.

Silent migration and automatic reset/discard of schema-v1 journals are forbidden. If schema v2 is required, migration must be explicit, canonical-lock-held, offline with no broker I/O and separately owner-reviewed, preserving original IDs, fills, checkpoints and audit history. A sidecar is unacceptable if cross-store commit ambiguity could leave an action durable without its risk authorization. No migration, sidecar, private SQL bypass or schema version change is implemented now.

## Restart, rearm, pause and shutdown

Restart preserves epoch, equity book, peak, daily baselines/PnL, trip latch, ENTRY counts and consumed approvals. It never resets loss/drawdown/count/trip or becomes risk rearm. Before a new future LIVE ENTRY: reconcile frozen Stage 10 state → restore/replay missing closed-candle risk valuations → latch missed trips → establish fresh current mark/exact equity → evaluate risk.

Only explicit operator rearm clears risk TRIPPED. Require healthy Stage 10, no HALT or unresolved action, fresh reconciliation, fresh accepted closed mark and exact valuation. Start a new epoch with current equity as baseline/peak; preserve the continuous execution/cash book, old epochs/trips and rearm lineage. No automatic rearm at midnight, process restart, price recovery, new signal or scheduler wake.

Risk rearm cannot clear `RuntimeState.HALTED`; Stage 10 HALT repair/rearm is a distinct operator procedure. Future 11.6 may add an explicit operator risk-trip/pause: block ENTRY, preserve LONG, allow valid strategy EXIT, no cancellation/liquidation. No operator control is implemented here.

Existing external scheduler stop remains separate: stop scheduling, persist STOPPING, preserve exposure/pending, no SELL/cancel. Do not redefine STOPPING as risk trip or use shutdown/restart to clear either latch.

## Accounting failures and non-goals

Corrupted risk history, impossible execution accounting, unsupported nonzero fee currency, missing durable baseline, conflicting valuation or invalid configuration fails closed. Broken risk accounting cannot return ALLOW, including for an EXIT. Future implementation will review exact mapping to existing Stage 10 failure reasons; do not add speculative enums or weaken fatal/transient read classification now.

Never edit `signal`, `desired_position`, EMA values or strategy parameters. If strategy wants LONG and risk BLOCKS ENTRY, desired position remains LONG and the verdict is a separate durable fact.

Initial Stage 11 explicitly excludes automatic liquidation, stop loss, take profit, trailing stop, shorting, leverage, margin, borrowing, pyramiding, multi-symbol trading, portfolio/multi-bot capital allocation, dynamic Kelly sizing, volatility targeting, ATR/stop-distance sizing, VaR/Expected Shortfall, risk parity, ML risk scores, drawdown-dependent resizing, dynamic compounding of the BUY budget, options/derivatives, live trading, deployment and a monitoring platform. It is fixed configured authorization plus hard caps and MTM circuit breakers.

## Stage 11 roadmap

| Milestone | Scope | Status after 11.1 |
| --- | --- | --- |
| 11.1 | Runtime Risk Management Contract / Architecture | COMPLETE / owner review pending |
| 11.2 | Pure Risk State + Valuation + Policy Engine | NOT STARTED |
| 11.3 | Durable Risk Journal + Schema/Migration Contract | NOT STARTED |
| 11.4 | Pre-Trade Risk Gate + Crash-Consistent Authorization | NOT STARTED |
| 11.5 | Daily Loss / Drawdown / Exposure Circuit Breakers | NOT STARTED |
| 11.6 | Restart + Risk Trip / Rearm / Operator Controls | NOT STARTED |
| 11.7 | End-to-End Risk Integration Regression | NOT STARTED |
| 11.8 | Final Stage 11 Audit + Docs | NOT STARTED |

## Canonical 12-stage top-level roadmap

Stages 1–10 retain their accepted scope/history. Current remaining top-level stages are **11 — Runtime Risk Management** and **12 — Production & Live Readiness**. Stage 12 future subphases, all NOT STARTED:

| Subphase | Scope |
| --- | --- |
| 12.1 | Observability & Monitoring |
| 12.2 | Long-Running Demo Validation |
| 12.3 | Production Hardening / Deployment |
| 12.4 | Controlled Live Trading |

Earlier planning references to top-level Stages 13–15 are superseded **as roadmap naming only**: monitoring and the formerly separate validation/hardening/live directions now sit under Stage 12. Decision 017 and historical changelog entries remain unchanged. No Stage 12 implementation or live authorization follows from this naming update.

## Stage 11.1 preservation and verification

Only this decision, PROJECT_STATE.md, README.md and CHANGELOG.md change. Production/tests/schema/dependencies/notebooks/datasets/results and previous Decisions are unchanged; no new tests, notebook execution or runtime activation. Verify the unchanged full suite (baseline 2,510 tests, zero failures/errors/skips), `pip check` and both unstaged/staged diff checks before publication. Offline tests validate frozen software, not actual Demo behavior, profitability or deployment/live readiness.

Authenticated Bybit Demo read/order/cancellation: **NOT RUN**. Stage 11.2 requires separate explicit owner approval and must not start automatically; Stage 12 remains NOT STARTED.
