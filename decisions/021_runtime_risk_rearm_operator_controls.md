# 021 — Runtime Risk Rearm and Operator Control Contract

- Date: 2026-10-16
- Status: Accepted
- Scope: Stage 11.6a architecture/documentation only.
- Frozen baseline: `f1c542b3deb5d1baebd2ea52f70ea0785292e5df` — `Harden runtime risk circuit breakers`; Stage 11.5 independently owner-reviewed, COMPLETE / FROZEN.
- Governing decisions: [017](017_demo_trading_runtime_contract.md), [018](018_runtime_risk_management.md), [019](019_runtime_risk_journal_schema.md), [020](020_runtime_risk_gate_authorization.md), unchanged.

## Authority and current capability

This decision defines future explicit operator controls, not their implementation. Stage 11.6a is COMPLETE / owner review pending; Stage 11.6 has STARTED and remains INCOMPLETE. **Stage 11.6b requires separate owner authorization after this contract is reviewed/frozen.** Stage 11.7 remains separate and NOT STARTED; Stage 12 remains NOT STARTED.

Current production has no dedicated operator rearm APIs or pure risk-rearm helper. It supports the frozen OPERATOR_REARMED state-machine event and schema-v2 epoch records, but risk initialization/public LIVE authorization are restricted to the initial epoch. This commit changes no Python, tests, schema, dependency, prior Decision, notebook or data/result. API signatures below are conceptual future boundaries, not callable APIs or deployment instructions. No real migration, activation, rearm or authenticated Demo activity is authorized.

## Two independent latches and mandatory ordering

| Latch | Meaning | Explicit future control |
| --- | --- | --- |
| RuntimeState.HALTED | Operational evidence, configuration, ownership or integrity is unsafe. | Apply frozen OPERATOR_REARMED: HALTED → SYNCHRONIZING, then require normal reconciliation. |
| RiskState.trip_reason is not None | An automatic DAILY_LOSS_LIMIT or MAX_DRAWDOWN policy trip is latched in the current risk epoch. | Create a child risk epoch from the same accepted accounting boundary, with a new measurement baseline/peak. |

Risk TRIP does not itself make runtime HALTED. Both may coexist; neither control silently clears the other. When both are active, the required order is:

```text
explicit Runtime HALT rearm
→ SYNCHRONIZING
→ successful normal broker reconciliation
→ confirmed safe FLAT/LONG with aligned strategy intent
→ explicit risk rearm
→ future normal LIVE decisions
```

Risk rearm fails while runtime is HALTED. Runtime HALT rearm preserves the risk trip/epoch. Clearing an operational latch is not proof that its original cause is repaired: reconciliation may HALT again, including for exhausted retained recovery budgets. No budget, deadline, uncertain action or ownership evidence is reset to make recovery pass.

## Runtime HALT rearm boundary

Future Stage 11.6b may expose one narrow RuntimeStore control:

```python
store.rearm_runtime_halt(*, expected_sequence, operator_at_ms)
```

Use the already-held canonical account lock and one short IMMEDIATE transaction. Fully validate the store/binding, compare checkpoint sequence, validate explicit bounded integer UTC milliseconds under existing checkpoint time rules, and require the current snapshot to be exactly HALTED. operator_at_ms must be strictly later than halted_at_ms and preserve existing monotonic rearm metadata. No implicit now(), broker evidence fetch or arbitrary caller checkpoint/transaction callback.

Compute the snapshot through the unchanged `transition_runtime_state(..., RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))`. The only transition is **HALTED → SYNCHRONIZING**, never FLAT/LONG or ORDER_PENDING. Persist a single consecutive checkpoint CAS, rearmed_at_ms = operator_at_ms and halted_at_ms = None, consistently with frozen checkpoint invariants. The current operational reason clears through that event; exposure remains LAST_KNOWN or UNKNOWN, not newly CONFIRMED.

Preserve exact owned quantity, pending placement identity/kind and subordinate cancellation history, desired position, candle/frontier/cutoffs, observation/coverage facts, action IDs/phases, fills, remaining recovery bounds/deadlines and every risk row. Existing observation timestamps are retained historical facts, not newly refreshed evidence. The control performs no broker read/order/cancellation and does not repair or settle pending work. Normal reconciliation must follow before any ordinary placement can be considered.

Reject this control from STARTING, SYNCHRONIZING, FLAT, LONG, ORDER_PENDING, UNCERTAIN and STOPPING. UNCERTAIN uses frozen bounded recovery. STOPPING cannot resume in the same process; a new process must first use frozen restart recovery to restore a STOPPING-from-HALTED checkpoint to HALTED. Repeated invocation after successful rearm conflicts because the current state is no longer HALTED. Stale CAS, invalid time or corrupt evidence commits nothing.

