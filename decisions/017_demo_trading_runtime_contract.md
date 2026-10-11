# 017 — Demo Trading Runtime Contract

- Date: 2026-10-11
- Status: Accepted
- Scope: Stage 10.1 architecture/documentation only, ready for owner review. No runtime implementation or broker run is authorized by this decision.
- Reviewed baseline: `4113ad653ccd46be40fafd165d78bf75589a2ce5` — `Complete Stage 9 Bybit demo exchange adapter audit`.
- Governing decisions: [010](010_generic_strategy_backtest_contract.md), [011](011_risk_and_position_sizing.md), [012](012_strategy_robustness.md), [013](013_bybit_demo_exchange_adapter.md), [014](014_read_only_account_and_order_state.md), [015](015_spot_market_order_lifecycle.md), [016](016_manual_demo_smoke.md); all unchanged.

## Context and scope

Stage 9 is COMPLETE. It provides explicit Demo reads, exact Spot normalization, separate action receipts, and optional bounded manual diagnostics. It provides no autonomous runtime. Stage 5 remains the frozen EMA baseline; Stages 6–8 and their next-OPEN, accounting, sizing and research contracts stay frozen.

Stage 10 will own bot identity, closed-candle handling, startup synchronization, local state, ownership, reconciliation, action planning/submission, ambiguous outcomes, restart recovery, durable checkpoints, bounded safe-read retries, scheduling and graceful shutdown. This decision describes future behavior; names below are contract concepts, not implemented Python APIs, classes or SQL tables.

Initial scope is **one Bybit Demo account, one bot, one strategy instance, one symbol and one timeframe; Spot LONG/FLAT, MARKET only, no leverage, borrowing or shorts**. The initial strategy is the unchanged `generate_ema_signals`, configured explicitly with its existing defaults: EMA20/50, 50 initialization-only candles, hourly interval `60`. Other intervals are rejected for this first implementation: the current strategy and canonical validator use one elapsed hour. Extensibility does not authorize changing those APIs.

No live/Testnet switch, derivatives, multi-bot allocation, WebSockets, ML, optimization, backtest/analytics rewrite, PostgreSQL, Redis, message queue or deployment is included. Stage 7 `position_fraction` is research sizing, not runtime authorization. Stage 11 owns later operational risk policy; Stage 12 owns full monitoring.

## Architecture and truth boundaries

```text
Closed-candle market-data gate → existing strategy → canonical desired intent
                                                       ↓
Persisted runtime journal + normalized broker evidence → reconciliation
                                                       ↓
                                                pure action planner
                                                       ↓
                                    durable intent → explicit authorization
                                                       ↓
                                     Stage 9.5 action adapter → Demo broker
                                                       ↓
                                  Stage 9.4 order/fill/account observations
                                                       ↓
                                      reconciliation → durable checkpoint
```

Future orchestration belongs in a focused runtime layer, separate from strategies, research/backtests and exchange parsing. Do not create that package in 10.1. Keep functions and small explicit records; no event bus, strategy framework, plugin registry or async framework is required. Stage 9 handles broker schemas and constraints; runtime consumes its normalized models, never raw SDK payloads. Runtime does not call historical next-OPEN execution/accounting to synthesize Demo fills.

| Evidence | Authority and limits |
| --- | --- |
| Strategy `desired_position` | What the strategy wants after a closed candle, integer 0/1; not proof of a holding or an order. `signal` remains LONG_ENTRY/LONG_EXIT/HOLD. |
| Persisted runtime journal | Which actions were authorized, which IDs belong to this bot, attempts/receipts already observed, and candles already logically handled. Intent is not execution evidence. |
| Broker observations | Authoritative reported orders, executions, fees and account balances. Reads are observations over bounded windows, not an atomic exchange snapshot. |
| Reconciled bot state | Confirmed ownership/exposure derived from the journal plus broker evidence. A pending action and partial exposure remain separate fields. |

Neither desired LONG nor a placement receipt proves LONG. Desired FLAT, cancellation acceptance, an empty execution window or an order not found proves no liquidation. Valid broker evidence may repair a stale local checkpoint atomically; contradictions or missing evidence cannot be repaired by guessing. Account totals are informational USD aggregates, not spendable USDT.

## Durable identity and configuration

The logical instance key is `(broker_id, account_binding, bot_id)`. `broker_id` is fixed to `bybit-demo`. `account_binding` is an operator-assigned stable label for exactly one Demo account/credential profile; `bot_id` is operator-assigned, unique within that account, 1–12 lowercase ASCII letters/digits. Neither changes at process restart. A PID, startup timestamp or random startup UUID cannot identify the bot.

