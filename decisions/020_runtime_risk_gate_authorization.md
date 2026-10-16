# 020 — Runtime Risk Gate Activation and Atomic Authorization Contract

- Date: 2026-10-16
- Status: Accepted
- Scope: Stage 11.4a architecture/documentation only.
- Frozen baseline: `be0eba0a4a6cb9f2d97165e0eb0da1525cdf951b` — `Add durable runtime risk journal`.
- Governing contracts: [017 — Demo Trading Runtime](017_demo_trading_runtime_contract.md), [018 — Runtime Risk Management](018_runtime_risk_management.md), [019 — Risk Journal Schema](019_runtime_risk_journal_schema.md), all unchanged. Stages 11.1–11.3 are independently owner-reviewed and FROZEN.

## Authority and current implementation

Stage 11.4 has STARTED and remains INCOMPLETE. This internal contract subphase, 11.4a, is COMPLETE / owner review pending. Stage 11.4b implementation requires separate explicit owner authorization after contract review/freeze; it is NOT STARTED. Stages 11.5–11.8 and Stage 12 are NOT STARTED. Accepted records the architecture, not permission to implement or activate it.

The current schema-v2 RuntimeStore has ten tables and supports explicit v1 migration, once-only epoch-1 ACTIVATION and consecutive REPLAY_ONLY persistence. It has no public LIVE valuation/verdict writer. The pure risk engine and the Stage 10 planner/cycle/scheduler/reconciliation/recovery remain frozen. **No runtime risk integration is implemented by this decision.** All API/outcome additions below describe future Stage 11.4b behavior.

This commit changes only this decision, PROJECT_STATE.md, README.md and CHANGELOG.md. No Python, tests, schema/version, previous Decision, dependency, notebook or data/result changes; no real user database migration, risk activation, credential/.env access or authenticated Demo activity.

## Intent, operational safety and risk permission

```text
closed candle → strategy → Stage 10 planner proposal → Stage 11 risk gate
→ durable LIVE risk valuation/verdict + optional durable PREPARED
→ Stage 9.5 preflight → before_submit timing check → durable ATTEMPT_STARTED
→ at most one Stage 9.5 broker mutation → receipt / uncertainty → reconciliation
```

**Planner proposal != risk authorization.** The unchanged strategy determines signal/desired intent; the Stage 10 planner determines canonical action intent, amount, units and IDs; risk decides whether that exact proposal may become durable authorization. An in-memory PREPARED proposal/event is not a durable action and must not be applied before permission is established.

Stage 10 safety always precedes policy. HALTED, STOPPING, UNCERTAIN, missing/unsafe reconciliation, ownership conflict, malformed broker/market evidence, unsafe timing and unresolved lifecycle restrictions cannot be overridden by risk ALLOW. Operational HALT/RECONCILE/WAIT keeps its safety meaning. The narrowly proved refused-intent continuation below addresses only its expected intent mismatch, never an independent safety refusal. Missing/malformed risk accounting is an error, not an invented ALLOW/BLOCK/TRIP; broken accounting cannot authorize EXIT either.

Keep the one Demo account/bot/strategy/symbol, hourly `60`, Spot LONG/FLAT MARKET scope. Historical next-OPEN research execution and Stage 7 allocation remain separate and unchanged. Risk does not expand exchange mutation capability or supply a strategy signal.

## Explicit activation before LIVE frontier advancement

An exact schema-v2 store with four empty risk tables is structurally valid but **not risk-active**. Empty risk journal != risk disabled. After Stage 11.4 integration there is no production risk-off trading mode, no automatic initialization and no ad hoc fallback policy.

Before explicit activation, bounded read-only reconciliation/recovery and historical BOOTSTRAP/REPLAY_ONLY work may still occur without broker mutation. For the next genuinely LIVE candle, an empty risk journal means:

```text
RISK_NOT_READY
no order; no PREPARED; no decision/frontier advancement; no automatic initialization
```

