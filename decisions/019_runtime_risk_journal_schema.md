# 019 — Runtime Risk Journal Schema v2 and Explicit Migration Contract

- Date: 2026-10-15
- Status: Accepted
- Scope: Stage 11.3a architecture/documentation only. No schema or persistence implementation is authorized in this commit.
- Frozen baseline: `ffb85663af831f5b723bb949c764ac85b3736683` — `Add pure runtime risk engine`.
- Governing contracts: [017 — Demo Trading Runtime](017_demo_trading_runtime_contract.md) and [018 — Runtime Risk Management](018_runtime_risk_management.md), unchanged. Stages 11.1 and 11.2 are independently owner-reviewed/FROZEN.

## Authority and current implementation

Stage 11.3a is an internal contract subphase of Stage 11.3. It accepts the future durable risk representation and explicit migration boundary; Stage 11.3 remains INCOMPLETE. Stage 11.3b implementation requires separate owner review/authorization after this contract is independently frozen. Stage 11.4 is not started or authorized here.

**Current RuntimeStore remains schema v1. No migration has run and no risk persistence exists.** Stage 11.2 remains a standalone pure engine. This decision changes no Python, tests, SQLite, dependencies, previous Decisions, notebooks or data/results, and authorizes no broker activation.

## Version selection and database boundary

The frozen v1 store has six tables: `identity`, `candles`, `actions`, `decisions`, `fills`, `checkpoint`. None represents risk configuration, epoch lineage, hourly valuations, virtual cash/equity/peak/daily baseline/PnL, trip notification/latch, verdicts or action risk approval. Do not overload existing fields with unrelated meanings.

Select **`SCHEMA_VERSION = 2` for future Stage 11.3b**. Keep `RUNTIME_CONTRACT_VERSION = 1` unchanged; changing it would require a separately justified implementation review. Both the identity row's schema version and SQLite `PRAGMA user_version` must identify v2 after a successful migration. The pure risk contract version is a separate persisted identity, initially 1, not a substitute for either runtime or schema version.

Keep risk records in the **same canonical RuntimeStore SQLite database under the same RuntimeAccountLock**. Add exactly four conceptual tables to the existing six:

```text
risk_configurations
risk_epochs
risk_valuations
risk_verdicts
```

No risk.sqlite3, risk.db, second store, sidecar JSON or cross-store commit protocol. Stage 11.4 needs one local transaction for risk approval plus the Stage 10 decision/action/frontier. Separate stores cannot provide that boundary.

Existing local storage/path safeguards, account lock, canonical Decimal TEXT, integer UTC milliseconds, DELETE journal, EXTRA synchronization, foreign keys ON, macOS fullfsync, bounded reads/writes, checkpoint CAS, action phase graph and indeterminate-commit handling remain authoritative. Exact SQL/index definitions and immutable Python persistence-record names/signatures belong to 11.3b review/tests.

## Explicit migration only

Future v2 `RuntimeStore.open(...)` must **never silently migrate v1**. A recognized legacy v1 store fails with a fixed migration-required diagnostic. Unknown, malformed or partially converted schemas fail closed as integrity errors. No automatic ALTER/reset/delete/recreation, empty replacement database, implicit sidecar or best-effort repair. Ordinary open is not a migration entry point.

The future explicit operation is conceptually:

```python
RuntimeStore.migrate_v1_to_v2(lock, configuration_v2)
```

It requires the already-held canonical account lock, no simultaneously open RuntimeStore on that lock/database, an existing safe regular local database file, exact valid frozen schema v1, and caller-reviewed v2 RuntimeConfiguration. Missing files, wrong lock/account binding, open stores, unsafe paths, malformed/unknown schemas and already-v2 databases are errors, never migration success. It creates no session/client, inspects no environment/credentials and performs no broker/network I/O.

Migration must use an explicit version-aware frozen-v1 validator, not relax normal v2 loading or assume changing global SCHEMA_VERSION makes legacy records valid. Verify the actual six v1 table definitions, indexes, version metadata, integrity, references, canonical data and all accepted v1 invariants before mutation. Bounded validation must not truncate excessive history.

