# 026 — Bybit Demo clock-skew tolerance correction

- Date: 2026-11-08
- Status: **Accepted / COMPLETE / FROZEN after independent owner review PASS.**
- Scope: One-field V1 Stage 12.2 Demo operational compatibility contract; documentation-only freeze closure.
- Reviewed repository baseline: `347b6d0126ea7dc1c64f65d346bba2ee10eab043` — `Freeze Decision 025 after remote audit`.
- Governing frozen contracts: [017](017_demo_trading_runtime_contract.md), [024](024_demo_activation_runbook_contract.md) and [025](025_bybit_demo_uta_permission_bundle_correction.md). Decisions 001–025 remain frozen and unchanged.

## Independent owner review and freeze closure

The owner independently reviewed the local Decision 026 proposal at the repository baseline above and returned **OWNER REVIEW PASS / ACCEPTED FOR FREEZE**. The reviewed paths were Decision 026, PROJECT_STATE.md, README.md and CHANGELOG.md. This documentation-only closure records that acceptance without materially changing the reviewed technical policy.

Owner review confirmed the durable skew field and exact RuntimeStore identity binding, the need for a narrow migration, separate 60000-ms planner freshness, the absence of an approved runtime configuration-digest derivation, the distinct risk digest behavior and independent Stage 12.2b authorization.

**Accepted target policy: 6000 ms. Production implementation: NOT IMPLEMENTED. Durable migration: NOT RUN. Runtime store migrated to 6000: NO.** The owner-supplied reviewed durable value remains **1000 ms**, at sequence 403 / STARTING / LAST_KNOWN. This closure does not inspect or mutate the real store, establish a new production/trading baseline or authorize any future implementation or operation.

## Authority and current contract

Decision 026 accepts the reviewed deployment's `RuntimeConfiguration.max_clock_skew_ms` target change from **1000 to 6000**. The accepted target policy is frozen, but the current durable/operational bound remains **1000 ms** until the narrow implementation is independently reviewed/frozen and a separately authorized durable migration has completed. An external preflight must not start accepting 6000 before those prerequisites.

This documentation freeze implements and authorizes no production API, migration, RuntimeStore operation, credential access, clock/broker/Telegram request, restart preparation, reconciliation, strategy execution, scheduler or order action. Acceptance/freeze is not permission to perform those operations. Stage 12.2b remains **NOT STARTED**.

The accepted exception applies only to `broker_id=bybit-demo`, `account_binding=demo-main`, `bot_id=bot1`, for Stage 12.2 controlled Demo validation with virtual funds. It grants no Stage 12.4 Live tolerance, Live credential use or Live order placement, and no Demo order permission by itself. Before Live, independently review clock/timing policy; no Demo → Live policy inheritance.

## Sanitized evidence and rationale

The owner supplied these non-secret observations from earlier separately authorized operations. They are historical evidence, not requests performed by this documentation task:

| Observation | RTT_MS | CLOCK_SKEW_MS | Approved absolute bound | Result |
| --- | ---: | ---: | ---: | --- |
| Final Gate G attempt | 123.056 | +4057.5 | 1000 ms | FAIL |
| Standalone clock-only recheck | 149.136 | +4082.964 | 1000 ms | FAIL |

Skew is Bybit server time minus the local request midpoint. The similar positive offset of approximately 4.1 seconds across two bounded checks motivated the reviewed proposal. It does **not** establish a root cause, future worst-case offset or clock stability. The owner reports that normal macOS automatic-time remediation did not resolve the observed offset; this is operator context only, not proof about macOS, Bybit or NTP behavior.

A 5000-ms bound would leave roughly 0.9 seconds of margin over the reported offsets. A fixed 6000-ms bound provides roughly 1.9 seconds of bounded operating margin while remaining well below the separate 60000-ms decision/observation freshness windows. This is the accepted explicitly reviewed V1 Demo tolerance target for this deployment, **not a limit described as safe in general**. It accepts a wider range of timestamp disagreement; it does not prove that the clocks are synchronized.

The value is fixed, not adaptive. No dynamic tolerance calculation, wallet/broker-derived configuration, retry-until-pass clock loop or automatic system-clock correction is permitted. After implementation review/freeze and separately authorized migration, an absolute skew above 6000 ms must still FAIL; equality is accepted.