This applies to LIVE HOLD/no-proposal as well as ENTRY/EXIT: do not consume LIVE candles before the operator establishes the epoch and thereby silently omit them from its measurement history. RISK_NOT_READY is a distinct normalized nonretryable cycle outcome, not RuntimeState.HALTED or risk TRIP. Existing RuntimeReason.INVALID_CONFIGURATION may provide diagnostic control metadata without latching HALTED. Independent Stage 10 safety/recovery checkpoint evidence may still be persisted; that is not permission to consume the unhandled LIVE candle or erase an existing HALT/pending lifecycle.

A legacy confirmed LONG gets no special EXIT bypass. Required procedure: reconcile → explicit `initialize_risk_journal(...)` while safely LONG using retained owned fills → risk-active runtime → later valid strategy EXIT. Migration alone activates nothing and fabricates no approvals for old actions. No real user migration or activation is authorized here.

## Historical risk catch-up and evidence continuity

With an initialized epoch, catch up the risk journal through **every already-durable historical candle after its latest valuation through the runtime decision frontier**, before any new LIVE candle is committed. Use `append_risk_replay_valuation(candle_open_ms=...)` one hour at a time, with matching durable candle/close and temporally eligible owned fills; never skip hours, reset a baseline/peak or apply today's inventory retroactively.

Historical decision persistence and REPLAY_ONLY risk persistence may use separate transactions because neither authorizes a broker mutation. After a crash between those commits, restart detects the lag and appends the missing REPLAY_ONLY valuations before future LIVE authorization. This adds accounting evidence, never retroactive approval or a resend of a historical action. Existing exact replay retries retain Stage 11.3b's safe no-op semantics.

Replay may latch DAILY_LOSS_LIMIT or MAX_DRAWDOWN even if equity subsequently recovers. Preserve the original trip/time, high-water mark, daily baseline, ENTRY count and pending trip notification according to the pure engine; replay does not consume a notification by inventing a verdict. Historical catch-up sends **zero orders and zero cancellations**. The resulting latch constrains later ENTRY.

Before accepting LIVE, recompute the **latest accepted valuation's evidence snapshot at that valuation's cutoff**, the predecessor for the proposed LIVE row. Select all durable owned fills with executed_at_ms <= that cutoff; retain Stage 11.3b's complete canonical fields, execution-time/ID ordering, count and digest. Require exact count/digest equality. Legitimately late evidence does not rewrite or automatically invalidate the old observation, but it blocks continuation: no new LIVE valuation, verdict, decision, PREPARED, frontier advance or order. Missing/conflicting evidence cannot be repaired here by rehashing history or resetting the epoch.

## Authoritative risk inputs and pure evaluation

`run_single_cycle()` must not accept ad hoc numeric risk limits. Active policy/epoch come from `RuntimeStore.get_risk_configuration()` and `get_current_risk_epoch()`, with the frozen runtime BUY budget/currency binding. No environment overrides, caller float policy, wallet-derived capital or account USD equity.

Reconciliation first establishes durable owned execution truth. Reconstruct the current book from its approved original capital anchor and complete retained owned fills through the current valuation boundary, deduplicated by durable identity and ordered as in Stage 11.3b. Reuse `initial_risk_book` and `apply_owned_execution`; never duplicate fee/PnL formulas or count ACK/requested amounts as fills. Signed fees/rebates and unsupported-fee refusal remain frozen.

The mark is exactly the current accepted candle's close, introduced by the same LIVE transaction where necessary, with `valued_at_ms = candle_open_ms + HOUR_MS`. No independent caller mark/time, ticker, mid, WebSocket or local-clock price. After catch-up, require current valued_at_ms = latest risk valued_at_ms + HOUR_MS.

Use frozen `advance_risk_state(...)` then `evaluate_risk(...)` with the exact proposed `RiskActionProposal` or None. Persist the **post-evaluation** state, including notification consumption and any ENTRY count increment, atomically; do not first commit a pre-evaluation state and then update an immutable valuation. The pure module and all 123 Stage 11.2 tests stay byte-identical. If its contract cannot support a required case, STOP and report the gap separately rather than change it here.