### Identity and configuration compatibility

Compare every frozen non-secret runtime identity/configuration field with the v1 identity row. Only these row values are migration-owned:

| Field | Permitted change |
| --- | --- |
| `schema_version` | 1 → 2 |
| `configuration_digest` | Existing v1 digest → caller-reviewed valid v2 digest |

Everything else must remain exact: broker/account/bot binding, optional broker account ID, strategy ID/implementation/parameters, symbol/currencies/timeframe/interval, fixed BUY budget, history anchor, timing/read/reconciliation bounds and runtime contract version. No implicit adjustment to make a mismatched configuration fit.

Decision 017 binds configuration identity to schema/runtime contract information; the v2 configuration therefore has its explicitly reviewed digest. Migration adopts the supplied destination digest only after compatibility validation; it does not invent a new configuration or recalculate old logical actions under that digest. Existing action IDs, orderLinkIds and ownership mappings remain immutable/consumed. Future genuinely new actions may bind the new runtime configuration digest; historical IDs are never regenerated, relinked or resent.

### Transaction and failure contract

```text
canonical account lock already held; no store open
→ inspect exact v1 schema/version
→ fully validate v1 integrity, identity and data
→ BEGIN IMMEDIATE migration transaction; recheck source assumptions
→ create the four risk tables and required indexes/FKs
→ update identity schema_version/configuration_digest and user_version
→ validate the proposed exact v2 structure and preserved data
→ COMMIT
→ reopen/validate exact v2 with the supplied configuration
```

This is one bounded local SQLite migration transaction. No broker call, callback, credential access or unrelated external I/O occurs inside it. Preserve SQLite durability and path/lock identity checks. A failure before commit rolls back the structural/identity changes and leaves logical v1 contents unchanged; never accept a partial v2 table set. An indeterminate commit/rollback stops and requires reopening to determine exact v1 or v2 truth, without automatic migration retry/reset. Report success only after exact v2 validation; a post-commit failure cannot be described as proof that v1 remains.

Preserve all candles, decisions, actions, fills and checkpoint rows exactly, including canonical financial TEXT, IDs, pending work, HALT/STOPPING state, sequence, recovery counters/deadlines and bootstrap/replay/frontier/coverage facts. Only the two identity fields above and version/schema metadata change. No FLAT/LONG inference, uncertainty clearing, unsent abandonment, HALT rearm, ownership/economics change or checkpoint sequence reset. Exact logical rows/TEXT are the preservation guarantee; SQLite physical page layout need not remain byte-identical.

### Migration is not risk activation

A successful structural migration yields **exact schema v2 plus four EMPTY risk tables**. It invents no risk capital/configuration, epoch, book/equity/peak, daily baseline, trip status, verdict or approval. It never invokes risk initialization. Existing Stage 10 facts remain readable/recoverable without retroactive risk verdicts; migration must not fabricate approval for legacy actions.

Stage 11.3b does not change planner/cycle/scheduler/reconciliation behavior or create automatic risk enforcement. Stage 11.4 separately reviews when runtime activation requires a nonempty coherent journal and how pre-risk legacy history is distinguished from actions requiring LIVE approval. Structural v2 support alone is not an active risk gate.

## Canonical encoding and immutable configuration history

Use SHA256 lower-case 64-hex identities over UTF-8 JSON, `sort_keys=True`, compact separators `(',', ':')`, `ensure_ascii=True`. Encode exact Decimal values with the existing RuntimeStore canonical plain-string serializer; finite numeric value must survive without global-context rounding. Time/count/version values are validated integers, optional absent identities are JSON null. No floats, repr/pickle, process/random values, current time, credentials or raw SDK payloads in these digests.

`risk_configurations` is immutable history keyed by `risk_configuration_digest`. Its canonical payload contains exactly the semantic fields:

```text
risk_contract_version
risk_capital_quote
buy_quote_budget
max_entry_notional_quote
max_position_notional_quote
max_daily_loss_fraction
max_drawdown_fraction
max_entries_per_utc_day
base_currency
quote_currency
```

