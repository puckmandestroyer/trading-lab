# 023 — Observability Event / Logging Contract

- Date: 2026-10-17
- Status: Accepted contract; Stage 12.1a COMPLETE / owner review pending.
- Scope: Architecture/documentation only. No logging, notification, dashboard or integration implementation.
- Owner-reviewed baseline: `0b275c91abe53068dc4b0b05ade7be710d13cef6` — `Define Trading Lab v1 readiness contract`; Stage 12.0 / Decision 022 COMPLETE / FROZEN.
- Governing frozen decisions: [017](017_demo_trading_runtime_contract.md), [018](018_runtime_risk_management.md), [019](019_runtime_risk_journal_schema.md), [020](020_runtime_risk_gate_authorization.md), [021](021_runtime_risk_rearm_operator_controls.md), [022](022_trading_lab_v1_production_live_readiness.md), unchanged.

## Authority and preservation

This contract defines the future v1 observability used by 12.1b Structured Logs + Health Snapshot, 12.1c Telegram Outbound Alerts, 12.1d Streamlit Dashboard and 12.1e Observability Offline Regression + Audit. Observability is **derived, read-only with respect to trading truth, non-authoritative and failure-isolated**. It describes accepted facts; it cannot create them.

```text
RuntimeStore durable records + broker reconciliation = trading truth
                         ↓ after successful commit / transaction close
                 derived structured events + health snapshot
                         ↓                         ↓
                outbound Telegram           read-only Streamlit
```

JSONL, health snapshots, notifications and dashboard views never authorize orders, establish ownership/fills, perform risk accounting, rearm runtime/risk, reconcile or recover trading state. Deleting every observability artifact must not change the next trading decision. A projection cursor is not the trading frontier, and replaying an event cannot replay an order.

Preserve planner/risk behavior, action IDs/orderLinkIds, checkpoint transitions, risk epochs, fill ownership, scheduler cadence, retries, reconciliation and restart. Observability failure must not produce ALLOW/BLOCK/HALT/rearm or suppress an existing trading failure. Fixed-budget risk, independent HALT/TRIP latches, preflight → before_submit → durable ATTEMPT_STARTED → one possible mutation, and no blind resend remain frozen. Exactly-once logical authorization does not imply exactly-once exchange or notification delivery.

The frozen production boundary is the baseline above, with Stage 11 COMPLETE / FROZEN at `b79d511b94fa6e5dd07f59d95e7c51f175f3f756`. In particular runtime/{cycle,scheduler,reconciliation,recovery,state,store,risk_gate}.py, risk/runtime_risk.py, exchange adapters/results and all E2E/golden tests remain byte-identical. No public Python API, hook, constant, RuntimeStore schema-v2 table or dependency is added here.

## Version, envelope and serialization

Conceptually define **OBSERVABILITY_CONTRACT_VERSION = 1**, separately from RuntimeStore schema version 2, runtime contract version 1 and risk contract version 1. Do not implement the constant now. Changing a derived format does not itself require a trading database migration.

Every structured event has this fixed common envelope:

```text
observability_version
event_id
event_type
severity
source
occurred_at_ms
observed_at_ms
run_id
broker_id
account_binding
bot_id
strategy_id
symbol
timeframe
checkpoint_sequence
runtime_state
runtime_reason
risk_epoch_id
risk_epoch_sequence
risk_trip_reason
candle_open_ms
action_id
broker_order_id
summary
```

Version/type/severity/source identify the explicit record contract. Identity comes from validated non-secret runtime configuration, never credentials or wallet guesses. State/reason fields retain the existing distinct runtime/risk enums. action_id means the full logical action ID, not the shortened orderLinkId. summary is bounded sanitized human-readable text, not a payload dump or an authority input.

Fields that do not apply or are genuinely unavailable are explicit nulls where the future concrete record permits. Do not fill historical envelopes with today's state/epoch/sequence as though it existed at the event. occurred_at_ms is the known fact time; observed_at_ms is projection/observation time. A missing retained occurrence time must remain unavailable, never be replaced by the restart clock. Exact type-specific nullability/source validation is required in 12.1b.

All financial values are **canonical exact Decimal strings**, never JSON floats, scientific/rounded float conversions or Python repr. Examples: "0.04995", "100.123456789", "999.8951". Reuse frozen canonical Decimal semantics; no new financial formulas or precision policy. Timestamps are integer UTC milliseconds; versions, sequences and counts are integers, flags explicit booleans, enums stable string values, and absence JSON null. Unsupported/non-finite values fail observability validation without modifying trading truth.