## One atomic LIVE persistence boundary

Stage 11.4b should add one narrow RuntimeStore mutation, conceptually `commit_live_risk_decision(...)`. It is the only public way to create a LIVE valuation or risk verdict. No standalone LIVE writer, verdict writer or arbitrary SQL/callback transaction API.

Under the same canonical account lock and one short SQLite transaction, commit:

```text
CandleRecord + DecisionRecord + LIVE RiskValuationRecord + RiskVerdictRecord
+ optional PREPARED ActionRecord + RuntimeCheckpoint/frontier
```

The store independently validates/recomputes the result from its durable previous valuation, current epoch/configuration, owned fills, accepted candle mark, exact proposal and frozen pure engine. A caller's policy preview is not authority. Recheck predecessor evidence and continuity inside the transaction; reject stale checkpoint CAS, mismatched configuration/epoch, unsafe state, changed intent, conflicting duplicates or unsupported accounting. If handling HOLD depends on the refusal-continuation exception below, independently verify that same complete durable provenance inside the transaction, never trust a caller's exception flag. Preserve v2 DDL, exact Decimal TEXT, durability settings, bounds, references and existing ID/phase semantics; no new schema is selected by this decision.

| Pure result / proposal | Same-transaction durable result |
| --- | --- |
| ALLOW ENTRY/EXIT | LIVE valuation/verdict + matching ACTION decision + matching fresh PREPARED placement + pending checkpoint/frontier. |
| BLOCK or TRIP ENTRY | LIVE valuation/verdict + WAIT decision retaining exact signal/desired intent + checkpoint/frontier; no action row or pending-action event. |
| ALLOW with no proposal | LIVE valuation/verdict + planner's no-action decision/checkpoint/frontier; accounting only, no broker authorization. |
| TRIP with no proposal | LIVE valuation/verdict/latch + no-action decision/checkpoint/frontier; no broker action or runtime HALT caused by the trip. |

ALLOW of an ENTRY/EXIT action must be inseparable from its PREPARED action. `verdict.action_id == decision.action_id == action.logical_action_id`; exact kind, amount, unit, symbol and candle must match. Cancellation cannot be a risk-approved ENTRY/EXIT. BLOCK/TRIP/no-proposal records have action_id NULL. Refused ENTRY uses existing `DecisionDisposition.WAIT`, not a new disposition; risk_verdicts.verdict/reason is authoritative refusal provenance. Never persist ACTION/pending/ENTRY_PREPARED for a refused proposal.

BLOCK/TRIP consumes the LIVE candle without PREPARED, an action row or ATTEMPT_STARTED. Preserve the exact refused quote amount; never silently resize it. Exact committed replay of an already handled LIVE candle yields its recorded result with **no new authorization, counter increment, action event or send**. A conflicting replay fails closed. Runtime code must not bypass this boundary through the older Stage 10 `commit_decision` path for genuinely LIVE work.

### ENTRY authorization count

Durable truth remains unique ALLOW ENTRY verdicts grouped by the UTC day of evaluated_at_ms across retained epochs, not fills or a mutable counter table. The pure post-evaluation `entries_this_utc_day += 1` is saved in the same commit as PREPARED and must agree with that history. Validate authorization time/day against the frozen UTC valuation state; never disguise a mismatch by changing the timestamp, rounding money or refunding history.

Pre-submit refusal, ABANDONED_UNSENT, confirmed broker rejection, partial fill, UNKNOWN_OUTCOME, shutdown and restart never refund a consumed authorization. Duplicate replay consumes no second slot. BLOCK/TRIP/HOLD/EXIT consumes no ENTRY slot. UTC rollover retains the pure reset convention without clearing a trip or erasing authorization history; future rearm cannot reset the same day's consumed count.

## Risk trip, operational HALT and pending work

Risk TRIP latches RiskState; it is not a transition to RuntimeState.HALTED. Keep exact exposure and pending work. No cancellation, liquidation, stop loss or fabricated EXIT follows from a risk trip.