All six Decimal fields are canonical exact TEXT; the ENTRY limit/version are integers. Validate the frozen RuntimeRiskConfiguration invariants without coercion or clamp and verify digest/content correspondence on load. No mutable UPDATE API. Equivalent canonical numeric values yield the same digest; different policy/currency/version content must not alias. Unknown risk contract versions fail closed.

Risk configuration is separate from RuntimeConfiguration. Before initialization require exact risk/runtime BUY budget, base currency and quote currency equality. Risk policy cannot rewrite runtime identity, authorize another currency or reinterpret Stage 7 position_fraction. Persistence's numeric/time/count storage bounds may reject unsupported encodings without changing the frozen pure engine.

## Epoch lineage

`risk_epochs` retains immutable:

```text
epoch_id
epoch_sequence
risk_configuration_digest
started_at_ms
parent_epoch_id
```

The configuration digest references risk_configurations. Initial activation has sequence 1 and NULL parent. Future explicit rearm has sequence previous + 1 and the exact preceding epoch ID as parent. Sequences are unique and consecutive; no branch, missing predecessor, cycle or arbitrary active-epoch overwrite. The current epoch is the highest accepted sequence on this one instance's chain. Each epoch has its first ACTIVATION valuation at started_at_ms, supplying starting equity/peak/baseline; no duplicate independently mutable starting-finance fields are required.

Use deterministic SHA256 over canonical risk_configuration_digest, epoch_sequence, started_at_ms and parent_epoch_id. started_at_ms is the supplied accepted valuation boundary, not process start time. The exact encoding/field names and test vectors must be frozen in 11.3b tests. No UUID/PID/random/startup timestamp identity. Stage 11.3b can initialize **epoch 1 only**; Stage 11.6 alone owns future rearm epoch creation, preserving old history and continuous book/count semantics.

## Hourly risk valuations

`risk_valuations` has one immutable accepted record per `(epoch_id, valued_at_ms)`, plus symbol, timeframe and candle_open_ms. Bind its epoch/configuration and referenced durable candle through validated foreign-key/identity relationships:

```text
valued_at_ms = candle_open_ms + 3_600_000
timeframe = "60"
mark_price = referenced CandleRecord.close exactly
```

The referenced candle must already exist for ACTIVATION/REPLAY_ONLY and match the runtime's anchored instrument. LIVE may introduce it only in Stage 11.4's future atomic decision transaction. No ticker, account USD mark, arbitrary caller price, local-clock price or backtest fill price is accepted.

Persist these financial/state facts exactly:

```text
mark_price
virtual_quote_cash
owned_base_quantity
risk_equity
peak_risk_equity
utc_day_start_ms
utc_day_start_risk_equity
daily_pnl
entries_this_utc_day
trip_reason
tripped_at_ms
trip_pending_report
```

The epoch supplies RiskState.epoch_started_at_ms; valuation identity supplies valued_at_ms. This round-trips to the frozen RiskBook and RiskState without new financial meanings. Decimal fields use canonical exact TEXT; integer fields retain their validated bounds, and trip_pending_report is an explicit 0/1 persisted boolean decoded back to bool. Trip reason/time nullability and enum rules remain those of the pure engine. Drawdown's exact numerator/denominator derive from equity/peak, not another stored rounded ratio.

Persistence may import RuntimeRiskConfiguration, RiskBook, RiskState, initialize_risk_state and advance_risk_state from `risk.runtime_risk` to validate supplied facts/transitions. Reuse the pure accounting helpers when validating execution/book consistency; do not create a second risk formula. Dependency direction is **runtime/store → pure risk**, never pure risk → runtime/store. Frozen pure code/tests remain byte-identical unless a separately reviewed defect requires correction.

### Durable owned-fill evidence snapshot

Each valuation also retains `fill_evidence_count` and `fill_evidence_digest`. Select the complete durable bound-account owned fills known at acceptance with **executed_at_ms <= valued_at_ms**, including equality. Sort by `(executed_at_ms, broker_execution_id)` and hash the canonical ordered JSON array. Each fill object includes the complete frozen OwnedFillRecord semantics:

```text
broker_id, account_binding, broker_execution_id, action_id,
broker_order_id, order_link_id, symbol, side,
executed_quantity, execution_price, execution_fee, fee_currency,
executed_at_ms, observed_at_ms
```

Encode money canonically, integers exactly and unavailable fee currency as null. Count is the number of selected fills, including a well-defined digest of the empty array. Existing action ownership/FKs and duplicate/conflict rules still apply. Later rereads do not replace the retained first observed_at_ms of an identical durable fill. This snapshot identifies accepted local evidence, not proof that limited broker history contains every historical execution.

A legitimately discovered later fill may predate an accepted valuation. **Old rows/digests/equity/peak/daily PnL remain immutable observations of the evidence accepted then.** Do not recompute old records on open or silently replace their snapshot with today's larger fill set. A historical snapshot differing from subsequently expanded durable evidence is distinct from malformed schema/rows; reads must preserve that history.

Before accepting a replay successor, compare its predecessor's snapshot against the current durable fill set at that predecessor's cutoff. If the set changed, refuse to append a supposedly coherent successor that would hide the discrepancy. Future Stage 11.4 must likewise detect changed evidence at the latest accepted valuation before a new ENTRY and refuse authorization until separately reviewed replay/correction semantics establish a coherent chain. No automatic historical rewrite/correction is introduced in 11.3; these rules do not bypass Stage 10's restrictions on terminal fill mutation.

### Modes and permitted writers

| Mode | Meaning | Stage 11.3b public write capability |
| --- | --- | --- |
| ACTIVATION | First valuation of the initial epoch. | Only through atomic initialize_risk_journal. |
| REPLAY_ONLY | Consecutive historical risk reconstruction; never broker authorization. | Only through append_risk_replay_valuation. |
| LIVE | Valuation belonging to an actual current runtime decision/verdict. | **None**; reserved for Stage 11.4 atomic integration. |

No standalone LIVE valuation writer is permitted. Schema/models/decoding may represent LIVE for the future complete transaction, but cannot expose a way to commit it independently.

## Separate explicit risk initialization

Future `store.initialize_risk_journal(...)` is one bounded atomic local transaction creating a compatible immutable risk configuration, epoch 1 and its initial ACTIVATION valuation. It creates no verdict, action, decision/frontier change or broker mutation. All four risk tables must initially be empty. Select deterministic once-only behavior: an already initialized journal, even an identical request, fails without writes; a conflict always fails. Stage 11.3b must test this explicitly.

Require a healthy confirmed FLAT/LONG checkpoint, no unresolved/unsafe lifecycle, known CONFIRMED quantity, a matching existing authoritative candle/close, compatible configuration, valid exact book and state equal to frozen initialize_risk_state for the supplied boundary. Supplied book.owned_base_quantity must equal the checkpoint's current confirmed bot-owned quantity. UNKNOWN, LAST_KNOWN, pending, HALTED, STOPPING or unsynchronized state fails; initialization cannot repair/reconcile Stage 10 or adopt unrelated wallet holdings.

Initial virtual cash comes from the approved risk_capital_quote accounting anchor adjusted only through the complete retained owned executions selected for activation. The supplied book and its durable evidence snapshot must be consistent; no wallet balance, USD aggregate or fabricated free holding can supply the anchor. Activation is responsible for evidence completeness and temporal consistency; if a current checkpoint includes executions beyond the proposed boundary, do not disguise that as a historical matching book. No broker read or historical risk equity/baseline/peak/trip is invented to fill a gap. Durable activation over retained execution facts is distinct from retrospective risk activation before the chosen epoch start.

## REPLAY_ONLY append

Future `append_risk_replay_valuation(...)` may append only to the same current epoch at exactly the next accepted hour. Require existing matching candle/close, exact evidence count/digest, unchanged predecessor evidence at its cutoff, and a RiskBook/RiskState transition matching frozen advance_risk_state exactly. Preserve peak, midnight behavior, entry count and original trip reason/time/notification; do not consume a trip notification by inventing a verdict.