No generic unbounded arbitrary context dict, automatic dataclass/SDK dump or exception-local capture is the primary schema. Every event-specific field is explicitly allowlisted by type. Strings, summaries, lists, event sizes and read batches must have finite validated bounds; exact numeric bounds are reviewed in 12.1b. Unavailable financial values remain null, distinct from exact zero.

## Event families and identities

**Durable projected events** describe accepted RuntimeStore evidence: owned fills, supported action-phase facts, confirmed position changes, LIVE BLOCK verdicts, first trip/latch evidence, retained HALT/rearm facts and child risk epochs. They are reconstructable from the accepted records that prove the fact; projection does not make a new state transition.

**Process/control events** describe a particular run: process/scheduler start/exit, normalized cycle completion, observed read/market degradation, RISK_NOT_READY, uncaught failure or sink failure. They need not be reconstructable from RuntimeStore. Never fabricate a completed cycle/normal stop when the call raised or the process died.

For a durable event, event_id is deterministic SHA256 over a canonical, unambiguous representation of observability version, stable broker/account/bot identity, event type and its type-specific durable reference. Follow the existing UTF-8 canonical JSON convention (sorted keys, compact separators, explicit values), not ambiguous string concatenation or repr. Re-projecting the same fact after restart produces the same event_id.

References may use action ID and supported phase, broker execution ID, epoch ID/valued_at_ms, original trip time/reason, or an actually retained checkpoint transition reference. **Never include observed_at_ms, PID, randomness or run_id in durable event identity.** Later observations or different summaries do not create a new fact. A later checkpoint merely retaining an old latch must not give that latch a new identity.

Each runtime process has a new observability-only run_id for correlation. Process-only IDs may use run_id and a bounded per-run occurrence reference to distinguish repeated cycles. run_id cannot affect action/epoch IDs, orderLinkIds, checkpoint contents, strategy output or any trading behavior. It does not replace the durable instance identity.

### Retained-history limits and catch-up

Schema v2 retains one current checkpoint and the latest record per action; it is **not an append-only checkpoint/action-transition log**. Immutable decisions, fills, risk valuations/verdicts and epoch lineage retain more history. The event taxonomy is not a claim that every past intermediate phase, checkpoint sequence or transition time can be recovered after it has been overwritten.

Project only supported facts. A post-commit observation of a proven transition may emit its event; restart catch-up re-projects facts still provable from retained records with the same durable identity. It must not invent missing prior states/times, infer that UNKNOWN previously ACKed, or infer every historical confirmation from an order receipt. Missing proof means unavailable history, not successful complete backfill. 12.1b must settle/test the exact source/reference mapping and observation boundaries before integration. No extra trading table, private SQL mutation or manufactured trading write is permitted to improve log completeness.

A separate non-authoritative cursor/index outside RuntimeStore may track projection/delivery. A missing/corrupt cursor reports observability degraded and allows bounded re-projection from retained trading truth. Duplicate observations are preferable to changing truth; gaps must be visible. The cursor cannot gate trading, advance its frontier or settle unknown ownership. An indeterminate trading commit follows the frozen stop/reopen policy: logging cannot perform forbidden follow-up reads/writes or announce committed success from a lost return.

## Severity and event taxonomy

V1 severity has exactly **INFO, WARNING, ERROR, CRITICAL**, without custom numeric semantics:

| Severity | Meaning / examples |
| --- | --- |
| INFO | Normal process start/stop, cycle completion, confirmed OPEN/CLOSED, action/fill progression and successful explicit rearm. |
| WARNING | Risk BLOCK/TRIP, stale/missing evidence, bounded transient read degradation and observability delivery degradation. Risk TRIP is not runtime HALT. |
| ERROR | UNCERTAIN/ambiguous action, persistent reconciliation deficiency or scheduler/control failure requiring operator attention. |
| CRITICAL | Runtime HALTED, store/integrity failure or uncaught fatal runtime exception. |

The following event semantics are frozen. Concrete Python names may follow repository conventions. Payload columns are closed allowlists of conceptual fields in addition to the envelope; optional values require evidence and explicit nullability. Shared field groups below have only the listed fields, not arbitrary dictionaries. Neither severity nor presentation classification changes trading policy.