| Accepted policy state / proposal | Required pure meaning |
| --- | --- |
| Existing latch + fresh ENTRY | BLOCK / RISK_LATCH_ACTIVE; consume the candle without an action. |
| New trip + ENTRY or no proposal | TRIP; retain original breaker reason/time and persist notification consumption. |
| Existing latch + no proposal | ALLOW accounting only; latch remains. |
| New or existing trip + valid exact owned-base EXIT | ALLOW normal PREPARED EXIT under every Stage 10 guard; latch remains, no rearm. |

A genuinely LIVE planner NOOP/WAIT with no proposed action still receives a LIVE valuation and `proposal=None` verdict when risk is active and Stage 10 permits that decision to be handled. A WAIT that represents operational safety blocking decision processing is not promoted to policy ALLOW. Risk reasons use RiskReason, not overloaded RuntimeReason values.

With an unresolved action, the frozen single-pending-lifecycle restriction prevents a second authorization. A LIVE no-action candle may still record risk accounting; a new trip does not cancel the pending order. ACK never reduces exposure, and only reconciled fills change the book. In the current one-position runtime, this stronger prohibition on a second action preserves Decision 018's full conservative pending-ENTRY reservation constraint: unresolved authorization is never treated as free capacity. It is not a second cash debit, and no new reservation-based sizing or concurrent-entry path is introduced.

Runtime HALTED still forbids new authorization/rearm/risk-generated EXIT; STOPPING and other unsafe states retain their frozen behavior. Risk rearm/epoch 2/operator trip controls remain Stage 11.6. No midnight, recovery, restart, new signal or price recovery rearms risk.

## Durable refused-intent continuation after a blocked ENTRY

For FLAT + LONG_ENTRY/desired=1 refused by policy, the atomic result keeps runtime FLAT, desired_position=1, confirmed zero owned inventory and no pending action. Do not edit the signal, force desired=0, fake LONG/fills or apply the planner's proposed ENTRY_PREPARED event.

The frozen planner correctly HALTs a LIVE FLAT/HOLD/desired=1 mismatch when no explanation exists. Stage 11.4b should interpret only the following risk-proven case in a focused integration layer around the unchanged planner:

1. Current runtime is confirmed FLAT, checkpoint desired_position=1, current signal HOLD and current desired_position=1, with no pending action or independent ownership/safety inconsistency.
2. Complete durable history in the same risk epoch/configuration and instrument proves a contiguous LIVE chain through the immediately preceding candle.
3. Its origin is LONG_ENTRY/desired=1, WAIT disposition, BLOCK or TRIP verdict with proposal_kind ENTRY, exact refused amount, and NULL action references/no action row.
4. Every subsequent link is the next consecutive LIVE HOLD/desired=1 candle, with no action and an ALLOW/no-proposal risk verdict. No missing hour, decision or verdict.

Only this provenance explains the mismatch. Any ENTRY action, EXIT action, desired=0, LONG_EXIT, historical BOOTSTRAP/REPLAY_ONLY boundary without LIVE provenance, missing decision/verdict/hour, epoch discontinuity, malformed risk row or ownership inconsistency invalidates the exception. Then the normal Stage 10 planner semantics apply, including HALT where appropriate. An invalid/incomplete/bounded-out history cannot establish the exception by scanning only a convenient suffix.

The integration layer must prove the result is this specific expected intent mismatch, with all independent operational/freshness/configuration/history guards satisfied. It cannot convert an arbitrary HALT/RECONCILE/unsafe WAIT to ALLOW, suppress another fatal cause, alter planner inputs/strategy truth, broaden the frozen planner's global HOLD rule or hide a missed EXIT.

A proved continuation processes **no action** and evaluates `proposal=None`. Persist the resulting LIVE accounting/verdict/decision/frontier atomically. **Never issue a delayed BUY on HOLD**, even if the limits would now admit the original desired holding. A new risk-increasing authorization requires a genuinely new planner ENTRY proposal. Restart never reconsiders the original refused candle.