No gaps, backwards time or conflicting duplicate rows. Select identical replay retry as a safe no-op only when the complete already accepted record matches exactly; it does not advance any frontier or report a new valuation. Any differing financial/state/evidence/mode field conflicts. No epoch/configuration switch, action, verdict, runtime checkpoint/decision/frontier mutation or broker capability. Risk replay never queues historical orders.

## Future verdict/action representation

`risk_verdicts` schema support is included in v2 now so Stage 11.4 does not require schema v3 merely to express this accepted boundary. Retain:

```text
symbol, timeframe, candle_open_ms
epoch_id, valued_at_ms, risk_configuration_digest
proposal_kind, authorized_amount
verdict, reason
action_id, evaluated_at_ms
```

One verdict per durable decision candle, with an exact reference to that decision, the corresponding LIVE valuation/epoch and its matching configuration digest. evaluated_at_ms is explicit validated UTC evaluation/authorization time, separate from closed-candle valuation time. Optional proposal kind/amount are both absent or both present; ENTRY amount is quote, EXIT amount is exact owned base. No broker payload or alternative monetary unit enters these fields.

| Verdict / proposal | Amount | action_id |
| --- | --- | --- |
| ALLOW ENTRY or EXIT | Required positive exact Decimal | Required; exact unique Stage 10 placement action FK |
| BLOCK ENTRY | Required | NULL |
| TRIP ENTRY | Required | NULL |
| TRIP with no proposal | NULL | NULL |
| ALLOW with no proposal | NULL | NULL |

ALLOW reason is NULL; BLOCK reasons are the frozen nonfatal policy reasons; TRIP reason matches the valuation latch's DAILY_LOSS_LIMIT/MAX_DRAWDOWN. The initial pure policy has no BLOCK/TRIP EXIT: a valid exact EXIT may ALLOW while the valuation remains tripped; invalid evidence raises an error, never becomes a refusal record. No-proposal ALLOW is accounting only. An action reference must match the exact decision/candle, kind, amount, unit and symbol, not merely exist. Cancellation is not a risk ENTRY/EXIT proposal or another ALLOW action type.

**Stage 11.3b has no standalone public verdict writer.** It adds schema, immutable models, decoding/validation and bounded reads; only Stage 11.4 may add the reviewed LIVE write transaction. Future ALLOWed ENTRY must commit decision + risk valuation/verdict/authorization + PREPARED action + frontier atomically before ATTEMPT_STARTED. Refused ENTRY commits decision + verdict/valuation/latch + frontier without action. LIVE valuations cannot commit alone; corresponding verdict/action relationships must be validated before commit.

For future LIVE rows, the accepted state must account coherently for pure evaluation's notification consumption and any ENTRY count increment in the **same** transaction, rather than updating an immutable valuation afterward. Exact Stage 11.4 API/transition validation and integration with frozen decision dispositions remain separately reviewed work. No risk verdict retrofits a migrated historical action.

### ENTRY count is derived authorization history

The durable source is unique risk_verdicts with proposal_kind ENTRY and verdict ALLOW, grouped by UTC day of evaluated_at_ms across epochs. No mutable counter table. RiskState.entries_this_utc_day is the accepted snapshot/cache of that history, validated coherently as LIVE usage is implemented. BLOCK/TRIP/HOLD/EXIT do not consume a slot; rejection, abandonment, partial fill or restart never refund it. Epoch rearm cannot reset the same UTC day's consumed authorizations.

Stage 11.3b writes no verdicts and therefore invents no consumed authorization. Its initial epoch starts with the pure initializer's zero count; replay preserves/reset-at-midnight semantics only. Future LIVE validation must reconcile valuation snapshots, authorization time/day and all retained verdicts, not count fills or mutate a separate counter.

## Reads and full-store validation

Expose bounded immutable reads conceptually named get_risk_configuration, get_current_risk_epoch, get_latest_risk_valuation, list_risk_valuations, get_risk_verdict and list_risk_verdicts. Exact signatures/models are settled in 11.3b. Reads perform no mutation/network, return complete validated records and follow existing 100,000-row style bounds, never truncated/partially repaired success. Use deterministic epoch/time/candle ordering and reject invalid filters.