| Event type | Family / source and meaning | Allowed event-specific fields |
| --- | --- | --- |
| PROCESS_STARTED | Process; actual process start, not proof of activation/health. | process_started_at_ms |
| PROCESS_STOPPED | Process; normal observed completion only, not crash inference. | process_started_at_ms, process_stopped_at_ms, stop_reason |
| SCHEDULER_STARTED | Process; actual scheduler entry. | scheduler_started_at_ms |
| SCHEDULER_EXITED | Process; normal SchedulerResult return. | scheduler_exit_reason, cycle_count, wake_count, last_cycle_outcome |
| CYCLE_COMPLETED | Process; normal SingleCycleResult return. | cycle_outcome, processed_candle_count, processed_candle_open_ms, planner_kind, new_execution_ids, risk_verdict, risk_reason |
| CRITICAL_FAILURE | Process; sanitized uncaught fatal/store/control failure, without claiming a durable HALT. | operation, failure_kind, exception_type, safe_error_code |
| MARKET_DATA_STALE | Process/evidence; established stale/missing market observation, not guessed from an ambiguous generic WAIT. | evidence_kind, latest_accepted_candle_open_ms, latest_mark_price, evidence_observed_at_ms |
| RECONCILIATION_DEGRADED | Process/evidence; normalized deficiency with its known reason, no repair. | evidence_kind, last_reconciled_at_ms, last_broker_observation_at_ms, pending_action_id |
| RECONCILIATION_CONFIRMED | Durable projection of an accepted coherent reconciliation, not order acceptance. | position_evidence, owned_base_quantity, pending_action_id, last_reconciled_at_ms, last_broker_observation_at_ms |
| ACTION_PREPARED | Durable; accepted action intent, not permission from an in-memory planner alone. | Action fields below |
| ACTION_ATTEMPT_STARTED | Durable; committed attempt marker, not proof of send/fill. | Action fields below |
| ACTION_ACKNOWLEDGED | Durable; retained valid acknowledgement, not fill. | Action fields below |
| ACTION_UNKNOWN_OUTCOME | Durable; retained unknown mutation outcome, never resend permission. | Action fields below |
| ACTION_TERMINAL_CONFIRMED | Durable; reconciled terminal action evidence, not cancel acceptance. | Action fields below |
| ACTION_REJECTED | Durable; confirmed current rejection distinct from transport ambiguity. | Action fields below |
| ACTION_ABANDONED_UNSENT | Durable; retired provably unsent PREPARED, never an attempted action. | Action fields below |
| OWNED_EXECUTION_DISCOVERED | Durable; unique committed bot-owned fill, not an order average. | Execution fields below |
| POSITION_OPEN_CONFIRMED | Durable; reconciled ownership becomes confirmed positive. | Position fields below |
| POSITION_CLOSE_CONFIRMED | Durable; reconciled positive ownership becomes confirmed exact zero. | Position fields below |
| POSITION_QUANTITY_CHANGED | Durable; confirmed owned quantity changes without inventing another complete trade. | Position fields below |
| RISK_NOT_READY | Process/condition; empty risk journal refused LIVE without consuming its frontier. | risk_active, cycle_outcome |
| RISK_BLOCKED | Durable; accepted LIVE BLOCK verdict for that exact candle/proposal. | Risk fields below |
| RISK_TRIPPED | Durable; first accepted latch evidence, including historical replay or an ALLOWed EXIT with a retained new trip. | Risk fields below |
| RISK_REARMED | Durable; committed child epoch and ACTIVATION, never merely a requested control. | parent_epoch_id, child_epoch_id, accepted_boundary_ms, risk_configuration_digest |
| RUNTIME_HALTED | Durable; checkpoint transition/latch evidence, never a logger-created HALT. | owned_base_quantity, position_evidence, pending_action_id, halted_at_ms |
| RUNTIME_UNCERTAIN | Durable; accepted uncertainty evidence; original unresolved identities remain. | owned_base_quantity, position_evidence, pending_action_id, action_phase |
| RUNTIME_REARMED | Durable; committed explicit HALTED → SYNCHRONIZING only. | rearmed_at_ms, previous_runtime_state, reconciliation_required |
| OBSERVABILITY_DEGRADED | Process; sink/projection/delivery problem with bounded fallback. | sink, operation, failure_kind, exception_type, safe_error_code |

Allowlisted payload groups:

- **Action fields:** action_kind, action_phase, order_link_id, parent_action_id, target_broker_order_id, side, amount_unit, currency, authorized_amount, submitted_amount, attempt_count, acknowledgement_broker_ms, acknowledgement_observed_ms, order_status, external_status, terminal_at_ms, safe_reason, rejection_code. External status must satisfy safe-text bounds; omit unsafe external text rather than dumping it.
- **Execution fields:** broker_execution_id, order_link_id, side, executed_quantity, execution_price, execution_fee, fee_currency, executed_at_ms, first_observed_at_ms. Preserve signed fees/rebates and units; absent fee currency cannot be invented. Ownership and action/order references come from the accepted owned-fill record.
- **Position fields:** position_evidence, previous_owned_base_quantity, owned_base_quantity, pending_action_id, order_link_id, contributing_execution_ids, entry_time_ms, exit_time_ms, entry_fills, exit_fills, realized_trade_pnl_quote. Fill-list members use only Execution fields plus their action/order IDs; bound the lists and expose incompleteness rather than claim an exact total from a prefix. Trade fields/PnL are optional and require the exact reconstruction conditions below.
- **Risk fields:** risk_configuration_digest, valued_at_ms, valuation_mode, proposal_kind, authorized_amount, risk_verdict, risk_reason, mark_price, risk_equity, peak_risk_equity, utc_day_start_risk_equity, daily_pnl, entries_this_utc_day, max_entries_per_utc_day, tripped_at_ms. Retain the epoch/reason/time in the envelope and payload consistently; no new valuation/verdict is created by projection.

Additional derived fields/events needed by charts/read models require an explicit reviewed allowlist, not an unbounded extension bag. Do not infer a specific market/API failure from a normalized result that does not distinguish it.

## Financial and state-event truth

### Confirmed position and partial fills

POSITION_OPEN_CONFIRMED requires durable reconciliation proving a transition into confirmed owned quantity > 0. LONG_ENTRY, planner ACTION, risk ALLOW, PREPARED, ATTEMPT_STARTED and broker ACK alone are insufficient. POSITION_CLOSE_CONFIRMED requires a proved transition from positive owned quantity to confirmed quantity == 0; SELL signal/request/ACK or cancellation acceptance cannot establish this.

A first partial BUY may legitimately establish confirmed positive owned inventory and emit OPEN even while ORDER_PENDING. OPEN proves exposure, **not that the order filled completely**. Later positive quantity growth is POSITION_QUANTITY_CHANGED, not another OPEN. Partial executions may emit OWNED_EXECUTION_DISCOVERED and quantity-change events. Partial SELL leaving positive inventory is not CLOSE; retained dust is not rounded to FLAT. Confirmed zero exposure and terminal order state remain different facts. Restoring certainty for the same existing holding after restart must not invent a new opening trade.

Observability must not run a second ownership/reconciliation engine. Use accepted reconciled facts plus their exact durable execution references. If a historical transition cannot be proved, show known current exposure/retained fills with the missing history explicit, rather than synthesize an OPEN/CLOSE event from signals or acknowledgements.

### Trade PnL

Display realized trade PnL only when exactly reconstructable from complete bot-owned durable execution quantities/prices and signed fees with known units. Preserve base/quote fee effects once under frozen accounting; do not convert unsupported currencies, treat ACK/requested quantity as a fill, or fabricate trade cycles. Requested amounts, wallet equity/USD equivalents and strategy signal prices are not PnL inputs. Unavailable/incomplete PnL is null, never zero. Any later aggregation must retain the source execution IDs and reviewed exact semantics; this contract implements no formula or analytics module.

### Risk and independent latches

RISK_BLOCKED requires a durable LIVE BLOCK verdict. Risk not ready is not BLOCK or TRIP. RISK_TRIPPED projects the first retained latch evidence using original epoch, trip reason and tripped_at_ms; a later candle retaining the latch does not create another trip event. Detect the latch itself, not only a TRIP verdict: replay can latch it and a genuine EXIT can ALLOW while tripped. Projection cannot consume trip_pending_report or change the latch. A later blocked ENTRY under the latch may separately emit RISK_BLOCKED / RISK_LATCH_ACTIVE.

RUNTIME_HALTED needs a committed checkpoint transition/latch with known reason, sequence, quantity/evidence, pending action and halted_at_ms where retained. Repeated reads of the same fact keep its event_id. Uncaught store failure may leave durable state unknown; CRITICAL_FAILURE must not claim HALTED was successfully persisted.