## Cycle outcomes and ordering

Future additive CycleOutcome values may be RISK_NOT_READY, RISK_BLOCKED and RISK_TRIPPED. They are normal normalized outcomes, not exceptions, and receive no scheduler 1s/2s retry. The retryable set remains exactly WAIT/RECONCILE/NO_NEW_DATA combined with EVIDENCE_MISSING/ACTION_OUTCOME_UNKNOWN under the frozen finite timing/attempt bounds. The ordinary next scheduled wake is separate from an immediate retry. Prefer no scheduler production changes.

SingleCycleResult may gain optional immutable risk_verdict/risk_reason fields using frozen RiskVerdict/RiskReason, with None for historical/non-risk-ready cases. Do not overload RuntimeReason with policy reasons. RISK_NOT_READY does not latch HALTED. RISK_BLOCKED/TRIPPED reports policy without changing operational state merely for risk; a valid EXIT may be ALLOW despite its retained risk latch.

Future LIVE ordering:

```text
startup reconciliation → authoritative closed-market validation → strategy
→ catch up missing durable risk REPLAY_ONLY history → frozen planner
→ narrow refused-intent interpretation, if proved → pure risk evaluation
→ atomic LIVE risk/decision/(optional action)/frontier commit
→ only for action ALLOW: existing Stage 9.5 preflight and final pre-submit gate
→ ATTEMPT_STARTED → adapter mutation once → existing receipt/uncertainty/reconciliation
```

Read-only broker reconciliation necessarily precedes risk evaluation to establish owned fills; it is not order dispatch. **No broker mutation/order submission occurs before committed ALLOW + PREPARED**, and no broker/network I/O occurs inside the atomic SQLite transaction. Neither the pure gate nor persistence performs a broker call.

Retain the final `before_submit` timing checks after metadata/validation/normalization:

```text
submit_ms >= decision.available_at_ms
submit_ms - decision.available_at_ms <= config.decision_max_age_ms
submit_ms < action.reconciliation_deadline_ms
```

Risk approval never replaces this final send-time gate or moves ATTEMPT_STARTED ahead of preflight. Keep callback_entered, pre_submit_timing_accepted, start_attempt_call_begun and attempt_commit_returned distinctions. Known unsent timing refusal may become ABANDONED_UNSENT without an attempt/send; an invoked-but-unconfirmed attempt commit stops without follow-up reads, writes, abandonment or resend. The consumed ENTRY slot remains consumed. Existing Stage 9.3/9.5 normalization may reduce the eventual submitted amount within its authorization; that frozen preflight behavior is separate from a risk gate resizing a refused proposal, which is forbidden.

## Crash and failure boundary

| Crash/failure point | Durable truth and recovery |
| --- | --- |
| Historical decision committed, replay valuation missing | Catch up missing REPLAY_ONLY hours before any LIVE authorization; no historical mutation. |
| Before LIVE commit / an insertion fails before commit | Roll back the entire candle/decision/risk/action/checkpoint change; no partial PREPARED or approval. |
| After BLOCK/TRIP commit | Candle consumed, verdict/latch retained, no action; never create PREPARED for that candle on restart. |
| After ALLOW + PREPARED, before ATTEMPT_STARTED | Approval/slot retained; frozen recovery retires provably unsent PREPARED without reauthorization. |
| At/after durable ATTEMPT_STARTED | Possibly sent even if no receipt; recover original IDs, never automatically resend. |
| Indeterminate commit/rollback | Stop, close/reopen/validate durable truth under the frozen store contract; no automatic retry, guessed success, abandonment or compensating action. |

Acknowledgement stays distinct from fill; cancel acknowledgement stays distinct from terminal order evidence. Risk does not reset recovery bounds/deadlines, erase consumed IDs, mutate settled fill history, refund approvals or weaken Stage 10 restart/HALT/shutdown rules.

## Expected separately authorized Stage 11.4b scope