## Timing controls and runtime consumers

Only the first row changes in the accepted target configuration:

| Runtime field | Current reviewed value | Accepted target value |
| --- | ---: | ---: |
| `max_clock_skew_ms` | 1000 | 6000 |
| `decision_max_age_ms` | 60000 | 60000 — unchanged |
| `observation_max_age_ms` | 60000 | 60000 — unchanged |
| `reconciliation_timeout_ms` | 600000 | 600000 — unchanged |
| `reconciliation_round_limit` | 5 | 5 — unchanged |
| `read_attempt_limit` | 3 | 3 — unchanged |
| `request_timeout_ms` | 10000 | 10000 — unchanged |

`max_clock_skew_ms` is not merely an outer Gate G comparison. Source inspection establishes these existing boundaries:

| Frozen source | Existing behavior affected by the configured skew bound |
| --- | --- |
| `runtime/store.py`: `RuntimeConfiguration`, validation, identity encoding/open/read paths | Requires a positive integer skew value, persists it in the identity row, and requires exact equality with the caller's configuration. |
| `runtime/reconciliation.py`: `_common(...)` | Checks broker/fetched timestamp disagreement and fetched timestamps ahead of the local control clock. Observation age remains separately bounded. |
| `runtime/reconciliation.py`: `reconcile_startup(...)` elapsed-time checks | Compares UTC elapsed time with monotonic elapsed time. Recovery deadlines and budgets remain separate. |
| `runtime/cycle.py`: `_receipt_action(...)` | Checks receipt broker/fetched timestamps and permitted future observation skew; causal availability and observation age remain separate. |
| `runtime/cycle.py`: public-prefix checks | Requires authoritative market-time samples within the local request interval expanded by the configured skew bound. |
| `runtime/planner.py`: `plan_action(...)` | Does not directly consume `max_clock_skew_ms`. It separately enforces causal availability, future-evidence refusal, observation freshness, decision age and historical cutoffs. |

The future correction must therefore bind the runtime's durable configuration and the operator's external clock comparison consistently. **External Gate G accepting 6000 while RuntimeConfiguration remains 1000 is prohibited.** No frozen consumer, formula or timing comparison is rewritten by this documentation freeze.

Increasing clock-skew tolerance MUST NOT raise or bypass `decision_max_age_ms` or `observation_max_age_ms`. A decision older than 60000 ms is still stale even when broker/local timestamps fall within the 6000-ms skew allowance. Candle closure, history continuity, replay eligibility and next-OPEN backtest behavior remain unchanged. The planner's causal/freshness checks and final send-time guards still require submission at or after decision availability, decision age at most 60000 ms, and submission strictly before the action's reconciliation deadline. No new six-second grace period is added to those guards.

## Reviewed durable baseline and open conflict

The owner supplied the following reviewed state after the failed Gate G attempt; this documentation task does not open or revalidate the real database:

```text
checkpoint sequence = 403
state = STARTING
position_evidence = LAST_KNOWN
owned_base_quantity = 0 BTC
pending_action = NONE

last_processed_candle = 2026-11-08 05:00:00 UTC
replay_until = 2026-11-08 05:00:00 UTC
latest risk valuation candle = 2026-11-08 05:00:00 UTC
risk epoch = 1
risk trip = NO
runtime HALT = NO

durable max_clock_skew_ms = 1000
authenticated broker requests during the failed attempt = 0
reconciliation calls during the failed attempt = 0
order mutations during the failed attempt = 0
```

The failed attempt completed restart preparation but failed its clock gate before authenticated broker reads. Its retained STARTING / LAST_KNOWN state must not be promoted to confirmed exposure by a configuration correction.

The existing `identity.max_clock_skew_ms` column is INTEGER. `RuntimeStore.open(..., initialize=False)`, `get_configuration()` and relationship validation bind the stored identity to the supplied RuntimeConfiguration. Supplying 6000 against the existing 1000 identity fails exact validation; it is not a supported update path. Simply changing an outer preflight or constructing a new configuration cannot migrate the store.