RUNTIME_UNCERTAIN and ACTION_UNKNOWN_OUTCOME make ambiguity highly visible. They never recommend an automatic "retry order" or invoke resend/cancel. Missing broker order IDs remain null. Unknown receipt, known broker order observation and partial ownership are separate facts.

RUNTIME_REARMED requires the committed HALTED → SYNCHRONIZING checkpoint and recorded rearmed_at_ms. It means explicit control succeeded, not runtime healthy or position confirmed; separate reconciliation is still required. RISK_REARMED requires durable child epoch + ACTIVATION, retaining parent/child identities and accepted boundary T. Neither event invokes rearm or suggests restart/midnight/recovery rearmed anything. Prior trip history and same-day consumed ENTRY count remain intact.

## Normalized process telemetry and exceptions

CYCLE_COMPLETED uses only normalized SingleCycleResult: outcome, processed candle count/times, planner kind, logical action/broker order IDs when available, new execution IDs, runtime reason, risk verdict/reason and checkpoint sequence/state. OBSERVED is not synonymous with FILLED. A normal cycle event complements rather than replaces specific durable events. No raw candles/SDK payloads or blanket repr logging.

Scheduler start is observed at entry; exit uses SchedulerResult cycle_count, wake_count, exit_reason and last_cycle.outcome. Preserve STOP_REQUESTED, HALTED and STOPPING as distinct values. Stopped runtime does not imply flatness, cancellation, cleared risk or rearm. If the scheduler raises, no normal result/exit is fabricated.

An uncaught runtime exception may emit CRITICAL_FAILURE with allowlisted safe operation/code/type only. Preserve the original exception/control behavior; never swallow it to keep logging alive, convert it to a safe state, automatically retry a mutation or attempt compensating persistence. Failure reporting must itself be bounded and must not mask the original exception. In particular, an indeterminate attempt commit still forbids follow-up trading reads/writes, abandonment and resend.

## Secret safety and redaction

Never log API keys/secrets, Telegram bot tokens, Authorization/private headers, cookies, signatures, environment dumps or credential-bearing URLs. Do not persist raw SDK/HTTP payloads, arbitrary exception messages/chains/locals, client reprs or request/response dumps by default. Truncating raw secret-bearing text is not sanitization. Prefer fixed operation/reason codes and verified exception types, using existing bounded safe-text conventions where applicable.

The safe operational allowlist includes validated bot_id/account_binding, symbol/timeframe, action ID/orderLinkId/broker order ID/execution ID, runtime/risk enums, exact quantities/prices/fees, candle timestamps and checkpoint/epoch sequences. These identifiers are not credentials, but still require bounded validation. Safe human summaries may use only these approved fields; external untrusted text is not automatically safe because it fits a size limit. No actual credential/token access is necessary for offline tests.

## Storage, I/O and failure isolation

Choose local **UTF-8 JSON Lines (JSONL)**: one explicitly validated event object per line. Use UTC-date segmented append-only files, conceptually events-YYYY-MM-DD.jsonl, rather than one permanently growing file. Exact local per-bot/account-binding paths and UTC segmentation details are settled in 12.1b, outside notebooks/results and without secret-bearing names. Stage 12.1 does not delete old logs; retention/deletion/compression belongs to **12.3d Backup + Log Rotation + Recovery**.

A separate derived **health.json** holds the latest operational read model. Future writes use a temporary file, fsync as appropriate and atomic replacement so readers do not accept half a snapshot. Exact implementation belongs to 12.1b. Missing/malformed health means observability unavailable/stale; it cannot change trading state. JSONL/snapshot/cursor storage adds no SQLite trading table, schema v3, DB migration or second trading journal.

```text
durable trading transaction commits
→ transaction closes
→ bounded observability projection / file write / delivery may occur
```

Never hold RuntimeStore transactions across file sinks, Telegram I/O or dashboard work. No external sink determines whether trading truth commits. Observation hooks need separate narrow review and must preserve final send-time checks and exception behavior. Keep file/network sinks and expensive projection outside the frozen PREPARED/preflight/before_submit/ATTEMPT_STARTED/send segment; in particular, do not insert a fallible logging call between the durable attempt marker and its one possible broker call. Project supported facts later at reviewed safe boundaries, without weakening timing checks to accommodate logging. Observability may not add waits/retries to the scheduler's trading policy or duplicate its reconciliation loop.