## Risk rearm boundary and preconditions

Future Stage 11.6b may expose one narrow control:

```python
store.rearm_risk_epoch(*, expected_epoch_id, operator_at_ms)
```

It consumes only already-durable evidence under the same canonical account lock. Inside one IMMEDIATE transaction, independently revalidate all history, the expected current epoch, current checkpoint, configuration, mark/book and evidence; never trust a caller-supplied replacement state, numeric policy or epoch. No I/O callback or network spans the transaction.

All conditions below are required; failure is an explicit conflict/input/integrity error under existing sanitized RuntimeStore conventions, with no partial writes:

1. An active current epoch exists and matches expected_epoch_id exactly. Its final accepted state has an automatic trip reason/time and **trip_pending_report == False**. Uninitialized or untripped state cannot be rearmed.
2. Runtime is exactly FLAT or LONG, PositionEvidence.CONFIRMED, reason None and pending_action None. There is no unresolved placement or cancellation. Reject STARTING, SYNCHRONIZING, ORDER_PENDING, UNCERTAIN, HALTED and STOPPING.
3. Intent/exposure is aligned: **FLAT requires desired_position == 0; LONG requires desired_position == 1**. None, FLAT/1 and LONG/0 are errors. LONG retains its exact positive owned quantity; no extra BUY/pyramiding is permitted.
4. last_reconciled_at_ms and observed_at_ms are present. Relative to explicit operator_at_ms, each age is nonnegative and at most RuntimeConfiguration.observation_max_age_ms. Recorded Runtime HALT rearm must be followed by reconciliation evidence at or after rearmed_at_ms; old fresh-looking timestamps cannot replace subsequent reconciliation.
5. The accepted mark is fresh: `0 <= operator_at_ms - latest.valued_at_ms <= decision_max_age_ms`, using the existing runtime policy. No operator clock regression, fabricated observation time, ticker/wallet price or implicit now(). Stale evidence requires separate normal reconciliation/market processing first, not reads inside rearm.
6. The latest current-epoch risk valuation candle equals checkpoint.last_processed_candle_ms. Required historical hours are complete and coherent. No skipped REPLAY_ONLY/LIVE hour or rearm ahead of a lagging risk frontier.
7. Recompute the complete durable owned-fill evidence at the latest cutoff, including equality, using frozen canonical count/digest/order/fields. It must exactly match the accepted predecessor snapshot. A late-fill discrepancy blocks rearm; rearm is not historical correction or a way to ignore a missed breach.
8. Reconstruct the exact continuous book from the original approved accounting anchor and retained temporally eligible owned executions through the frozen pure helpers. Book, current confirmed quantity, accepted mark and prior equity must agree. Unsupported nonzero fee units, missing ownership, impossible book or changed evidence fails closed. Never apply post-boundary fills retroactively; newer facts requiring a new valuation must first pass normal accounting.

A missed REPLAY_ONLY trip cannot be erased while its notification remains pending. Normal runtime accounting must first surface/consume that notification without deleting its latch. The operator does not manufacture a verdict to satisfy this requirement.

### Why refused desired-LONG cannot cross the rearm boundary

Decision 020 permits confirmed FLAT/desired=1 HOLD only through a complete contiguous **same-epoch** LIVE chain rooted at a refused ENTRY. Rearm would end that provenance. Initial 11.6 therefore rejects this state instead of clearing desired_position, adopting wallet inventory, faking LONG, transferring refusal permission into the child, weakening planner safety or issuing a delayed BUY. Wait for strategy intent/exposure to align naturally. LONG/desired=1 may rearm under the other guards; this retains ownership and buys nothing.

## Child epoch, same candle boundary and continuous book

Use existing schema v2 and runtime contract version 1, unchanged. No schema v3, new table/index/column, sidecar or migration. The existing risk_epochs lineage and `(epoch_id, valued_at_ms)` valuation identity represent the child:

```text
epoch_sequence = parent.epoch_sequence + 1
parent_epoch_id = parent.epoch_id
risk_configuration_digest = parent.risk_configuration_digest
started_at_ms = parent latest accepted valued_at_ms = T
child ACTIVATION valued_at_ms = T
```

The child references the same durable candle, symbol/timeframe and exact authoritative CLOSE as the parent's final accepted valuation. T is a closed-candle boundary, not operator_at_ms or a process timestamp. Sharing T across two epoch IDs is deliberate; it is not a duplicate valuation within one epoch or another decision at that candle. Subsequent child valuations advance exactly T + HOUR_MS, then every consecutive hour under unchanged pure advancement rules.