An explicit reviewed one-time durable configuration migration is required before Gate G can use 6000. Do not delete/recreate the database, create a fresh bot identity or registry/account namespace, reset checkpoint/history/risk epoch, ignore the mismatch, or recommend raw operator SQL. A later state that differs from the reviewed baseline requires owner review, not rollback to sequence 403.

## Opaque runtime configuration digest

`RuntimeConfiguration.configuration_digest` is an existing caller-supplied opaque 64-lowercase-hex durable identity. `_validate_runtime_configuration(...)` checks its shape; **no approved repository function derives/recomputes it from RuntimeConfiguration contents**.

**configuration_digest remains unchanged by this correction unless a separate future owner-reviewed digest-migration decision explicitly changes that rule.**

Do not invent an encoding/hash algorithm, reuse `_canonical_hash(...)` retroactively, generate a random replacement digest, or infer a runtime digest from risk persistence. Preserving the existing opaque identity avoids silently inventing content derivation and preserves the existing logical action namespace. Existing action/link IDs must not be regenerated, relinked or made reusable.

This differs from `risk_configuration_digest`: frozen risk persistence explicitly canonicalizes and hashes risk configuration contents. Its implementation is not a derivation rule for the runtime digest. The risk configuration and its digest also remain unchanged.

## Future narrow migration boundary — not implemented

The later implementation must expose a narrow production API/boundary for exactly **1000 → 6000** on the named Demo deployment. No API name/signature or operator command is implemented here. It must not be raw operator SQL, a generic field/value editor, hot reload or a mismatch-tolerant replacement for normal store opening.

Require all of the following before a write:

- Runtime stopped; the canonical RuntimeAccountLock is already held and derives the existing database path. No alternative namespace or automatic initialization/fallback.
- Exact supported existing RuntimeStore/schema and exact expected durable identity, bound to the reviewed old RuntimeConfiguration. Validate every old field and existing record/invariant; there must be no configuration mismatch before migration.
- No external broker or Telegram resource active, no order mutation, scheduler or strategy execution. The migration itself performs no broker request, reconciliation, history replay, restart preparation, initialization or rearm.
- Explicitly reviewed migration authorization and preserved pre-migration evidence, including checkpoint sequence/state/evidence, history/cutoffs, action/fill content and complete risk history. The reviewed STARTING / LAST_KNOWN baseline remains uncertain; migration is not reconciliation or activation.

Atomically change only:

```text
identity.max_clock_skew_ms: 1000 → 6000
```

Preserve every other RuntimeConfiguration field, including `configuration_digest`, `strategy_implementation_digest`, strategy parameters, identity labels, history anchor, sizing/time/read settings, `schema_version=2` and `runtime_contract_version=1`. The existing integer column supports this value: **no schema change, user_version change, new table or dependency is proposed**. This is not the separate frozen v1-to-v2 schema migration; that existing API is not a clock-configuration editor.

Preserve all checkpoint fields and its sequence, state/evidence, desired/owned/pending facts, observation/reconciliation timestamps, candles, decisions, bootstrap/replay cutoffs, actions, fills, risk configuration/digest, epoch lineage, valuations, verdicts, entry/loss counters and HALT/trip state. No new risk epoch, latch clearing, automatic confirmation of exposure or checkpoint bump. Decimal storage, checkpoint CAS, action phase graph and single-instance locking remain unchanged.

## Atomicity, validation and uncertain outcomes

The future implementation must use the existing SQLite durability/transaction boundary: short local atomic transactions, `journal_mode=DELETE`, `synchronous=EXTRA`, `foreign_keys=ON`, and required macOS `fullfsync`. No transaction spans a network operation. The entire permitted logical data delta is one identity field.

Normal transaction post-validation calls `_validate_relations()`, which compares the durable identity with the instance's bound configuration. A naive update while retaining the old 1000 binding would fail that check. The future API must explicitly validate the exact old and new bindings at the correct transaction/lifecycle boundaries while preserving normal validation elsewhere. Do not globally relax identity equality or add a migration bypass to ordinary reads/opens. Concrete implementation mechanics require independent review.

| Observed configuration | Required result |
| --- | --- |
| Exact reviewed old identity/configuration, skew 1000 | One atomic field update to the exact reviewed 6000 target; preserve all other data. |
| Exact already-completed 6000 target, every other field/identity consistent | May explicitly recognize completion without another write; this is verification, not automatic retry. |
| Unexpected source value, including 500, 2000, 5000 or 7000; malformed/missing identity; any other mismatch | FAIL for owner review, with no conversion, repair or reset. |