Prefer changes limited to `runtime/store.py`, `runtime/cycle.py`, and optionally new `runtime/risk_gate.py`. A focused pure gate may adapt planner proposals to RiskActionProposal, prove refusal-continuation provenance and return deterministic results from normalized durable facts. It performs no broker/network/store mutation; pure accounting stays in `risk.runtime_risk`.

Keep planner.py byte-identical. Prefer zero changes to scheduler.py, state.py, reconciliation.py, recovery.py, runtime_risk.py and exchange code. If a frozen planner/scheduler/state change is truly necessary, STOP and explain before implementing it. If a pure-risk defect is discovered, STOP for separate review; never repair it implicitly in 11.4b. Existing schema v2 already represents LIVE/verdict facts; this contract introduces no schema or migration change.

Integrate only existing daily loss, max drawdown, ENTRY count, ENTRY notional, position notional and active-latch policy. No new stop loss/take profit, volatility sizing, consecutive-loss breaker, VaR, automatic liquidation, risk-based resizing, live routing, rearm/epoch 2 or operator control. No actual migration, activation or authenticated Demo operation follows from this ADR or future offline tests.

## Required Stage 11.4b acceptance tests

All future tests use temporary fixtures/fakes with no credentials or actual broker connection. Preserve old coverage; do not weaken source/financial/timing guards merely to pass. Require at least:

| Case | Required evidence |
| --- | --- |
| 1. Empty journal + LIVE ENTRY | RISK_NOT_READY; zero action, decision/frontier advance or automatic initialization. |
| 2. Empty journal + LIVE HOLD | Same refusal to consume the LIVE frontier, even with no proposal. |
| 3. Activated healthy ENTRY | ALLOW + LIVE valuation/verdict + matching PREPARED/pending/decision/frontier atomically. |
| 4. Daily ENTRY-count cap | Valid planner ENTRY with the UTC day's authorization count already at its maximum → BLOCK/ENTRY_COUNT_LIMIT; exact proposed ENTRY kind/amount retained in the verdict, WAIT decision and frontier consumed atomically, zero action/pending event. |
| 5. Existing latch ENTRY | Valid planner ENTRY → BLOCK/RISK_LATCH_ACTIVE; exact refused proposal and latch preserved, WAIT decision/frontier, zero action/pending event. |
| 6. New daily-loss/drawdown breach ENTRY | TRIP, durable latch, no action. |
| 7. New trip on HOLD | TRIP/no proposal, zero action and no risk-caused runtime HALT. |
| 8. TRIPPED exact EXIT | ALLOW matching PREPARED EXIT with latch retained and Stage 10 guards intact. |
| 9. Refused ENTRY then HOLD/desired=1 | Valid durable continuation avoids false HALT and sends no BUY. |
| 10. Many continuation HOLDs | Consecutive LIVE accounting, never a delayed BUY when limits change. |
| 11. Broken continuation chain | Every invalidator restores frozen planner safety; no broad HALT suppression. |
| 12. ALLOW ENTRY count | Pure post-evaluation count and unique authorization history commit with PREPARED. |
| 13. Abandoned/rejected ENTRY | Consumed authorization is not refunded, including after restart. |
| 14. Pending action | No second authorization; accounting does not cancel or treat ACK as fill. |
| 15. Late predecessor fill | LIVE fails closed with no new risk/decision/action/frontier records or historical rewrite. |
| 16. Atomic faults/crashes | Inject at every insertion, validation/CAS and commit boundary; all-or-nothing or explicit indeterminate reopening. |
| 17. Pre-submit boundary | No broker mutation before committed ALLOW/PREPARED; preserve final timing, one attempt and uncertain-commit stop. |
| 18. Scheduler policy outcomes | No 1s/2s retry for RISK_NOT_READY/BLOCKED/TRIPPED; frozen transient retries remain unchanged. |
| 19. Historical catch-up | Missing valuations recover across crash; missed trip remains durable; zero orders/cancellations. |
| 20. Activated permissive golden | Exactly 54 decisions / 2 placements / 2 fills / 0 cancellations. |