Reuse the existing deterministic canonical SHA256 epoch encoding over configuration digest, sequence, T and parent ID. No UUID/random/PID or operator wall-clock value enters epoch identity. Sequences are consecutive and unbranched; current epoch is the highest validated sequence. Parent epochs are closed historical records, not append targets after child creation.

Risk configuration is the existing current RiskConfigurationRecord, never operator-supplied alternative limits. Preserve its digest/version and exact risk_capital_quote, buy_quote_budget, max_entry_notional_quote, max_position_notional_quote, max_daily_loss_fraction, max_drawdown_fraction, max_entries_per_utc_day, base_currency and quote_currency. Runtime budget/currency binding stays exact. Rearm cannot edit policy, grow capital from profits/wallet/deposits or insert another configuration; policy changes require a separate future reviewed procedure.

The child's **virtual_quote_cash and owned_base_quantity equal the parent's exact accepted/reconstructed book at T**, with the same accepted fill evidence count/digest. Reconstruct from the original anchor plus each unique durable execution once, or carry a fully verified equivalent book. Never credit risk_capital_quote again, double-credit existing LONG inventory or apply fills twice. Only the measurement reference resets; cash/inventory/ownership and historical economics do not.

operator_at_ms is an explicit freshness/control input, not a replacement for T. Existing v2 lineage records the accepted risk rearm at its accounting boundary; it does not supply a general operator-identity/command journal. Do not overload verdicts or add hidden persistence to claim a broader audit facility. Runtime HALT rearm uses existing checkpoint rearmed_at_ms; richer operator-command journaling remains outside this contract.

## Focused pure rearm-state extension

Separately authorized Stage 11.6b may add one deterministic side-effect-free helper to the previously frozen pure module:

```python
rearm_risk_state(config, previous_state, book, mark_price, valued_at_ms) -> RiskState
```

This is the explicitly accepted additive Stage 11.6 extension, not permission to implement it in 11.6a or alter existing pure APIs/formulas. Preserve exact types, numeric/time bounds, context-independent Decimal arithmetic and sanitized RuntimeRiskError behavior. No runtime/store/exchange import, I/O, clock, environment, mutation, sizing or action generation.

Require validated config/state/book/mark/time records, previous trip_reason/time present, previous trip_pending_report exactly False, valued_at_ms == previous_state.valued_at_ms, and exact book/mark equity == previous_state.risk_equity. Persistence proves the same configuration digest, epoch and ownership binding; the pure helper cannot infer those identities from a RiskState alone. At the store boundary, changed book/mark/evidence fails even if an altered combination would coincidentally reproduce the same equity. Positive exact equity remains required. Changed time fails; initialize_risk_state's zero ENTRY count is not a substitute for rearm.

The returned immutable state is:

| Field | Child value |
| --- | --- |
| epoch_started_at_ms, valued_at_ms | T |
| risk_equity, peak_risk_equity | Current exact equity at T |
| utc_day_start_ms | UTC day containing T |
| utc_day_start_risk_equity | Current exact equity at T |
| daily_pnl | Exact zero |
| entries_this_utc_day | Previous state's same-day consumed count, unchanged |
| trip_reason, tripped_at_ms | None |
| trip_pending_report | False |

**Explicit risk rearm intentionally resets the epoch's daily-loss and drawdown references to current equity, including a new partial-day baseline.** Prior losses/peaks/trips remain immutable in the parent. This is a deliberate operator override, never restart, midnight, price recovery or a new signal. It does not reset capital, the continuous book or today's throttle.

Example: two unique ENTRY ALLOW authorizations today → trip → explicit rearm at an accepted same-day boundary → child entries_this_utc_day = 2. The durable authority remains unique ALLOW ENTRY verdicts grouped by evaluated_at_ms UTC day **across all retained epochs**, with no duplicate recount or mutable counter. Abandonment/rejection/partial/ambiguous outcomes still do not refund. At the next genuine UTC rollover, unchanged advance_risk_state may reset the new day's count; rearm itself never does so.

## Atomic persistence, validation and future LIVE

Successful risk rearm atomically inserts **only one child risk_epochs row plus its first ACTIVATION risk_valuations row**. No configuration, decision, verdict, action, fill or checkpoint mutation; no frontier/sequence advance, strategy edit, preflight, send or cancellation. The old decision/verdict at T continues to belong to its original epoch; child activation has no verdict. Do not replay/reevaluate old BLOCK/TRIP/WAIT/HOLD/ENTRY/EXIT candles or reuse consumed IDs.