A raised or uncertain persistence commit must stop the operation: close, preserve evidence and require a separately reviewed reopening/inspection. Never blindly retry, assume rollback or advance dependent work. Recognizing an exact already-completed target is the only permitted idempotent case; it must not silently convert arbitrary values.

After a known successful commit, close/reopen with the exact new RuntimeConfiguration and validate full integrity and all preserved evidence. Also verify that the old RuntimeConfiguration no longer opens as an exact match; its rejection is expected, not a reason to restore 1000 or weaken checks. Verification failure grants no repair/reset permission. Keep the canonical lock until store resources close.

Future offline tests must use temporary synthetic stores to prove: exact one-field delta and unchanged checkpoint/history/risk/IDs; correct 1000 and already-completed 6000 handling; rejection of unexpected values/identities, missing store/lock and incompatible schema; rollback versus uncertain-commit handling without retry; successful new-config reopen and old-config rejection; and zero broker/credential/scheduler capability. No such tests or implementation are added/run by this documentation task.

This is not a configuration-management subsystem. Arbitrary field editing, dynamic risk changes, strategy-parameter editing, symbol/timeframe switching, runtime UI configuration, hot reload and a configuration-history framework are excluded. General configuration management remains post-V1 unless separately approved.

## Unchanged trading and risk profile

| Setting | Preserved reviewed value |
| --- | --- |
| Strategy | `ema_trend`, EMA 20 / 50, warmup 50 |
| Market | BTCUSDT, timeframe `60`, hourly interval 3600000 ms |
| Actions | Spot LONG/FLAT MARKET; existing `place_order` / `cancel_order` boundary only |
| BUY quote budget | 10 USDT |
| Risk capital | 100 USDT |
| Maximum entry notional | 10 USDT |
| Maximum position notional | 10 USDT |
| Maximum daily loss fraction | 0.05 |
| Maximum drawdown fraction | 0.10 |
| Maximum entries per UTC day | 3 |

No leverage, borrowing, shorting, wallet adoption or dynamic sizing. Exchange routing, permission requirements under Decision 025, receipts-versus-fills, ownership, action deadlines, send-time guards and risk limits remain unchanged. Stage 5 EMA/financial regressions and historical next-OPEN behavior remain frozen.

## Future Gate G sequence and stage state

The required future sequence is:

```text
Decision 026 ACCEPTED / FROZEN
→ separately authorized narrow migration implementation
→ independent review/freeze of implementation
→ separately authorized one-time 1000→6000 durable migration
→ validate store using exact 6000 RuntimeConfiguration
→ fresh process-entry/reconciliation
→ fresh public clock measurement; require abs(skew) <= 6000 ms
→ fresh history/freshness validation
→ Gate G readiness classification
→ separate explicit Stage 12.2b authorization
```

Acceptance of this document alone grants none of those operations. Follow frozen process-entry/resource ordering during later authorized execution; no authenticated operational client before the canonical lock. Unprocessed history, stale decisions/observations or unresolved owned work still block readiness. An earlier clock/readiness PASS is temporary and must be rechecked at actual runtime start and submission.

| Stage / decision | Status after Decision 026 freeze |
| --- | --- |
| Decision 026 | **ACCEPTED / COMPLETE / FROZEN** |
| Decisions 001–025 | Frozen / unchanged |
| Stage 12.1 and Stage 12.2a | COMPLETE / FROZEN |
| Stage 12.2 | STARTED / INCOMPLETE |
| Stage 12.2b–d, 12.3 and 12.4 | NOT STARTED |
| Stage 12 | INCOMPLETE |
| v1.0.0 | NOT RELEASED |

Documentation-freeze verification is limited to diff/scope/secret checks. No full-suite run or new CI evidence is claimed. No real RuntimeStore, credential file or broker/Telegram service is inspected by this documentation closure. Git publication is separately authorized by the owner for this closure only. Production, tests, schema, dependencies, existing Decisions 001–025, notebooks and data remain unchanged; implementation and real migration are **NOT IMPLEMENTED / NOT RUN**.