Bind the instance to `strategy_id` (initially `ema_trend`), strategy implementation digest, exact strategy parameters, uppercase symbol, metadata base/quote currencies, timeframe code `60`, interval 3,600,000 milliseconds, runtime contract/schema versions and a digest of canonical non-secret configuration. Strategy implementation identity refers to strategy code, not the repository HEAD changing for a documentation commit. Configuration includes the explicit BUY budget, history anchor and operational time/read bounds. Changes require a stopped, reconciled, explicitly reviewed migration; they do not silently create a fresh position or erase old IDs.

An exchange-verified account identifier is recorded/compared when genuinely available. Stage 9.4's optional `account_id` is caller-owned; it is not a verified UID. The present boundary cannot independently authenticate the operator's account label. Initial operation requires explicit correct profile binding and no concurrent external management of bot-owned inventory/orders. A verified mismatch, uncertain account binding or reused namespace HALTs. Never store credentials or a hash of credentials as identity; key rotation does not automatically create another bot.

## Order ownership and logical action identity

Only an exact persisted action/link mapping with matching broker ID (when known), symbol, side, MARKET type and BASE/QUOTE unit establishes ownership. A symbol, wallet holding or matching link prefix alone is insufficient. A prefix identifies a candidate requiring verification; an unrecorded candidate in this bot's namespace is a collision or lost history, not an order to adopt/cancel. Unrelated orders are excluded from owned reconciliation and never cancelled; conflicting unrelated orders on the managed symbol block activation until the operator resolves them.