If event/snapshot/cursor writing or projection fails: do not place/cancel/rearm, modify risk/checkpoint, fake successful output or roll back accepted trading truth. Attempt one bounded sanitized local fallback such as stderr. Bound resource use/retries and suppress recursive logging of the fallback's own failure; no infinite logging recursion or unbounded retry loop. Surface degradation independently of trading state. Exact sink/resource limits and torn-line handling require offline tests in 12.1b.

## Health snapshot contract

The read model must be capable of presenting the following allowlisted groups. Unknown/nonapplicable values remain null/unavailable; financial fields are canonical Decimal strings. Context is derived from one clearly identified accepted boundary, not a claim that broker, risk mark and process telemetry are simultaneous.

| Group | Required facts |
| --- | --- |
| Identity | observability_version, generated_at_ms, run_id, broker_id, account_binding, bot_id, strategy_id, symbol, timeframe. |
| Process | process_started_at_ms, last_scheduler_activity_ms, last_cycle_activity_ms, last_cycle_outcome, observability_status. |
| Runtime | checkpoint_sequence, runtime_state/reason, position_evidence, owned_base_quantity, desired_position, pending_action_id/kind/phase where known, last_processed_candle_ms, last_reconciled_at_ms, last_broker_observation_at_ms, halted_at_ms, rearmed_at_ms. |
| Risk | risk_active/not-ready, current risk_epoch_id/sequence, risk_equity, peak_risk_equity, utc_day_start_risk_equity, daily_pnl, entries_this_utc_day, max_entries_per_utc_day, risk_trip_reason, tripped_at_ms. Include valued_at_ms/configuration digest so hourly risk values are not mistaken for current wallet equity. |
| Market | latest_accepted_candle_open_ms, latest_accepted_mark_price and its accepted valuation boundary. |
| Presentation | overall health level, known attention/critical reason codes, and explicit freshness/availability for generated data and underlying market/reconciliation/risk evidence. |

To support Decision 022 views, the derived read model may also carry the explicitly bound risk configuration fields (risk_capital_quote, buy_quote_budget, max_entry_notional_quote, max_position_notional_quote, max_daily_loss_fraction, max_drawdown_fraction, base_currency, quote_currency), exact drawdown numerator/denominator and retained event/trade/epoch references. It cannot recompute policy from wallet totals, silently reset peaks/counts or pretend a projected child epoch is an operator action.

Freshness is **fresh, stale or unknown**, tied to generated_at_ms and the actual underlying evidence times. Use existing runtime configuration age bounds where applicable; a new snapshot does not refresh an old reconciliation/mark. The UI must distinguish stale/unknown/not available from numeric zero or healthy. Exact display freshness rules are settled/tested in 12.1b/12.1d without changing runtime thresholds.

Overall observability health is exactly **OK, ATTENTION, CRITICAL**, for presentation only, not a RuntimeState:

| Level | Meaning |
| --- | --- |
| CRITICAL | Known runtime HALTED/UNCERTAIN, store/integrity open failure or uncaught fatal runtime failure. |
| ATTENTION | Risk TRIPPED/NOT READY; STARTING/SYNCHRONIZING/STOPPING; stale/missing market/reconciliation evidence; observability delivery degraded; pending action beyond a safely established expected observation window. |
| OK | No known critical/attention condition in the available fresh evidence. Absence of telemetry does not prove health. |

CRITICAL takes presentation precedence over ATTENTION. ORDER_PENDING alone is not unhealthy. Always show original states/reasons and freshness alongside the summary; unavailable evidence is not silently OK. Presentation never triggers trading HALT/TRIP, rearm or resend and invents no new runtime deadline.

## Telegram and Streamlit consumer boundaries

**Telegram consumes structured events only**, without broker/wallet reads or reconciliation ownership. It is outbound-only: no command handlers, command polling/webhooks or chat-triggered mutation. Required eventual alert subset is PROCESS_STARTED, PROCESS_STOPPED, POSITION_OPEN_CONFIRMED, POSITION_CLOSE_CONFIRMED, RISK_TRIPPED, RUNTIME_HALTED, RUNTIME_UNCERTAIN, RUNTIME_REARMED, RISK_REARMED and CRITICAL_FAILURE. Suppress ordinary HOLD/NO_NEW_DATA/hourly-cycle spam by default; unknown action outcomes remain highly visible through their uncertainty event.