Full-store validation in 11.6b must independently establish consecutive sequence/exact parent/same configuration; parent final automatic trip with notification already consumed; child first ACTIVATION at exactly the parent's final T and epoch.started_at_ms; identical mark/book/evidence; carried count coherent with unique retained authorizations; and the pure rearm result above. Only the child clears the trip; parent rows, original reason/time and every prior action/fill/decision/verdict remain immutable. Orphan child/activation, branches, gaps, mismatched config/evidence/book/count, zeroed throttle or arbitrary unlatched epoch must fail closed.

Existing initial activation remains once-only epoch 1 via initialize_risk_journal; no repurposing it for rearm. Current epoch-1-only guards and strict cross-epoch time separation are correct for today's limited writer. Future store implementation must narrowly extend them for this reviewed child boundary and multi-epoch LIVE operation, without weakening within-epoch hourly continuity or legacy validation. Validate the first epoch with initialize_risk_state and each child with rearm_risk_state, not the zero-count initializer.

Reads must select latest from the highest validated epoch sequence and order shared-T history deterministically parent before child (time plus epoch sequence). Never choose current authority by lexical epoch hash or value-time alone. Bounded filtered reads still validate the complete history. Child activation must not be mistaken for a second verdict/authorization at T; counts are derived once from retained unique verdicts.

The **next genuinely new closed candle** uses the unchanged strategy → planner → risk gate → existing atomic LIVE boundary against the child. No historical or HOLD-delayed BUY, standalone LIVE/verdict writer or alternative send path. Rearm grants no order permission by itself. Existing ENTRY_COUNT_LIMIT and defensive notional/exposure semantics, exact EXIT, all operational guards, callback timing, ATTEMPT_STARTED ordering and no-resend behavior remain authoritative.

## Failure, retry and restart semantics

| Boundary | Before-commit failure | Committed truth / ambiguous return |
| --- | --- | --- |
| Runtime HALT rearm | Original HALTED checkpoint remains. | SYNCHRONIZING checkpoint with recorded rearmed_at_ms; risk unchanged. Indeterminate result stops and requires reopen/validation before any next operation. |
| Risk rearm | Parent remains current; no child or activation survives partially. | Complete child + ACTIVATION becomes current. Indeterminate commit/rollback stops, closes/reopens and validates lineage; never blindly repeat to create another epoch. |

Preserve existing SQLite durability, canonical lock/path validation, Decimal TEXT, FK/index/size/row bounds and error sanitization. No compensating write, automatic retry/reset or guessed successful rearm. Expected sequence/epoch protects against stale controls. After successful runtime rearm, another request fails outside HALTED; after successful risk rearm, another fails because current epoch is untripped (and the old expected_epoch_id is stale). Neither creates another reset or epoch N+2.

Frozen prepare_process_restart preserves current risk epoch/latch and retained runtime HALT; it invokes neither control and creates no epoch. Restart after successful rearm retains the accepted child/history and re-establishes operational certainty through normal reconciliation. Midnight and price recovery never clear trip_reason or create an epoch. STOP/shutdown continues to persist STOPPING, retain exposure/pending and exit without SELL/cancel; no same-process resume.

## Initial operator surface and implementation boundaries

Initial 11.6 includes exactly explicit Runtime HALT rearm and explicit automatic-risk-trip rearm. **No manual risk-pause/trip command.** Decision 018 allowed a possible later pause but did not require it here; v2 has no dedicated non-candle operator-control journal. Adding one requires separate persistence/schema review. Do not fake pause through HALTED, STOPPING, checkpoint reasons, risk_verdicts or a false DAILY_LOSS_LIMIT/MAX_DRAWDOWN reason. Existing STOP/shutdown remains the general conservative stop mechanism.

Both controls perform **zero broker reads, orders, cancellations, HTTP and credential access**. Reconciliation is a separate explicit runtime operation. Neither control cancels, sells, resizes, closes exposure, relaxes ownership, changes strategy output or clears the other latch. LONG remains owned until an ordinary valid strategy EXIT; risk rearm buys nothing.