The current [Bybit orderLinkId contract](https://bybit-exchange.github.io/docs/v5/order/create-order) permits up to 36 letters/digits/dashes/underscores and requires uniqueness. It agrees with Decision 015 and its tested 1–36 ASCII validation; checked on 2026-10-11. Initial runtime placement links will use `bot_id + "-" + first_23_hex_characters(logical_action_id)`, at most 36 characters. This is a runtime policy, not a Stage 9 adapter change.

`logical_action_id` is the full lowercase SHA256 hex digest of canonical intent: contract version, instance key, configuration digest, candle-open UTC milliseconds, action kind ENTRY/EXIT, side, unit and authorized amount. Canonical encoding is UTF-8 JSON with sorted keys, compact separators, ASCII encoding and plain exact decimal amount strings; no floats, process values or current observation time enter this identity. One action is allowed per logical candle decision, irrespective of later changes to balances or amounts. The complete intent and full digest are retained, not only the shortened link.

Both full action ID and link have durable uniqueness constraints for the account; IDs and ownership tombstones are never reused after completion or retirement. Detect a truncated-digest collision, conflicting broker identity or different intent for an existing link → HALT, never generate a replacement ID. Broker-side global uniqueness cannot be proved from limited reads, so a possible collision also fails closed. Losing the journal does not authorize reinitializing the same namespace.

Reconciliation always uses the original persisted link/known broker ID. Restart, lost receipt, timeout or a different wallet balance cannot create another order. A new placement link requires a genuinely new eligible closed-candle decision, safe reconciled state and no unresolved action. Rejected/preflight-failed actions are not retried on HOLD. Automatic replacement of an uncertain, partially filled, cancelled or dust-bearing action is excluded.

Cancellation is a separate explicit operator authorization against an exactly known owned broker order. Journal its stable caller control ID, target/parent action and original order link before calling Stage 9.5 `cancel_order`; no new placement link is sent. Repeated operator control IDs do not create repeated cancellation attempts. Initial strategy/scheduler/shutdown policy never automatically cancels. The concrete operator-control API is deferred to 10.7 review.

A runtime cancellation requires a healthy journal, fresh exact owned-order evidence and reconciled ORDER_PENDING state. STARTING, SYNCHRONIZING, UNCERTAIN, HALTED and STOPPING cannot dispatch it; operator rearm/repair must first restore a safe state. Explicit operator cancellation is not an exception to ownership or crash-consistency rules.

## Finite runtime state machine

The exact proposed states are below. They do not replace Stage 9 `OrderStatus` or the persisted action phase. `owned_base_quantity`, desired intent and pending action are explicit independent records; partial exposure may exist while ORDER_PENDING/UNCERTAIN.

| State | Meaning, allowed events and next states | Required durable evidence |
| --- | --- | --- |
| STARTING | Acquire single-instance protection and load/validate identity/store. Valid startup → SYNCHRONIZING; fatal validation → HALTED; shutdown → STOPPING. No strategy action. | Existing identity/schema and startup checkpoint when the store is healthy. |
| SYNCHRONIZING | Read/reconcile owned broker history and restore candle/strategy state. Coherent evidence → FLAT, LONG or ORDER_PENDING; missing evidence → UNCERTAIN; fatal conflict → HALTED; shutdown → STOPPING. | Reconciliation observations, restored history/frontier, owned evidence and pending intent. |
| FLAT | Confirmed zero owned base quantity, no unresolved owned action. Fresh eligible entry → ORDER_PENDING after durable authorization; HOLD/no applicable event stays FLAT; lost freshness → SYNCHRONIZING; uncertainty/fatal → UNCERTAIN/HALTED; shutdown → STOPPING. | Zero owned inventory evidence, decision journal and reconciliation freshness. |
| LONG | Confirmed positive owned base quantity, no unresolved owned action. Fresh eligible exit → ORDER_PENDING; no applicable event stays LONG; stale/uncertain/fatal/shutdown transitions as for FLAT. No extra BUY or rebalance. | Owned fills/fee effects and exact remaining base quantity. |
| ORDER_PENDING | One owned order lifecycle is unresolved, optionally with one explicitly authorized cancellation control for that same order; receipt is not finality. Reads may keep this state, confirm terminal evidence → FLAT/LONG, expose ambiguity → UNCERTAIN, or fatal conflict → HALTED; shutdown → STOPPING. New candle intent may be recorded but cannot queue another order. | Original IDs/authorization, attempt/ack phase, partial fills, reconciliation deadline and any subordinate cancellation record. |
| UNCERTAIN | Acceptance, identity, fills or state cannot yet be established. Bounded safe reads may restore SYNCHRONIZING/ORDER_PENDING/FLAT/LONG with complete evidence; exhausted budget/contradiction → HALTED; shutdown → STOPPING. No mutations. | Original unresolved action/evidence and safe reason, retained across restart. |
| HALTED | Latched refusal to act. Safe diagnostics are allowed; remain HALTED until explicit operator repair/rearm → SYNCHRONIZING, or shutdown → STOPPING. No placement or automatic cancellation. | Safe halt reason/time, pending work and last known exposure; rearm must be recorded. |
| STOPPING | Stop new decisions/mutations, preserve unresolved work and close resources; then exit. A later process always starts at STARTING, never resumes trading directly. | Prior operational state, pending action, last checkpoint and shutdown marker. |

Any transition not listed is forbidden. In particular STARTING cannot directly become LONG/FLAT/ORDER_PENDING on local claims alone; FLAT cannot become LONG from desired intent or acknowledgement; LONG cannot become FLAT on cancellation acceptance; UNCERTAIN/HALTED cannot place an order. Persist each logical transition with its evidence. If persistence itself is broken, fail without mutation and return a safe fatal diagnostic; do not overwrite corruption or pretend HALTED was durably saved.

The action journal distinguishes PREPARED, ATTEMPT_STARTED, ACKNOWLEDGED, UNKNOWN_OUTCOME, TERMINAL_CONFIRMED, REJECTED and ABANDONED_UNSENT. These are attempt/evidence phases, not alternative runtime position states. PREPARED is provably unsent only while no attempt-start checkpoint exists. Terminal action completion requires consistent status and all needed owned fills; rejection/unsent abandonment cannot erase an earlier unresolved attempt.

## Startup and restart recovery

1. Acquire the canonical account/instance lock before store/client access. Load the existing durable journal; fresh initialization is separately explicit, never an automatic empty fallback.
2. Validate schema, identity/configuration, strategy implementation and Demo routing. Respect a persisted HALT latch; no automatic rearm.
3. Enter SYNCHRONIZING; read normalized account, open orders, known owned orders and executions with finite bounds. Reconcile pending and ownership records first.
4. Restore the persisted candle-history anchor, verified history and last logically processed candle; rebuild strategy intent using the unchanged strategy.
5. Establish safe owned exposure, action uncertainty and freshness; commit the coherent checkpoint. Only future eligible decisions may then authorize an order.

Startup must never place merely because the latest restored strategy row wants LONG. Historical bootstrap rows initialize/replay strategy only. A fresh store starts with zero owned holdings; arbitrary pre-existing BTC remains unrelated. If past bot history may exist but is unavailable, initialization HALTs rather than claiming FLAT.

| Restart point | Required recovery |
| --- | --- |
| FLAT | Verify no unresolved/candidate owned action and zero owned inventory; unrelated balances are not adopted. |
| LONG | Verify persisted owned fill history, known order status and current account coverage; restore owned quantity without a second BUY. |
| After placement acknowledgement | Query the known exact broker ID and separate executions; restore pending/partial/final evidence. Receipt alone cannot confirm a fill. |
| After ambiguous placement | Reconcile the original link and any known broker ID; preserve uncertainty if not observed. Never resend or invent a new ID. |
| After partial fill | Deduplicate executions, retain actual owned exposure and remaining pending work; no second action until terminal coherent evidence. |
| After cancellation acknowledgement | Query original order/fills; it may still be pending, cancelled, partially cancelled or filled concurrently. |
| Crash before checkpoint | Durable pre-send intent/attempt marker enables recovery even without a receipt. Broker may have advanced; rebuild evidence rather than trusting old quantity. |
| PREPARED but definitely no attempt | Mark ABANDONED_UNSENT on restart; do not replay a historical purchase. Keep its IDs consumed. |

## Bounded reconciliation and adapter limits

One reconciliation round obtains account/open-order observations, relevant execution observations and exact-ID state for known pending orders, validates identities/units, then compares them with the action/fill journal. There is at most one unresolved owned order lifecycle. A cancellation control remains subordinate to that original placement/action, never replaces its IDs or permits another order; at most one cancellation control is unresolved. Only complete successful reads contribute to an atomic new checkpoint; late page/parse failures leave the previous checkpoint intact.

For lost acknowledgement with no broker ID, search complete open-order and execution observations for the **exact original orderLinkId**. A matching execution may reveal the broker ID; validate it, then use `get_order`. Prefix matches alone do not prove ownership. Persist the discovered ID, never rewrite the logical action/link. Missing links, missing candidate orders or incomplete execution coverage remain uncertain.

Stage 9.4 `get_order` accepts only broker order ID; it has no lookup-by-link/history-discovery API. `get_open_orders` is open-only and executions use a default seven-day window, both at most 100 pages. Thus a filled order with a lost acknowledgement, absent link or expired observation window may be unrecoverable through current primitives. A newer empty read is not historical completeness. Known persisted executions remain usable after they leave a broker window, but missing historical evidence cannot be fabricated. Initial Stage 10 must UNCERTAIN → HALT when its recovery budget cannot resolve this; any future narrow read-adapter extension needs separate review and tests, not raw SDK bypass or an automatic change to frozen Stage 9.

Previously fully reconciled terminal orders/fills retain their durable evidence when broker retention expires; they need not be rediscovered forever to retain a LONG holding. An empty newer window cannot erase that proven history. Recheck current open-order candidates and account coverage without claiming those reads prove all historical activity. This exception never promotes a pending/uncertain or incomplete old action to terminal from local intent alone.

Validate expected symbol/side/type/unit, requested authorization bounds and matching action identity. For quote BUY, reported unused budget is valid; do not require a FILLED order to spend the entire budget. Reconcile cumulative base execution quantities with deduplicated base fills; retain broker quote values separately, without mixing dimensions or inventing rounding tolerances. A terminal status with missing fills cannot finalize the position. Repeated identical execution IDs are applied once; the same ID with different financial fields HALTs.

| Outcome | Consequence |
| --- | --- |
| Confirmed FLAT | No unresolved action, complete owned history gives zero base quantity; persist FLAT. |
| Confirmed LONG | No unresolved action, complete owned history gives positive base quantity and sufficient reported wallet coverage; persist LONG. |
| Pending | Observed nonterminal order/partial fill; persist ORDER_PENDING and exposure separately. |
| Recoverable mismatch | Complete broker evidence advanced beyond local state; apply new owned fills/IDs atomically, then select the confirmed state. |
| Uncertain | Missing/UNKNOWN/delayed evidence or inconsistent views possibly due to latency; no mutation, bounded further reads. |
| Fatal inconsistency | Ownership collision, impossible transition, conflicting duplicate fill, oversold inventory, unsafe route, or unresolved deadline → HALTED. |

Reads are not exchange-transactional: a race between order/fill/account observations first blocks action, rather than manufacturing a coherent result. Reconciliation must have configured finite round, attempt and elapsed-time limits; no read-until-success loop. Operator intervention is required after unresolved limits.

## Bot-owned position and authorization

Owned inventory is an exact base-quantity journal of verified owned BUY/SELL fills with broker-reported base-currency fee/rebate effects. Quote/other-currency fees remain separate reported facts; no PnL, fee conversion or modeled slippage is invented. Nonzero fee with missing currency prevents exact ownership settlement → UNCERTAIN/HALT. Zero fee needs no invented currency. Negative owned quantity or mismatched fill identity HALTs.

Wallet inventory alone never proves ownership. Extra pre-existing holdings remain outside this journal. Account base balance must cover confirmed owned quantity, but excess is not sell authorization and does not resolve missing fill evidence. External withdrawals/trades involving owned inventory are outside the initial cooperative single-bot policy; detected disagreement HALTs. Fungible wallet balances cannot prove provenance independently of the owned history. A terminal partial BUY can establish a smaller LONG; a terminal partial SELL leaves a LONG remainder. Dust is retained as owned exposure, never rounded to FLAT; an unsellable remainder HALTs for operator review, with no top-up, split or automatic retry.

Initial sizing policy is **an explicitly operator-configured fixed positive finite exact quote budget per new BUY**, with no amount default and no wallet-derived percentage/compounding. SELL authorizes at most the exact reconciled owned base quantity, never the whole wallet. Both units/currencies are bound to current symbol metadata; Stage 9.3/9.5 round down and reject constraints without increasing, clipping or splitting authorization. Fees/fills remain exchange observations, not Stage 7 research math. Quote authorization is the exchange request budget, not a guarantee about total fees or a modeled fee-inclusive quantity.

Stage 9.4's USD availability and missing per-coin spendability cannot be used to estimate spendable Spot cash. Do not compute wallet-minus-locked as authorization. The operator authorizes the fixed request; the non-borrowing broker may reject insufficient funds. A future policy requiring independently verified spendable cash needs a reviewed read capability. Stage 11 may later add max order/exposure, loss/drawdown and other operational risk limits; none is silently supplied by `position_fraction` here.

## Strategy history and closed-candle handling

Use only the existing `generate_ema_signals` and canonical validation. Its EMAs use `adjust=False`, first-close seeding, 50 initialization-only HOLD/FLAT rows and eligible crossover events from row 51. Eligibility or fast EMA above slow EMA alone does not create an entry. Do not add a live EMA formula, seed a new sliding history window on each wake or alter strategy state to match broker holdings.

Fresh initialization chooses and persists one explicit history anchor before activation, fetches contiguous completed hourly candles from it, and stores validated normalized candle values. It needs at least warm-up plus one eligible row; insufficient history waits without synthesizing a signal. Initial history is bootstrap-only, so no historical event trades. Restart/long downtime restores that same history and anchor, appends verified missing candles, and deterministically rebuilds the strategy prefix. Strategy parameters/code, stored candle contents and anchor cannot change silently. Retain the full accepted prefix initially; an incremental/compacted equivalent needs separate exact-prefix tests and review.

Candle identity is `(symbol, timeframe, candle_open_utc_ms)`; interval `60` means one elapsed hour on the UTC hourly grid. Closing boundary is open time + one hour. A validated authoritative market/server-time observation must establish that boundary has passed and the complete OHLCV is available; local sleep or presence in a REST response alone is insufficient. Only a contiguous, unique, chronological closed prefix enters the strategy. Broker newest-first pages may be explicitly normalized at the market-data boundary and checked across page overlaps; malformed timestamps/conflicting duplicates cannot be silently sorted away or repaired inside strategy/backtest code.

Stage 9 currently exposes no normalized closed-candle/server-clock runtime feed. Stage 10.4 must review the read-only transport/clock proof and place broker-specific parsing behind the exchange/data boundary; it cannot quietly add raw SDK access to strategy/runtime planning. The existing public Kline helper may supply Spot history without becoming an authenticated live-trading route, but the frozen research snapshot is not a current trading feed. Do not silently replace that snapshot or broaden authenticated/order capabilities to obtain market data.

`last_processed_candle` is the OPEN timestamp of the highest **durably handled** closed decision, not the latest fetched/in-progress row or the last fill. Persist one unique decision row per candle, its input fingerprint, canonical signal/desired intent and disposition (BOOTSTRAP, REPLAY_ONLY, NOOP, WAIT, ACTION or HALT). Commit that row and any resulting action intent in the same transaction as advancing the frontier. A duplicate with identical accepted data returns the recorded outcome; conflicting data for a committed candle HALTs. Out-of-order unseen rows block the contiguous frontier; missing candles require bounded backfill, never forward-fill or skipping an hour as if it existed.

Exactly-once means **one committed logical decision/action authorization per candle**, not that pure calculations cannot be repeated after a crash. Prefix reconstruction/recomputation is allowed without submitting historical actions. Unique decision/action constraints and the pre-send journal prevent restart from authorizing the candle twice. This cannot promise exactly-once exchange delivery; uncertainty is explicitly preserved.

After downtime, backfilled decisions are REPLAY_ONLY; historical signals never become a queue of orders. Mark bootstrap/replay cutoff durably. Only a new candle closing after completed synchronization, with fresh broker evidence and within an explicit configured decision-age bound, is action-eligible. Delayed current data may be awaited within that bound; expired decisions are replay-only. A missed exit or intent change while a BUY/SELL was pending cannot trigger a stale replacement: if safe owned state and actionable intent cannot align under fresh-event rules, HALT for review. Fresh flat startup may record desired LONG without owning it; wait for a new legitimate entry event rather than adopting holdings or buying immediately.

Decision timing remains causal: completed candle → available strategy decision → later submission → actual broker execution timestamps/prices. Demo is not guaranteed to fill at next OPEN or at historical prices. Decision 010's historical N → N+1 OPEN and final-candle no-fill behavior remain entirely unchanged.

## Pure action planner

The future planner receives already validated canonical intent, decision eligibility/freshness, finite runtime/reconciliation state, confirmed owned exposure, pending action and explicit configured authorization. It generates no indicators, reads no wallet/SDK, writes no journal and sends no order. Orchestration validates/persists its result before dispatch.

| Output | Contract |
| --- | --- |
| NOOP | HOLD, already satisfied intent, or an event with no owned exposure change to authorize. |
| PLACE_BUY | Fresh eligible LONG_ENTRY/desired 1, confirmed FLAT, no pending action and explicit quote budget. |
| PLACE_SELL | Fresh eligible LONG_EXIT/desired 0, confirmed LONG, no pending action and exact owned base authorization. |
| WAIT | Known pending action or temporarily late data within accepted limits; no queued replacement order. |
| RECONCILE | Stale/missing broker evidence or startup synchronization required; no mutation. |
| HALT | Fatal configuration/ownership/transition problem, exhausted recovery or unresolvable missed-action mismatch. |

Pending and unsafe state take precedence over desire. No pyramiding or target-weight rebalancing. Desire changes during pending work are journaled, not traded concurrently. Separately authorized exact-owned cancellation uses the same journal/reconciliation discipline, outside automatic strategy planning; there is no automatic CANCEL planner output.

HALT/RECONCILE/WAIT guards take precedence over the NOOP/HOLD rule. NOOP requires a compatible safe state or an explicitly recorded bootstrap-only intent difference; it cannot conceal a missed exit or unresolved ownership. Inputs carry the durable bootstrap/replay eligibility information needed to distinguish those cases.

## Persistence and minimum durable records

Choose **local SQLite through Python's standard-library sqlite3**, one database per canonical account/instance on local durable storage. This avoids another dependency and makes candle/intent/fill/checkpoint changes transactional, with unique constraints. Atomic JSON replacement would require a growing all-history rewrite and extra cross-record consistency handling. No database file, schema, runtime directory or new dependency is created in 10.1; concrete table/API layout belongs to 10.3.

Initial durability settings are `journal_mode=DELETE`, `synchronous=EXTRA`, `foreign_keys=ON`, with short explicit transactions and verified settings; enable `fullfsync` on supported macOS. EXTRA also syncs the deleted rollback journal's directory; durability still assumes working local storage/sync semantics. See [SQLite synchronous/fullfsync](https://www.sqlite.org/pragma.html#pragma_synchronous) and [atomic commit](https://www.sqlite.org/atomiccommit.html). No transaction spans a network request and no database transaction is claimed atomic with a broker action.

| Durable record | Exact minimum fields / contents |
| --- | --- |
| Identity/configuration | `schema_version`, `runtime_contract_version`, `broker_id`, `account_binding`, optional verified `broker_account_id`, `bot_id`, `strategy_id`, `strategy_implementation_digest`, `strategy_parameters`, `symbol`, `base_currency`, `quote_currency`, `timeframe`, `interval_ms`, `configuration_digest`, `buy_quote_budget`, finite data/read/reconciliation policy settings. |
| Checkpoint | `checkpoint_sequence`, `runtime_state`, `last_processed_candle`, `latest_desired_position`, `last_reconciled_at`, observation timestamps/coverage, `current_logical_action_id`, `owned_base_quantity`, `position_evidence_state`, safe `halt_reason`/time, optional operator rearm record, `shutdown_marker` and prior operational state. Missing values are explicit, not fabricated zeroes. |
| Candle/decision history | `history_anchor`, bootstrap/replay cutoff, normalized completed candles and fingerprints; per-candle open time, available time, canonical signal/desired position, disposition and action reference. Unique candle key and contiguous committed frontier. |
| Action history | Full `logical_action_id`, original `order_link_id`, optional known `broker_order_id`, originating candle or explicit caller control ID, action kind/parent target, intended side/unit/currency, exact `authorized_amount`, submitted amount when observed, action phase, `attempt_count`, acceptance/cancellation receipt fields when observed, last external/internal order state, terminal evidence/reason, reconciliation deadline/remaining bounds. Preserve completed IDs/tombstones. |
| Owned fill history | Unique `(broker_id, account_binding, broker_execution_id)` plus owned action/order/link, symbol/side, executed base quantity, price, signed fee/currency, broker execution/observation times. Ownership references and applied inventory effects are part of the same transaction. |

Persist amounts as canonical exact decimal TEXT, identities as strings, enumerated state/phases and integer UTC milliseconds/sequence values. Do not serialize floats for order/inventory money, pickle, SDK objects, reprs, raw response dumps, headers, environment mappings or secrets. Strategy candle representations must replay identically; their validated numeric input is distinct from exact order money.

Validate schema/version, enums, identity, amounts, references and invariants on load; use integrity checks. Unknown schema, corruption, missing existing journal, failed disk write or incomplete required evidence fails closed. No automatic reset, repair, destructive migration or rollback to a stale backup that might erase sent intent. Backups are useful only with full reconciliation; review recovery before enabling actions.

## Crash-consistent action ordering

1. Validate reconciled state/fresh decision and explicit authorization; derive the stable logical action/link.
2. In one durable transaction, insert the unique decision and PREPARED intent with all IDs/amounts, record pending work, and advance `last_processed_candle`.
3. Durably mark ATTEMPT_STARTED/`attempt_count=1` **before** calling the action adapter. Failure to commit means no call. A crash after this checkpoint, even before the network send, conservatively means possibly sent.
4. Call the unchanged Stage 9.5 adapter once. Its fresh normalization may reduce authorization; final submitted amount is persisted when observed, never assumed from a lost receipt. Store a valid acknowledgement separately; malformed/transport outcome → UNKNOWN_OUTCOME. Safe preflight failure/confirmed current rejection is recorded distinctly, without automatic retry.
5. Later use Stage 9.4 reads to reconcile separate status/fills; atomically apply deduplicated owned executions, inventory, terminal evidence and the new checkpoint.

Crash after send/receipt but before local update leaves the original attempt recoverable. No receipt rollback erases intent. An attempted action never automatically issues a second placement/cancellation, even with the same link: links are correlation, not a guarantee of SDK exactly-once delivery. A confirmed rejection proves only that request, not the absence of an older order using a colliding ID. Abandon only provably unsent or fully reconciled rejected work, never an unknown potentially filled action.

## Scheduler, read retries and error classification

Future scheduling handles only the configured hourly timeframe. Wake near the next UTC closing boundary, then verify market time/data closure and reconciliation freshness; do not trade solely because sleep elapsed. Serialize all work; one action at a time. Late/missing/stale data blocks placement. No high-frequency polling requirement or separate scheduler process is introduced.

Safe transport read retries may use **at most three total attempts**, with bounded 1-second then 2-second backoff, under a finite configured reconciliation/elapsed-time budget. Retry an entire failed atomic read, not an invented partial result. Known permanent authentication/configuration/constraint errors, malformed data and ownership contradictions are not blindly retried. Broker error-code classification must be verified in 10.5; unknown API codes default to fail closed. Do not alter Stage 9 SDK one-attempt settings. No auto-placement/cancellation retry exists.

The runtime deadline is checked between bounded calls; it is not a promise to interrupt an in-flight Stage 9 paginated method. Existing SDK timeouts, one attempt and 100-page safety bounds still limit each call. Scheduler/reconciliation tests must account for that worst case, track persisted action deadlines across restart and HALT after finite unresolved bounds; no resetting the budget on every wake. Use monotonic elapsed time during a process and validated persisted UTC deadlines for recovery; unsafe clock drift blocks activation.

| Error class | Initial response |
| --- | --- |
| Transient read timeout/verified temporary API failure, late candle | Bounded safe reads/backoff or WAIT; no mutation without fresh evidence. |
| Ambiguous action, malformed acknowledgement, delayed fills, mismatched read views | UNCERTAIN, original-ID reconciliation only; never resend. |
| Unsafe Demo/account binding, corrupt store, collision, impossible transition, conflicting fill, irreconcilable ownership or exhausted deadline | HALTED; safe reason, no automatic broker action, operator repair required. |

Keep safe operation/code/type diagnostics and Stage 9's client-local disabled SDK logger; no global suppression, credential logging or raw SDK exception text. These classifications do not require an exception framework in 10.1.

## HALT, graceful shutdown and single-instance protection

HALTED refuses new placement and automatic cancellation/liquidation. Preserve pending intent, owned exposure and safe reason when the store is healthy. Diagnostics may make bounded read-only calls but cannot silently unlatch HALT. Explicit operator repair/rearm must re-enter synchronization; it does not license an ambiguous resend.

Shutdown stops scheduling/new decisions before persisting STOPPING and the last known operational state/pending work. Finish or safely interrupt only at documented transaction/request boundaries, close the SDK and database, and release the lock last. Pending orders are not declared terminal. No automatic SELL, cancel-all or exit liquidation. A clean shutdown marker means resources/checkpoint were handled, not that the broker is FLAT; restart still reconciles.

Choose a process-lifetime exclusive nonblocking **OS file lock** (`fcntl.flock`, `LOCK_EX | LOCK_NB`) on a canonical local account lock file, acquired before store/session access. Initial platforms are the current macOS/POSIX host; unavailable locking fails closed. See [Python fcntl](https://docs.python.org/3.11/library/fcntl.html). Hold the same file descriptor through shutdown; do not unlink/recreate the locked file or use existence/PID as ownership. A competing process exits before broker calls. Account-level protection is stronger than bot-only protection and matches the one-bot/account scope; database identity prevents another bot configuration reusing the store. All launch paths must use the same canonical account registry/lock path, regardless of alternative DB path. No network filesystem, multi-host, distributed lease or leader election. This protects cooperating runtime launches, not unrelated external clients.

## Stage 10 roadmap

| Milestone | Scope | Status after 10.1 |
| --- | --- | --- |
| 10.1 — Runtime Contract / Architecture | This decision and status documentation only. | COMPLETE; Accepted, ready for owner review. |
| 10.2 — Runtime State Model + Pure State Machine | Small validated state/intent/evidence records and deterministic transitions; no broker orchestration. | Next; NOT STARTED; explicit approval required. |
| 10.3 — Durable Runtime Persistence + Single-Instance Lock | SQLite transactions/schema/integrity, durable IDs/frontier, canonical OS lock. | NOT STARTED. |
| 10.4 — Closed-Candle Market Data Gate | Hourly closure/freshness/continuity, anchored history and duplicate protection. | NOT STARTED. |
| 10.5 — Startup / Broker Reconciliation | Normalized bounded reads, ownership, recovery gaps/uncertainty and halt policy. | NOT STARTED. |
| 10.6 — Runtime Action Planner + Explicit Demo Sizing Policy | Pure planner, fixed explicit quote BUY/owned base SELL authorization. | NOT STARTED. |
| 10.7 — Single-Cycle Demo Runtime Orchestration | One authorized journaled decision/action/observation cycle, separate receipts/fills. | NOT STARTED. |
| 10.8 — Long-Running Candle Scheduler | Serialized hourly scheduling, bounded safe reads, stop/shutdown boundaries. | NOT STARTED. |
| 10.9 — Restart / Crash / Ambiguous-Action Recovery | Crash-point and restart scenarios, original IDs, no duplicate action or false certainty. | NOT STARTED. |
| 10.10 — Runtime Integration Regression + Optional Explicit Demo Run | Offline end-to-end gates; any actual Demo run needs separate explicit owner authorization and recorded evidence. | NOT STARTED. |
| 10.11 — Final Stage 10 Audit + Docs | Scope/ownership/crash/timing/secret/regression audit and honest closure. | NOT STARTED. |

## Post-Stage-10 direction and exclusions

| Future stage | High-level direction only; not started or implemented |
| --- | --- |
| 11 — Runtime Risk Management | Maximum order/exposure, daily loss/drawdown, stale-data kill policy, repeated API failure breakers, manual kill switch. |
| 12 — Observability & Monitoring | Structured events, orders/fills/reconciliation, health, metrics, alerts and diagnostics. |
| 13 — Long-Running Demo Validation | Multi-day/week evidence, disconnect/restart, partial/ambiguous actions, missing candles/errors, expected versus observed behavior. |
| 14 — Live Readiness / Production Hardening | Strict environment separation, production secrets, supervision/deployment, backups/recovery, auditability and operator procedures. |
| 15 — Controlled Live Trading | Minimal authorized capital/size, one strategy/symbol/account, reviewed risk limits, manual kill and continuous reconciliation. |

No detailed Stage 11–15 contract or implementation is frozen now. Stage 10 correctness guards (closure, ownership, durability, HALT) are not a complete runtime risk platform. No claim of profitability, actual Demo fill quality, live-money safety or deployment readiness follows from offline tests or this ADR.

## Acceptance and preservation gates

Stage 10.1 is complete when the identity/ownership/ID/state/truth/startup/restart/reconciliation/candle/planner/sizing/persistence/crash/retry/HALT/shutdown/lock contracts above and the exact roadmap are documented. Accepted follows the existing contract-milestone convention; owner review does not automatically authorize 10.2 or a Demo run.

Future implementation must test synthetic boot/restart and every crash boundary, duplicate/conflicting/missing candles, lost acknowledgements, partial fills, cancelled/filled races, unknown statuses/windows, unrelated inventory/orders, ownership/ID collisions, fee-unit uncertainty, persistence corruption and duplicate-process refusal. Preserve existing APIs, financial values/tolerances, notebooks, data/results, Demo routing, diagnostics and all frozen regressions. Do not broaden Stage 9 mutation dispatch beyond place_order/cancel_order or put broker access in strategies/backtests.

The 10.1 gate runs the unchanged full suite once plus `pip check` and `git diff --check`, verifies protected-file/data/package preservation, and adds zero tests. No notebook execution, installation, session construction, authenticated API call, order, runtime state database, loop, scheduler or auto-wiring is performed. Stage 9 remains COMPLETE; Stage 10 has STARTED and is INCOMPLETE; 10.1 is COMPLETE and ready for owner review; 10.2 is next and NOT STARTED. No automatic commit/push or next milestone.