Telegram uses stable event identity with best-effort **bounded** retry/dedupe. HTTP delivery may succeed immediately before a crash loses the local acknowledgement; duplicate notifications are therefore possible. No exactly-once Telegram delivery claim, and no notification duplicate/failure can cause a trading duplicate. A separate derived delivery cursor is permitted, never a RuntimeStore outbox or authorization record. Stage 12.1c settles concrete delivery limits/ack handling with offline HTTP fakes, without a real token or message during implementation.

**Streamlit consumes health snapshots and structured observability events**, local-only/read-only by default. It does not open the live RuntimeStore as a second active account-lock owner or trading authority, inspect broker APIs, run direct SQL mutation or reconstruct trading recovery from logs. Additional needed derived fields belong in the reviewed observability read model, not dashboard reinterpretation of trading persistence.

Support the six Decision 022 views: Overview, Position / Orders, Risk, Trades, Runtime Health, Event / Error History. Charts may show risk equity, daily PnL, drawdown, owned quantity and confirmed trades from supported durable-derived data; never infer fills from EMA signals. Financial event/snapshot source values remain exact canonical Decimal strings; rendering cannot change stored facts or policy. No BUY/SELL/cancel/rearm/change-limits/force-flat/start-Live buttons or other trading controls.

## Implementation roadmap and acceptance boundaries

| Milestone | Reviewed direction | Status after 12.1a |
| --- | --- | --- |
| 12.1a | Decision 023 and current documentation only. | COMPLETE / owner review pending |
| 12.1b | Structured event model, safe JSONL sink, durable projection, atomic health snapshot and offline tests. A dedicated package such as src/trading_lab/observability/ may be introduced after authorization. | NOT STARTED |
| 12.1c | Telegram outbound worker/sink; bounded delivery retry/dedupe, HTTP fakes/tests, no real token/message during implementation. | NOT STARTED |
| 12.1d | Streamlit read-only dashboard using local derived data and offline fixtures/tests. | NOT STARTED |
| 12.1e | Combined offline observability regression/failure isolation, Stage 11 golden preservation and final 12.1 audit. | NOT STARTED |

Keep observability separate from strategy, pure risk, exchange adapters and RuntimeStore. Minimal future integration hooks require narrow review; this decision does not authorize changes to frozen production or duplicate schedulers/reconciliation. Future acceptance must prove deterministic IDs across restart, correct partial/unknown/confirmed transitions, exact serialization/nullability, bounded sanitized sinks and catch-up, honest unavailable history, atomic snapshot readability/freshness and unchanged behavior under observability failures/deletion.

Preserve the no-rearm golden **54 decisions / 2 placements / 2 fills / 0 cancellations / 1 risk epoch**, exact IDs/links, amounts/prices/signed fees, final ownership and restart. All Stage 11 E2E/latch/rearm/accounting and Stage 5 EMA/next-OPEN regressions remain frozen. Tests use local synthetic data/fake transports only; no application network, credential, real DB, real notification or authenticated broker operation is needed.

## Stage 12.1a validation and publication

Exactly this Decision 023, PROJECT_STATE.md, README.md and CHANGELOG.md change. Production/tests/schema/dependencies/previous Decisions/notebooks/data/results remain unchanged; no new code/tests or logging package is created. Local execution passed the unchanged **2,943-test full suite**, failures/errors/skips **0/0/0**; `pip check`, `git diff --check` and `git diff --staged --check` pass. These are local results, not CI evidence.

After validation, commit/push normally to main as explicitly authorized, without force push/history rewrite; verify HEAD == origin/main and clean worktree. This Git publication is separate from application-network operations. Stage 12.0 remains FROZEN at `0b275c9`; Stage 12.1 STARTED / INCOMPLETE, 12.1a COMPLETE / owner review pending, 12.1b–e and 12.2–12.4 NOT STARTED. Stage 12 remains INCOMPLETE; v1.0.0 NOT RELEASED. Do not begin 12.1b automatically.

```text
Demo API credentials: NOT USED
Live API credentials: NOT USED
Telegram bot token: NOT USED
Real Telegram message: NOT SENT
Authenticated Bybit Demo read/order/cancel: NOT RUN
Authenticated Bybit Live read/order/cancel: NOT RUN
Real user DB migration/activation/rearm: NOT RUN
```