After separate authorization, prefer production changes only in `risk/runtime_risk.py` (one new pure helper) and `runtime/store.py` (two narrow controls plus child/history validation and reads). Existing pure function semantics and 123 pure tests remain valid. Keep state.py, recovery.py, reconciliation.py, planner.py, risk_gate.py, cycle.py, scheduler.py, exchange/* and strategies/* unchanged. If cycle/risk_gate/state/recovery or another frozen layer must change, **STOP and report before expanding scope**.

Future test work may add focused rearm coverage and narrowly extend existing finite public-capability assertions to admit exactly rearm_risk_state, rearm_runtime_halt and rearm_risk_epoch; refresh source-preservation hashes only for separately authorized changed production. No broad mutation surface, manual_pause, clear_trip, force_flat, liquidate, cancel_all, edit_risk_config or generic transaction callback. No weakening/deleting old financial, state, timing, ownership or failure assertions.

Stage 11.7 remains the later broad End-to-End Risk Integration Regression milestone. No final integration expansion, launch/CLI, real operation, new breaker, live-money routing, dependencies, monitoring or Stage 12 work is included here.

## Required future Stage 11.6b acceptance tests

Use temporary fixtures/fakes and real local durability boundaries; no credentials, authenticated requests or real user journals. Require at least:

1. Automatic risk trip survives restart, with no new epoch.
2. Midnight and price recovery cannot clear it.
3. Risk rearm while HALTED rejects without any row/checkpoint change.
4. Runtime HALT rearm uses frozen OPERATOR_REARMED and enters SYNCHRONIZING only; other source states and stale CAS reject.
5. Runtime HALT rearm retains the exact risk trip/epoch, pending work, owned exposure, desired intent and recovery budgets.
6. Subsequent successful reconciliation restores safe FLAT/LONG; rearm itself establishes no confirmed broker state.
7. Risk rearm requires safe confirmed FLAT/LONG; unsafe states/reasons reject.
8. Pending placement or cancellation rejects risk rearm without abandonment or cancellation.
9. Missing/stale/future reconciliation timestamps or stale mark reject; no implicit clock or in-store broker read.
10. Risk frontier behind runtime frontier or missing required hour rejects.
11. Changed predecessor fill evidence, including equal-boundary late fills, rejects without rewriting history.
12. Pending trip notification rejects until normal accounting surfaces it.
13. FLAT desired=1, LONG desired=0 and desired=None reject without strategy edits or transferred refusal provenance.
14. Confirmed LONG desired=1 can rearm with exact ownership and no additional BUY.
15. Exact risk/runtime configuration and digest remain unchanged; alternative limits cannot be supplied.
16. Continuous cash/inventory and fill evidence are preserved exactly, with no fresh capital credit or duplicate fees/fills.
17. Same-day consumed ENTRY count carries across epochs, including abandoned/rejected/ambiguous authorizations; no recount/refund.
18. Child baseline/peak reset to exact current equity and daily PnL to zero; normal later UTC rollover remains unchanged.
19. Parent epoch, original trip reason/time, valuations, verdicts and authorization history remain immutable.
20. Child sequence/parent/ID are deterministic at the exact shared T; malformed lineage/orphan activation and lexical-hash latest-selection errors fail.
21. Repeated successful rearm cannot create another epoch or reset references again.
22. Faults at epoch/activation insertion, CAS/validation/commit/rollback and lost commit returns require all-or-nothing or explicit reopen, with no blind retry/duplicate.
23. Restart after risk rearm retains the child/current-epoch read selection, carried count and continuous book.
24. Next genuine LIVE candle uses the child; old candle replay/HOLD cannot create a delayed BUY or another approval. LIVE continuity and exact replay/no-send remain valid.
25. Both controls have no broker/network/cancel/liquidation/credential capability and cannot clear the other latch.

Without invoking rearm, the unchanged golden must remain **54 decisions / 2 placements / 2 fills / 0 cancellations**, one initial epoch, exact action IDs/orderLinkIds, authorized/submitted amounts, execution quantities/prices/fees, final ownership and restart behavior. Preserve Stage 5 EMA/next-OPEN and all research/backtest results.

## Stage 11.6a verification and publication

This contract changes exactly Decision 021, PROJECT_STATE.md, README.md and CHANGELOG.md. Zero production/test/schema/dependency/previous-Decision/notebook/data/result changes or new tests. Local execution passed the unchanged **2,850-test full suite**, zero failures/errors/skips; pip check and both unstaged/staged diff checks pass. No CI result is claimed. No notebook execution or runtime network activity; Git publication is a separate expressly authorized operation.

Publish one normal main commit after validation, with no history rewrite/force push; fetch and require HEAD == origin/main and a clean worktree. Stage 11.6a COMPLETE / owner review pending, Stage 11.6 INCOMPLETE, 11.6b next / NOT STARTED and separately authorized only after contract review/freeze; Stage 11.7–11.8 and Stage 12 NOT STARTED.

Real user DB migration: **NOT RUN**. Real user risk activation/rearm: **NOT RUN**. Runtime HALT operator rearm on a real runtime: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**.