The permissive, explicitly initialized synthetic golden must retain exact action IDs/orderLinkIds, Decimal submitted amounts, executions, fees, final owned quantity and restart semantics. Risk adds journal/verdict facts without rekeying canonical actions or changing economics when limits do not bind. Also test exact LIVE replay without a second authorization, conflicts, LONG activation with no EXIT bypass, coherent UTC authorization counts/notification consumption, and every independent safety guard around continuation. Frozen Stage 5 EMA/next-OPEN financial results remain unchanged.

### Current runtime BLOCK reachability and defensive coverage

Owner-requested documentation-only correction, 2026-10-16: Stage 11.4a remains the architecture baseline at `6bc9d773040f4f09bb0f9aa103ffe4357a5bb27d`. Acceptance case 4 uses the reachable daily ENTRY-count cap instead of requiring an end-to-end ENTRY-notional refusal. No policy reason, formula, API or configuration invariant changes.

The frozen planner's ENTRY `authorized_amount` is exactly `RuntimeConfiguration.buy_quote_budget`. RuntimeStore requires the risk configuration's BUY budget to equal that runtime budget. Frozen risk configuration requires:

```text
buy_quote_budget <= max_entry_notional_quote <= max_position_notional_quote
```

Therefore a genuine planner ENTRY cannot exceed the entry-notional cap. ENTRY also requires confirmed FLAT, zero owned base and no unresolved lifecycle; pyramiding is forbidden. Its projected owned exposure is consequently zero plus the same fixed BUY budget, which cannot exceed the position-notional cap. Neither ENTRY_NOTIONAL_LIMIT nor POSITION_NOTIONAL_LIMIT is a reachable end-to-end planner ENTRY outcome in the current runtime scope.

Both remain valid frozen Stage 11.2 policy reasons and must retain direct pure-engine defensive coverage, including notional-limit and exposure validation under the frozen invariants. Explicitly constructed normalized proposals may exercise defensive integration/store validation where appropriate; inconsistent evidence must be rejected. This coverage must not fabricate either reason as a genuine current planner outcome. Future runtime scopes may exercise these reasons end-to-end only if separately accepted sizing/exposure contracts legally make them reachable.

Future Stage 11.4b must prove atomic BLOCK persistence end-to-end with ENTRY_COUNT_LIMIT and RISK_LATCH_ACTIVE, retain pure coverage for ENTRY_NOTIONAL_LIMIT and POSITION_NOTIONAL_LIMIT/exposure, and may additionally test store rejection of inconsistent constructed inputs. It must never weaken planner/configuration invariants for coverage. In particular, none of these counts as a genuine runtime BLOCK proof:

- `buy_quote_budget > max_entry_notional_quote`;
- `max_entry_notional_quote > max_position_notional_quote`;
- mismatched runtime/risk BUY budgets;
- manually changing a planner ActionRecord's authorized amount;
- enabling pyramiding;
- bypassing planner validation.

Such cases may test rejection of invalid evidence only. The matrix still has twenty cases; all other Decision 020 semantics remain unchanged. This correction adds no production/test/schema/dependency changes, migration, activation or Demo operation. Stage 11.4b remains NOT STARTED and must not resume until this correction is owner-reviewed/frozen.

## Stage 11.4a verification and publication

Local execution passed the unchanged full suite: **2,753 tests**, zero failures/errors/skips, with zero new tests. pip check, git diff --check and git diff --staged --check pass. Exactly four documentation files change; all production/tests/schema/dependencies/Decisions 017–019/notebooks/data/results are byte-identical to `be0eba0`. No CI or real exchange evidence is implied by offline validation.

Publish one normal main commit after all checks, with no history rewrite/force push; fetch and require HEAD == origin/main and a clean worktree. Stage 11.4a is COMPLETE / owner review pending; Stage 11.4b is next / NOT STARTED and requires separate authorization. Stage 11 remains INCOMPLETE; 11.5–11.8 and Stage 12 remain NOT STARTED.

Real user DB migration: **NOT RUN**. Real user risk activation: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**.