Future v2 open validates the exact combined schema/indexes/FKs/version, existing Stage 10 integrity/identity and all risk rows/relationships. Fail closed on missing/wrong columns/indexes/FKs; malformed or noncanonical Decimal TEXT; invalid enums/booleans/versions; dangling epoch/configuration references; invalid candle/close/time links; impossible epoch/parent lineage; inconsistent pure-state transitions; conflicting valuation duplicates; invalid verdict/action/config/decision binding; or row/size overflow. Validate all rows rather than trusting a filtered read.

All four risk tables EMPTY is structurally valid after migration/early integration. Partially initialized risk history is invalid: configurations/epochs/required ACTIVATION valuations must form complete relationships, with no orphan partial initialization. Existing legacy actions can remain without invented risk approvals. Risk tables' structural validity does not claim current evidence freshness or broker completeness; changed late evidence is surfaced as described above before replay/new ENTRY, not silently repaired by loading.

## Implementation and regression boundaries

After separate authorization, Stage 11.3b may modify runtime/store.py and focused store tests/docs for exact v2 schema, explicit migration, immutable risk models/read APIs and ACTIVATION/REPLAY persistence. It may not modify planner, cycle, scheduler, reconciliation, state, locking, exchange adapters or runtime_risk.py, or weaken their frozen tests, without separately approved correction. No generic arbitrary-SQL/callback transaction API is introduced.

Migration and initialization are separate operations/transactions. Neither constructs clients, reads broker accounts/orders/executions, places/cancels, reads .env or obtains network evidence. All execution facts used here are already durable RuntimeStore evidence. Stage 11.4 owns risk-aware runtime atomic authorization; 11.6 owns explicit rearm. No implementation begins in 11.3a.

Future 11.3b acceptance tests must construct a **genuine frozen schema-v1 fixture** matching this baseline's accepted table/index layout, version metadata and records. Do not generate legacy fixtures solely from the new v2 schema. Prove explicit valid v1 → exact v2 reopen with all preserved Stage 10 rows/TEXT, including pending/HALT/STOPPING/recovery/frontier cases. Prove ordinary v1 open never migrates; wrong configuration/contract/budget/identity, malformed v1, missing files, already-v2 and wrong lock/open-store cases fail without replacement. Fault injection before/during/at commit must prove rollback or explicit indeterminate-outcome reopening, never accepted partial v2. All risk tables remain empty after migration.

Risk tests must cover exact Decimal/boolean/enum/state round-trip including midnight and trip notification/latch; configuration digest determinism and epoch test vectors; atomic once-only initialization and rollback; confirmed-owned quantity/retained-book consistency; authoritative candle-close mark; replay hourly continuity/identical retry/conflict rejection; fill-evidence sorting/digest stability, inclusion at equality and late-fill discrepancy detection without rewriting old observations; immutable conflicts; row/size bounds; malformed risk schema/FKs/rows failing closed; forbidden standalone LIVE/verdict writes; and zero broker/network/credential capability. Preserve frozen 123 pure risk tests and Stage 10/Stage 5 EMA, next-OPEN and financial regression behavior.

## Stage status and current verification

Stage 11.1 is FROZEN at `e80d318`; Stage 11.2 is FROZEN at `ffb8566`. Stage 11.3 has STARTED and remains INCOMPLETE; 11.3a contract COMPLETE / owner review pending; 11.3b implementation NOT STARTED. Stages 11.4–11.8 and Stage 12 remain NOT STARTED.

Stage 11.3a changes only this decision, PROJECT_STATE.md, README.md and CHANGELOG.md. Its gate is the unchanged full suite (2,633 tests; zero failures/errors/skips), pip check and both unstaged/staged diff checks. No new tests, database migration/initialization, notebook execution, dependency installation or broker activity occurs. Validation is local execution, not a CI claim.

Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. Stage 11.3b must not start automatically.
