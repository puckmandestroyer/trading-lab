# Project State

## Project goal

Build a Python trading research and demo-trading platform supporting multiple strategies and bot instances.

## Current stage

Stage 12 — Production & Live Readiness and Stage 12.1 — Observability & Operator Visibility are STARTED / INCOMPLETE. Stage 12.1a — Observability Event / Logging Contract is COMPLETE / owner review pending under [Decision 023](decisions/023_observability_event_logging_contract.md). Stage 12.1b — Structured Logs + Health Snapshot is next / NOT STARTED; 12.1c–e and 12.2–12.4 are NOT STARTED. The project remains **pre-v1 / Stage 12 in progress; v1.0.0 NOT RELEASED**. Do not begin 12.1b automatically.

Stage 12.0 — Trading Lab V1 Production & Live Readiness Contract / [Decision 022](decisions/022_trading_lab_v1_production_live_readiness.md) is independently owner-reviewed, COMPLETE / FROZEN at `0b275c91abe53068dc4b0b05ade7be710d13cef6` (`Define Trading Lab v1 readiness contract`). Decision 022 is unchanged.

Stage 11 — Runtime Risk Management, including Stage 11.8 — Final Stage 11 Audit + Documentation, is independently owner-reviewed, COMPLETE / FROZEN at `b79d511b94fa6e5dd07f59d95e7c51f175f3f756` (`Complete Stage 11 final audit`). Its frozen implementation and Decisions 018–021 are unchanged.

Stage 11.7 — End-to-End Risk Integration Regression is independently owner-reviewed, COMPLETE / FROZEN at `8a57b81b7ea464739d295cf737b057fec79be86f`. Stage 11.6 remains COMPLETE / FROZEN at `a16fe071b508394bba3c79953ddc7e6ae018d3e7` under unchanged Accepted [Decision 021](decisions/021_runtime_risk_rearm_operator_controls.md); 11.6a remains FROZEN at `a45389ae8c4c4b399373c8be8ff2ea0b1046deed`.

Stage 11.5 is independently owner-reviewed, COMPLETE / FROZEN at `f1c542b3deb5d1baebd2ea52f70ea0785292e5df`. Stage 11.4 remains COMPLETE / FROZEN at `887e6631095fbc37720b49c56c8025807d1e9104`; Decisions 018–020, including the reachability correction at `73c1df6`, remain unchanged.

Stage 11.3 — Durable Risk Journal + Schema/Migration Contract, including 11.3b, is independently owner-reviewed, COMPLETE / FROZEN at `be0eba0a4a6cb9f2d97165e0eb0da1525cdf951b`. Stage 11.3a is FROZEN at `9807ed8`. RuntimeStore implements schema v2, explicit v1 migration and ACTIVATION/REPLAY_ONLY persistence. Migration was tested only on temporary fixtures; no real user runtime database was migrated or risk-activated.

Stage 11.2 — Pure Risk State + Valuation + Policy Engine is independently owner-reviewed and FROZEN at `ffb85663af831f5b723bb949c764ac85b3736683`. Existing pure semantics and all 123 regressions remain valid; Stage 11.6b adds only the approved pure rearm helper/public-surface expectation. The pure module has no broker capability.

Stage 11.1 — Runtime Risk Management Contract / Architecture is independently owner-reviewed and FROZEN at `e80d318d80c996fd5ba2fd3cac7fbaa59ead43c9`. [Decision 018](decisions/018_runtime_risk_management.md) remains Accepted and unchanged. Each implementation milestone requires explicit owner approval/review.

Stage 10 — Demo Trading Runtime is independently owner-reviewed, COMPLETE / FROZEN at final baseline `87888719c3e2c87bd3b8979dd9c4ecc33db6cb65` (`Complete Stage 10 final audit`). Stage 10.11 is COMPLETE / FROZEN; its Decision 017 audit passed without production/test changes.

Stage 10.1 — Runtime Contract / Architecture is COMPLETE, published and frozen at `b9eb945674fb450515164eb54256d7ac7270d29d`. [Decision 017](decisions/017_demo_trading_runtime_contract.md) remains Accepted and unchanged.

Stage 10.2 — Runtime State Model + Pure State Machine is COMPLETE, published and frozen at `8b41427d669f5c17717a296113aa7b28b9dd23e3`. Its pure model, public API and tests remain unchanged.

Stage 10.3 — Durable Runtime Persistence + Single-Instance Lock is COMPLETE and FROZEN, with published baseline `56584c462b1226f36941ab02726ed7a621a82dac`. Owner-approved corrections are reviewed and FROZEN: recovery guards at `ad3aca759dbb556d736996bf39b0ba035bb0e512`, durable read APIs at `8b3a482f1d7d2586c2f609aa52f32adf283d8a60`, STARTING/UNKNOWN_OUTCOME restart validation at `a22199f9abd1ce2484aa6dbde500ad126cb66b21`. Legacy table semantics, write APIs, phase graph and locking remain preserved; the approved Stage 11.3b schema-v2 extension is documented below.

Stage 10.4 — Closed-Candle Market Data Gate is COMPLETE, published and frozen at `1865435bb0310dd5d8e8ce7208d56650dc51590a`. Public/read-only market observations only; no operational runtime or authenticated trading.

Stage 10.5 — Startup / Broker Reconciliation is COMPLETE, published, owner-reviewed and FROZEN at `757682038f2a5686e5d45e98dda378e91901b392`. One bounded read-only round consumes normalized Demo broker observations and public durable history, then persists safe exposure/pending/uncertain/HALT evidence. No order mutation, strategy/planner/market-data orchestration or scheduler exists.

Stage 10.6 — Runtime Action Planner + Explicit Demo Sizing Policy is COMPLETE and FROZEN at `6865a1e38b91ab3519fe5b84e4864a59db5ff8bd`. Pure planning/authorization only.

Stage 10.7 — Single-Cycle Demo Runtime Orchestration and its historical/freshness boundary correction are COMPLETE, owner-reviewed and FROZEN at `728bf6d74d38f5f686f738c71bbf34048e032619`.

Stage 10.8 — Long-Running Candle Scheduler is COMPLETE, owner-approved and FROZEN at `f3e9fe6bb9770031c121314c67e4177d0299e095`. Serialized UTC-hour control calls the frozen cycle, with bounded safe retries and durable shutdown. No actual Demo activation.

Stage 10.9 — Restart / Crash / Ambiguous-Action Recovery is COMPLETE, owner-reviewed and FROZEN at `fef6b6ee4a8d4fceb9526ed1e3bc1705fda6b7d5`. Process-entry normalization and all previously approved RuntimeStore and Stage 9 corrections remain unchanged.

Stage 10.10 — Runtime Integration Regression is COMPLETE OFFLINE, independently owner-reviewed and FROZEN at `329252658aa703b90f107d862e34dbabd81f0f64`.

Both audit-blocker corrections are independently owner-reviewed and FROZEN: account/order read classification at `4e947b192d9e2b3be8b9b050917ca9e03a250320`, public market-data classification at `c273a8be3213a1cbeb3fc12271d17618f2d28b94`. Stages 10.1–10.11 and all approved RuntimeStore/Stage 9 corrections remain FROZEN. Stage 11 implementation and final audit are documented below; Stage 12.1b must not start automatically. Optional authenticated Demo run: NOT PERFORMED / NOT AUTHORIZED.

Stage 9 — Bybit Demo Exchange Adapter remains COMPLETE/FROZEN, including the owner-reviewed Stage 9.5 pre-submit correction at `77a88fe1b1250cabde6a1a6fa4aa492db056084b`.

Stage 9.1 — Demo Exchange Adapter Contract remains COMPLETE; [Decision 013](decisions/013_bybit_demo_exchange_adapter.md) is Accepted and unchanged.

Stage 9.2 — Pybit Dependency + Secure Demo Configuration / Session remains COMPLETE; its Demo configuration and retry settings are unchanged.

Stage 9.3 — Instrument Metadata + Order Normalization remains COMPLETE; its metadata and Decimal formatting behavior is unchanged.

Stage 9.4 — Read-Only Demo Account / Order State Adapter is COMPLETE under [Decision 014](decisions/014_read_only_account_and_order_state.md). Account/order/fill snapshots are immutable and broker-independent; Demo reads only, no execution capability.

Stage 9.5 — Spot Market Order Lifecycle Adapter remains COMPLETE/FROZEN under [Decision 015](decisions/015_spot_market_order_lifecycle.md), including the additive pre-submit correction at `77a88fe`. Explicit Demo Spot Market actions only; no adapter-owned strategy execution or portfolio mutation.

Stage 9.6 — Adapter Integration + Offline Regression + Optional Manual Demo Smoke remains COMPLETE/FROZEN. [Decision 016](decisions/016_manual_demo_smoke.md) records explicit manual activation and diagnostic safety. No actual authenticated Demo smoke/order was executed.

Stage 9.7 — Final Stage 9 Audit + Docs remains COMPLETE.

Stage 8 — Strategy Robustness is COMPLETE.

Stage 8.8 — Final Stage 8 Audit + Docs is COMPLETE. All milestones 8.1–8.8 are complete under Accepted Decision 012.

Stage 8.7 — Strategy Robustness Notebook remains COMPLETE and unchanged.

Stage 8.6 — Robustness Summary / Diagnostics remains COMPLETE and unchanged.

Stage 8.5 — Walk-Forward Evaluation remains COMPLETE and unchanged.

Stage 8.4 — Parameter Stability Analysis remains COMPLETE and unchanged.

Stage 8.3 — Parameter Sensitivity Engine remains COMPLETE and unchanged.

Stage 8.2 — Time Split / OOS Evaluation Core remains COMPLETE and unchanged.

Stage 8.1 — Robustness Contract is COMPLETE; Decision 012 is Accepted.

Stage 7 — Risk Manager + Position Sizing is COMPLETE.

Stage 7.9 — Final Stage 7 Audit + Docs completed.

Stage 7.8 — Position Sizing Notebook remains complete.

Stage 7.7 — Exact Regression + Analytics Compatibility remains complete.

Stage 7.6 — Generic Backtest Integration remains complete.

Stage 7.5 — MTM Equity / Reserve Cash remains complete.

Stage 7.4 — NET Accounting Integration remains complete.

Stage 7.3 — GROSS Accounting Integration remains complete.

Stage 7.2 — Position Sizing Core remains complete.

Stage 7.1 — Risk & Position Sizing Contract remains Accepted as Decision 011.

Stage 6 — Generic Backtesting Engine remains COMPLETE at `df72973de837ecbd4ee81f4bdaf77efd74730a56`.

Stage 5 — Analytics remains COMPLETE and frozen at `a3fde091be234fd78d216f6338752a810fa117f0` (`Complete Stage 5 analytics report`).

## Observability event / logging contract — Stage 12.1a

[Decision 023](decisions/023_observability_event_logging_contract.md) defines architecture only: non-authoritative UTF-8 JSONL events, an atomic derived health snapshot, stable durable-fact IDs, exact Decimal-string financial serialization and bounded redaction/failure isolation. Conceptual observability contract version 1 is separate from schema v2/runtime v1/risk v1; no Python constant, logging package, hook, test, schema or dependency is implemented now.

RuntimeStore plus broker reconciliation remains trading truth. Events/snapshots/Telegram/Streamlit cannot authorize, establish ownership/fills, account risk, rearm, reconcile or recover trading state. Deleting observability artifacts must not change the next trading decision. Projection/sink failures cannot alter checkpoints/risk or turn an exception into ALLOW/BLOCK/HALT/rearm. Trading commits close before observability I/O; no SQLite transaction spans a file/notification sink. Original exception/control behavior and indeterminate-commit stop rules remain unchanged; fallback diagnostics are bounded/sanitized without recursive logging.

The fixed 24-field event envelope binds version/ID/type/severity/source, occurrence/observation times, run correlation, non-secret account/bot/strategy/instrument identity, checkpoint/runtime facts, risk epoch/trip facts, candle/action/broker-order references and safe summary. Per-type payloads are explicit bounded allowlists, not arbitrary context/SDK/exception dumps. Four severities are INFO/WARNING/ERROR/CRITICAL. Durable identities exclude observation time/PID/random/run ID; process-only events may use the new per-process run_id, which never affects trading identity or output.

The 28 required event types cover process/scheduler/cycle/failure, market/reconciliation, all action phases and owned executions, confirmed position/quantity changes, risk readiness/BLOCK/TRIP/rearm, runtime HALT/UNCERTAIN/rearm and observability degradation. OPEN requires durable reconciled positive ownership, CLOSE a proved positive→exact-zero transition; ACK/proposal/signal is insufficient. A first partial BUY can establish OPEN while the order remains pending; later growth is quantity change, and partial SELL/dust cannot become CLOSE. Optional realized trade PnL requires complete exact owned executions/prices/signed fees; unavailable is null, never wallet/ACK-derived or zero by default.

First risk-trip identity uses original epoch/reason/tripped_at_ms, including replay/ALLOWed-EXIT latch evidence, not repeated candles. Runtime rearm means committed HALTED→SYNCHRONIZING, not healthy/confirmed; risk rearm requires durable child+ACTIVATION at accepted T. Schema v2 retains current checkpoint/action records rather than complete transition history: restart projects only retained provable facts and reports missing history, without fabricating old transitions/timestamps or adding a trading table.

Future local per-account/bot files are outside notebooks/results, UTC-date segmented append-only JSONL plus atomically replaced health.json. 12.1 does not delete logs; retention/compression belongs to 12.3d. Missing/corrupt derived cursors may cause bounded re-projection/duplicate events, never trading recovery. Health includes identity/process activity, checkpoint/exposure/pending/freshness, exact risk/configuration/epoch/trip/count facts and accepted market mark. Fresh/stale/unknown and unavailable/zero remain distinct. Presentation-only OK/ATTENTION/CRITICAL never changes RuntimeState; ORDER_PENDING alone is not unhealthy.

Telegram consumes events outbound-only, without broker reads/commands. It requires the start/stop, confirmed OPEN/CLOSE, trip/HALT/uncertainty, successful explicit rearm and fatal-failure subset, suppressing normal hourly/HOLD spam. Stable identity plus bounded best-effort retry may duplicate notifications after ambiguous delivery; no exactly-once claim or trading consequence. Streamlit consumes only derived health/events for the six Decision 022 views, without opening the live RuntimeStore as another account-lock owner, broker calls, direct SQL mutation or trading buttons.

Stage 12.1a changes exactly Decision 023 and the three current documents; all production, tests, schema, dependencies, previous Decisions, notebooks/data/results and frozen EMA/next-OPEN/golden behavior remain unchanged. Local execution: unchanged full suite **2,943 passed**, failures/errors/skips **0/0/0**; pip check and both diff checks pass; no new tests. No logging/Telegram/Streamlit implementation. Demo/Live credentials and Telegram token **NOT USED**; real Telegram message **NOT SENT**; authenticated Bybit Demo/Live read/order/cancel and real user DB migration/activation/rearm **NOT RUN**.

## Trading Lab v1 readiness contract — Stage 12.0

[Decision 022](decisions/022_trading_lab_v1_production_live_readiness.md) defines Stage 12 as the final top-level stage and release gate for **Trading Lab v1.0.0**. This contract is architecture/documentation only: exactly Decision 022 and the three current documents change; production, tests, schema, dependencies and previous Decisions have zero changes. No observability, Telegram, Streamlit, Demo activation, deployment or Live capability is implemented here.

The v1 target is **local macOS, one runtime instance / Bybit account binding / bot / existing EMA strategy / BTCUSDT symbol, hourly `60`, Spot LONG/FLAT MARKET, SQLite RuntimeStore**. Telegram will provide outbound alerts; Streamlit will provide a local read-only operational/statistical dashboard. Neither surface may place/cancel, rearm runtime/risk, change configuration, force liquidation or start Live trading. Existing Stage 11 risk stays fixed operator-authorized risk_capital_quote plus fixed planner buy_quote_budget, with vetoes and no resizing. Stage 7 position_fraction remains research only.

Trading truth stays in RuntimeStore and broker reconciliation; logs/events/snapshots/dashboard views are derived. OPEN/CLOSED notifications require durable reconciled owned exposure/flatness, never a signal, proposal, ALLOW or ACK alone. Exact fill/fee/PnL details are shown only when durably known/derivable, without wallet-total PnL. Telegram failure cannot change trading truth or invalidate a safe committed transaction; errors remain visible locally and no SQLite transaction spans notification I/O.

Streamlit's required views are Overview, Position / Orders, Risk, Trades, Runtime Health and Event / Error History. They expose owned position/orders/fills, exact risk configuration/equity/baselines/peak/daily PnL/drawdown/ENTRY count/trip/epoch lineage, reconstructed completed LONG cycles and runtime/reconciliation/pending/critical-error health. They contain no trading controls. Exact observability formats and implementation belong to 12.1.

### Stage 12 roadmap

| Phase | Milestone | Scope | Status |
| --- | --- | --- | --- |
| 12.1 — Observability & Operator Visibility (STARTED / INCOMPLETE) | 12.1a | Observability Event / Logging Contract | COMPLETE / owner review pending |
| 12.1 | 12.1b | Structured Logs + Health Snapshot | NOT STARTED |
| 12.1 | 12.1c | Telegram Outbound Alerts | NOT STARTED |
| 12.1 | 12.1d | Streamlit Dashboard | NOT STARTED |
| 12.1 | 12.1e | Observability Offline Regression + Audit | NOT STARTED |
| 12.2 — Long-Running Bybit Demo Validation | 12.2a | Demo Activation / Runbook Contract | NOT STARTED |
| 12.2 | 12.2b | Controlled 24h → 72h Demo Run | NOT STARTED |
| 12.2 | 12.2c | Restart / Network / Failure Validation | NOT STARTED |
| 12.2 | 12.2d | 7-day Demo Soak + Report | NOT STARTED |
| 12.3 — Local V1 Hardening | 12.3a | Local Operator CLI | NOT STARTED |
| 12.3 | 12.3b | Configuration + Secret Hardening | NOT STARTED |
| 12.3 | 12.3c | Local Process Supervision / Startup | NOT STARTED |
| 12.3 | 12.3d | Backup + Log Rotation + Recovery | NOT STARTED |
| 12.3 | 12.3e | Local Deployment Audit | NOT STARTED |
| 12.4 — Controlled Live Validation | 12.4a | Live Exchange / Safety Contract | NOT STARTED |
| 12.4 | 12.4b | Live Read-Only Validation | NOT STARTED |
| 12.4 | 12.4c | Exact Live Dry-Run / Preflight | NOT STARTED |
| 12.4 | 12.4d | First Explicit Tiny Live Order | NOT STARTED |
| 12.4 | 12.4e | Tiny-Capital Live Runtime Validation | NOT STARTED |
| 12.4 | 12.4f | Final Stage 12 / V1 Audit + Release | NOT STARTED |

12.1 uses local/synthetic data and is expected to need no authenticated Bybit account or API credentials. 12.2 is the first phase requiring real Demo credentials for separately authorized execution: short authenticated smoke → reviewed 24h → reviewed 72h → reviewed 7-day soak. Record sleep/downtime, outages, scheduler/freshness/read/reconciliation/order/partial-fill/restart/HALT/TRIP behavior, visibility and database/log/process health honestly. Duplicate automatic sends, blind resends, unauthorized actions, automatic forced liquidation and automatic rearm must remain zero.

12.3 defines local macOS CLI/runbooks, secret hardening, supervision, database location/permissions, backup/restore testing, log rotation, disk-space and single-instance startup. Safe existing controls remain explicit local controls; graceful stop does not SELL, cancel all, clear trip or rearm. No generic SQL/config mutation or force-liquidate CLI is included. SQLite continues; cloud, Docker and PostgreSQL are not v1 requirements.

12.4 requires a separately reviewed Live safety/exchange boundary and separate Live credentials, minimum permissions/no withdrawals, with 12.3 secret handling satisfied before mutation. Ordering is public/read-only → authenticated account/order read-only → reconciliation validation → exact dry-run/preflight → explicit owner authorization → one tiny real order → reconcile/verify → tiny-capital autonomous validation. Every mutation milestone requires separate explicit authorization. Small risk_capital_quote/buy_quote_budget must be separately reviewed against exchange minimums/frozen invariants; no amount or wallet-derived sizing is invented. Emergency manual exchange intervention remains explicit/out of band unless a separate in-app contract is approved.

Only after 12.1–12.3 and 12.4a–e are COMPLETE / FROZEN, 12.4f audit PASS and no unresolved safety blocker may v1.0.0 be tagged. The audit covers frozen Stages 1–11, observability, Demo soak, local deployment/runbook/secrets, Live read-only/tiny-mutation evidence, invariants, golden regressions and limitations. No tag is created now.

Dynamic 0.5% risk-per-trade/stop-distance/Kelly/ATR/volatility sizing and compounding, additional runtime strategies/bots, portfolio/global or multi-symbol risk, shorts/leverage/margin/derivatives/FX, PostgreSQL/cloud/Kubernetes, automatic liquidation/risk stops/TP/trailing, Telegram trading commands, Streamlit trading controls and a full operator web UI are POST-v1/excluded. Future bots may reuse risk-engine code but need independent RiskState, RiskBook, epochs, PnL, drawdown and daily ENTRY counts; profits/losses cannot silently offset inside one shared strategy-level RiskState. A global layer is later work.

Stage 12.0 verification: unchanged full local suite **2,943 passed**, failures/errors/skips **0/0/0**; `pip check` and both diff checks pass. No new code/tests or real operations. Demo/Live credentials **NOT USED**; authenticated Bybit Demo/Live read/order/cancel and real user DB migration/activation/rearm **NOT RUN**; real Telegram bot message **NOT SENT**. This is local regression evidence, not production or Live readiness.

## Runtime risk contract — Stage 11.1

Milestone records below retain their original scope, completion-time status and test totals. The Current stage and Stage 12.1a contract sections state current status; Stage 12.0 is FROZEN at `0b275c9` and Stage 11 at `b79d511`.

Decision 018 defines the future flow: closed market data → strategy intent → Stage 10 planner proposal → runtime risk gate → durable risk authorization → PREPARED → ATTEMPT_STARTED → Stage 9.5 Demo mutation. Strategy intent, proposed action and permission to take risk are separate facts. Stage 7 `position_fraction` remains historical research allocation, not runtime sizing.

Risk uses a fixed operator-authorized quote-capital envelope, an exact bot-owned execution/cash book and confirmed owned inventory marked at accepted authoritative hourly candle closes. Wallet totals and unrelated assets never enlarge risk capital/equity. Inclusive UTC daily MTM loss and epoch high-water-mark drawdown can latch TRIPPED; this is separate from Stage 10 HALTED. TRIPPED blocks ENTRY but can ALLOW a valid exact owned-base strategy EXIT under all frozen safety checks; no automatic liquidation, stop loss or risk-generated signal.

Future hard entry/position caps and UTC ENTRY-authorization counts never resize orders. Full unresolved ENTRY reservations and consumed slots survive partial/ambiguous outcomes and restart. Risk history/epochs/peaks/day baselines/trips survive restart; explicit rearm starts a new measurement epoch from current equity without crediting new cash or erasing history. Hourly marks provide no intrabar protection.

ALLOW authorization, valuation/verdict, candle decision, PREPARED and frontier must commit atomically; refused ENTRY records verdict/decision/frontier without PREPARED. Future 11.4 must review the frozen planner/cycle integration, including durable refused-intent provenance so a policy-blocked ENTRY does not cause a false HALT on later HOLD. Stage 11.3 requires explicit schema review; any needed v2 migration must be separately owner-reviewed, lock-held and offline, never automatic reset/migration or an ambiguous cross-store commit.

At Stage 11.1 completion, only Decision 018 and current documentation changed. Its unchanged local full suite passed **2,510 tests**, zero failures/errors/skips; `pip check` and both diff checks passed. It is now owner-reviewed/FROZEN at `e80d318`. No authenticated Bybit Demo activity occurred.

### Pure risk state, valuation and policy — Stage 11.2

Added `src/trading_lab/risk/runtime_risk.py`, imported explicitly from that submodule; `risk/__init__.py` and Stage 7 sizing remain unchanged. Public error: `RuntimeRiskError`. Exact enums: `RiskVerdict` (ALLOW/BLOCK/TRIP), `RiskReason` (ENTRY_NOTIONAL_LIMIT, POSITION_NOTIONAL_LIMIT, ENTRY_COUNT_LIMIT, RISK_LATCH_ACTIVE, DAILY_LOSS_LIMIT, MAX_DRAWDOWN), `RiskActionKind` (ENTRY/EXIT), `RiskExecutionSide` (BUY/SELL). Frozen/slotted records: `RuntimeRiskConfiguration`, `RiskExecution`, `RiskBook`, `RiskState`, `RiskActionProposal`, `RiskEvaluation`. Time constants: `HOUR_MS`, `DAY_MS`.

Public pure functions, all with validated inputs and new immutable outputs:

```python
initial_risk_book(config: RuntimeRiskConfiguration) -> RiskBook
apply_owned_execution(config: RuntimeRiskConfiguration, book: RiskBook, execution: RiskExecution) -> RiskBook
calculate_risk_equity(book: RiskBook, mark_price: Decimal) -> Decimal
calculate_projected_exposure(owned_base_quantity: Decimal, mark_price: Decimal, authorized_entry_quote: Decimal, pending_entry_reservation_quote: Decimal = Decimal("0")) -> Decimal
initialize_risk_state(config: RuntimeRiskConfiguration, book: RiskBook, mark_price: Decimal, valued_at_ms: int) -> RiskState
advance_risk_state(config: RuntimeRiskConfiguration, previous: RiskState, book: RiskBook, mark_price: Decimal, valued_at_ms: int) -> RiskState
evaluate_risk(config: RuntimeRiskConfiguration, state: RiskState, book: RiskBook, mark_price: Decimal, proposal: RiskActionProposal | None = None) -> RiskEvaluation
```

Configuration requires exact finite Decimal values, ordered positive quote budgets/caps, fractions in (0, 1], a positive Python-int daily ENTRY limit and different explicit uppercase currencies. No deployment numeric defaults or float coercion. Exact local arithmetic is independent of caller Decimal precision, rounding, exponent limits and traps, with the existing 4,096-character plain-decimal numeric bound. Signed quote fees/rebates change cash; base fees/rebates change owned inventory once on either side. Negative cash is retained; negative resulting inventory and unsupported nonzero fee units fail. Equity is cash plus owned base times supplied positive exact mark; healthy epoch valuations require positive equity.

Initialization is a first validated accounting/epoch anchor, not adoption, historical reconstruction or operator rearm. Advance requires exactly the next UTC hour. At midnight, the same boundary equity closes the outgoing day and checks its old loss baseline before the new day's baseline/PnL/count reset. Peak and trip survive rollover/recovery. Daily loss uses fixed capital; daily loss wins a simultaneous first drawdown breach. Drawdown diagnostics are exact `RiskState.drawdown_numerator` / `drawdown_denominator`; policy uses exact cross-multiplication, never a rounded ratio.

`RiskState.trip_pending_report` retains a newly latched notification until evaluation. Thread the returned state: evaluation consumes the notification, never the original trip reason/time. New breach gives TRIP for ENTRY/no proposal, or ALLOW for exact owned-base EXIT while retaining the latch. Existing latch BLOCKS ENTRY; exact EXIT stays permitted. No-proposal ALLOW means accounting only, never broker authorization. Invalid/mismatched book/mark/records raise sanitized `RuntimeRiskError`, not BLOCK. Pyramiding and inexact EXIT amounts fail. ENTRY ALLOW alone increments the pure daily count; no other verdict/action refunds or increments it. Ordered caps and FLAT-only ENTRY make the entry limit stricter than the position limit in current valid proposals; the pure exposure helper also covers full pending reservations without journal integration.

Caller responsibilities remain explicit: supply the authoritative closed mark and complete already-owned, deduplicated, temporally appropriate execution/book facts. `apply_owned_execution` is **not idempotent**; repeated input applies economics again. Threading immutable states does not provide durable IDs, replay history, crash consistency, broker authorization or rearm. Those remain future 11.3/11.4/11.6 work. No imports of runtime/exchange/strategy/backtest/Stage 7 sizing, I/O, clock, environment, database, action creation, resize, liquidation or broker capability.

At Stage 11.2 completion, local validation passed **123 new focused tests**, full suite **2,633 (2,510 + 123)**, zero failures/errors/skips; required frozen integration/cycle/store/planner/state/9.4/EMA/historical suites, `pip check` and both diff checks passed. No pre-existing test or frozen production file changed; schema, Decisions, dependencies, notebooks and data/results were preserved. Authenticated Bybit Demo read/order/cancellation: **NOT RUN**. Stage 11.2 is now independently owner-reviewed/FROZEN at `ffb8566`; the next persistence contract is recorded below.

### Durable risk journal / schema-v2 migration contract — Stage 11.3a

At Stage 11.3a completion, Decision 019 accepted architecture/documentation only. The separately authorized Stage 11.3b implementation below uses schema version **2**, keeping runtime contract version **1**, in the same canonical RuntimeStore database/account lock. Four future immutable tables are specified: `risk_configurations` (canonical policy digest/history), `risk_epochs` (deterministic lineage), `risk_valuations` (hourly book/state/candle/evidence snapshots), and `risk_verdicts` (future decision/proposal/verdict/action relationships). At that contract-only milestone, implementation remained **schema v1**, with no migration or risk persistence added. Stage 11.3a is now FROZEN at `9807ed8`.

Migration must be a separate explicit, lock-held, offline operation on exact valid v1 with no open store. Ordinary v2 open must reject v1 with a migration-required diagnostic, never reset, repair or auto-migrate. Compare every runtime configuration field exactly except the migration-owned schema version and caller-reviewed configuration digest. One bounded transaction creates v2 tables/indexes and updates those identity fields plus SQLite version metadata, preserving all existing rows/TEXT, action IDs/links, checkpoint state/sequence, pending/HALT/STOPPING, budgets/deadlines and frontiers. Reopen/validate exact v2; failure rolls back or reports an indeterminate result requiring reopen. No broker I/O.

Structural migration leaves all four risk tables **EMPTY**, without inventing configuration, capital, epoch, equity, baseline, peak, trip or approval. Separate initialization atomically creates compatible risk configuration + epoch 1 + ACTIVATION valuation, only with confirmed safe owned quantity, retained execution-consistent book and an existing candle's exact close. It does not reconcile or repair runtime state. Public 11.3b append may persist consecutive REPLAY_ONLY valuations using frozen pure transitions; standalone LIVE valuation and verdict writers are forbidden. Stage 11.4 alone will own decision + risk approval/verdict/valuation + PREPARED action + frontier atomicity.

Each valuation binds the durable hourly candle/close and exact RiskBook/RiskState, including midnight counts and trip notification. Fill evidence count/digest identifies the complete accepted durable set with executed_at_ms <= valued_at_ms, sorted by execution time/ID and canonically hashed with ownership/financial fields. Old snapshots are immutable after legitimately late evidence; a replay successor must not hide a changed predecessor evidence set. Future LIVE ENTRY must refuse incoherent evidence pending reviewed correction semantics. Consumed ENTRY counts will derive from ALLOW ENTRY verdicts by authorization UTC day, not a mutable counter table.

Future 11.3b tests must build genuine frozen-v1 fixtures independently of new v2 schema, prove exact row/TEXT preservation and empty-risk migration, fault-safe rollback/reopen, explicit migration refusal cases, and risk digest/state/candle/evidence/initialization/replay/bounds validation. No implementation or test change is made in 11.3a. Unchanged full suite: **2,633 tests**, zero failures/errors/skips, local execution; `pip check` and both diff checks pass. Production/tests/schema/dependencies/previous Decisions/notebooks/data/results remain unchanged. Authenticated Bybit Demo read/order/cancellation: **NOT RUN**.

### Durable risk journal / schema-v2 migration implementation — Stage 11.3b

Stage 11.3b is independently owner-reviewed, COMPLETE / FROZEN at `be0eba0a4a6cb9f2d97165e0eb0da1525cdf951b`, completing Stage 11.3. Stage 11.3a is FROZEN at `9807ed8d9177149ebd578b93d00b149c7f7d2aed`. Decisions 018/019 remain unchanged. Stage 11 remains INCOMPLETE; the separately approved Stage 11.4 integration is documented below. At Stage 11.3b completion, LIVE authorization integration was NOT STARTED.

Production changes are limited to `runtime/store.py`. RuntimeStore now implements **schema v2: ten tables, including the four risk tables**, with runtime contract version **1**. Immutable/slotted records: `RiskConfigurationRecord`, `RiskEpochRecord`, `RiskValuationRecord`, `RiskVerdictRecord`; `RiskValuationMode` is ACTIVATION / REPLAY_ONLY / LIVE. Risk policy enums, book/state validation and exact accounting/valuation formulas are reused from the byte-identical Stage 11.2 pure engine.

New public write APIs:

```python
RuntimeStore.migrate_v1_to_v2(lock: RuntimeAccountLock, configuration: RuntimeConfiguration) -> None
store.initialize_risk_journal(risk_configuration: RuntimeRiskConfiguration, *, candle_open_ms: int) -> RiskValuationRecord
store.append_risk_replay_valuation(*, candle_open_ms: int) -> bool
```

Ordinary open of exact valid v1 raises the fixed `RuntimeStoreMigrationRequiredError`, a `RuntimeStoreIntegrityError` subtype, without changing database bytes. Explicit migration requires the canonical held lock, a safe existing file, no open store on that database, literal exact v1 schema/data validation and compatible reviewed v2 configuration. Only identity schema_version/configuration_digest and SQLite version/schema metadata change. One IMMEDIATE transaction creates the risk tables, validates v2 and commits; exact reopen validation is required before success. Pre-commit failures roll back; uncertain commit/rollback closes and requires reopen without retry. Post-commit validation failure does not claim the source stayed v1. All legacy rows, raw Decimal TEXT, consumed IDs/links, pending/HALT/STOPPING, checkpoint sequence/frontiers and recovery bounds remain exact. Migration leaves all four risk tables EMPTY.

**Migration was tested only on temporary fixtures. No real user runtime database migration was performed.** No risk configuration or capital is invented during migration. Separate once-only activation requires healthy CONFIRMED FLAT/LONG, no pending work, exact runtime BUY budget/currencies, existing durable candle and retained owned executions consistent with confirmed inventory. Future executions cannot be folded into a historical activation. Pure initialization derives the first book/equity/peak/day baseline; all activation inserts roll back together on failure. Identical repeated initialization is an error.

Configuration digest and epoch ID use deterministic canonical SHA256 JSON with exact Decimal strings and fixed-vector tests. Fill snapshots select all durable owned fills with executed_at_ms <= valued_at_ms, ordered by execution time/ID, and hash all fourteen ownership/financial/observation fields; the empty-array digest is explicitly tested. Mark and valued_at derive only from the durable hourly candle close/boundary. Replay advances exactly one hour through the frozen pure engine, including midnight, peak, latch and pending trip notification. An identical complete REPLAY_ONLY retry returns False; conflicts/gaps fail. A changed predecessor fill count/digest blocks continuation without rewriting old valuations; legitimately late evidence does not by itself make the retained old snapshot corrupt on open.

Bounded, fully validated immutable reads:

```python
store.get_risk_configuration(risk_configuration_digest: str | None = None) -> RiskConfigurationRecord | None
store.get_current_risk_epoch() -> RiskEpochRecord | None
store.get_latest_risk_valuation() -> RiskValuationRecord | None
store.list_risk_valuations(epoch_id: str | None = None) -> tuple[RiskValuationRecord, ...]
store.get_risk_verdict(candle_open_ms: int) -> RiskVerdictRecord | None
store.list_risk_verdicts(epoch_id: str | None = None) -> tuple[RiskVerdictRecord, ...]
```

Empty journals return None/empty tuples. Complete validation covers all ten tables, exact schema/index/FKs, canonical money/digests, epoch lineage, contiguous candle-bound valuations, pure transitions, verdict references and existing row/size bounds; filters never hide corrupt later rows. At Stage 11.3b completion, schema/models/read validation could represent future LIVE/verdict rows, but **no public LIVE writer or runtime authorization integration existed**; Stage 11.4b adds only its atomic boundary below. No standalone LIVE/verdict writer exists; explicit risk rearm/control is now recorded under Stage 11.6b below. Migration, initialization and REPLAY_ONLY append create no verdicts. Existing Stage 10 public writes leave risk rows unchanged; classified LIVE work uses the new atomic API.

Local validation: **120 additive Stage 11.3b tests**, RuntimeStore **350 (230 + 120)**, pure risk **123**, locking **23**, restart **89**, runtime integration **64**, cycle **114**, planner **79**, state **188**, Stage 9.4 **136**, frozen EMA **16**, historical/research/backtest **982**, full suite **2,753 (2,633 + 120)**; zero failures/errors/skips. `pip check` and both diff checks pass. Existing unsupported-version test fixtures now use version 3, the store import guard admits only the new pure-risk dependency, and only the authorized store preservation hashes changed. No old tests were removed or skipped. All other production, pure risk's 123 tests, Decisions 017–019, dependencies, notebooks/data/results and financial/next-OPEN behavior are unchanged. Authenticated Bybit Demo read/order/cancellation: **NOT RUN**.

### Pre-trade risk gate / atomic authorization contract — Stage 11.4a

Accepted [Decision 020](decisions/020_runtime_risk_gate_authorization.md) is architecture/documentation only. Stage 11.3 is independently owner-reviewed, COMPLETE/FROZEN at `be0eba0a4a6cb9f2d97165e0eb0da1525cdf951b`. Stage 11.4a is now owner-reviewed/FROZEN at `6bc9d773`. At that contract-only milestone, no 11.4b implementation, LIVE writes, new cycle outcomes or runtime wiring existed; the separately authorized implementation is recorded below.

The future boundary is closed candle → strategy → frozen planner proposal → risk gate → atomic LIVE valuation/verdict + optional PREPARED → existing preflight/final timing → ATTEMPT_STARTED → Stage 9.5 mutation. Stage 10 operational safety always takes precedence. Explicit risk activation is required before genuinely LIVE decision/frontier consumption; an empty v2 journal is not a risk-off mode. LIVE ENTRY and HOLD return distinct nonretryable RISK_NOT_READY without an action, decision/frontier advancement, automatic initialization or risk-caused runtime HALT. Legacy LONG must reconcile and explicitly initialize risk before a later valid EXIT; there is no bypass.

An active journal catches up every missing already-durable historical hour through REPLAY_ONLY before LIVE, including missed trip latches, with zero orders/cancellations. Separate historical decision/replay commits are recoverable after crash. Latest predecessor evidence must still match its retained fill count/digest before a new LIVE commit; late evidence blocks all new risk/decision/action/frontier facts without rewriting history.

Future one-transaction persistence validates durable configuration/epoch/fills/mark and the pure result independently: candle + decision + post-evaluation LIVE valuation + verdict + optional PREPARED + checkpoint/frontier. ALLOW action and matching PREPARED are inseparable; refused ENTRY commits existing WAIT disposition and exact strategy intent/amount with BLOCK/TRIP verdict, no action or pending event. ENTRY ALLOW consumes a durable daily slot without later refund. No-proposal LIVE evaluation is accounting-only. TRIP latches RiskState rather than RuntimeState.HALTED, creates no cancellation/liquidation, and may ALLOW an exact valid owned-base EXIT under every Stage 10 guard.

The narrow HOLD-after-refusal exception needs a complete same-epoch contiguous LIVE chain rooted at refused LONG_ENTRY/desired=1 with ENTRY BLOCK/TRIP and no action, followed only by HOLD/desired=1 + ALLOW/no-proposal links. Runtime remains confirmed FLAT with no pending work. Missing/historical/action/desired=0/epoch/ownership breaks invalidate the exception and restore frozen planner safety. It never generates a delayed BUY on HOLD, even if policy later permits risk; a new action needs a genuinely new planner ENTRY proposal. Planner stays unchanged.

Stage 11.4b may add a pure risk_gate.py and extend only store.py/cycle.py, subject to separate authorization. Keep planner/scheduler/state/reconciliation/recovery/pure-risk/exchange production frozen; required planner/scheduler/state changes or a pure-engine defect must STOP for review. Future RISK_NOT_READY/BLOCKED/TRIPPED outcomes get no scheduler 1s/2s retry. Preserve the final send-time callback/one-attempt/no-resend semantics and the permissive activated golden 54 decisions / 2 placements / 2 fills / 0 cancellations with exact IDs/Decimal economics.

Stage 11.4a local validation: **2,753 unchanged tests passed**, zero failures/errors/skips; pip check and both diff checks pass. Exactly four Markdown files change; zero production/test/schema/dependency/previous-Decision/notebook/data/result changes, zero new tests. Real user DB migration/risk activation and authenticated Bybit Demo read/order/cancellation: **NOT RUN**. At that contract milestone, Stage 11.4b required separate authorization and was NOT STARTED; the independently authorized implementation is recorded below. Stage 11 remains INCOMPLETE; 11.5–11.8 and Stage 12 remain NOT STARTED.

### Decision 020 reachability clarification — 2026-10-16

Stage 11.4a remains the architecture baseline at `6bc9d773040f4f09bb0f9aa103ffe4357a5bb27d`. A narrow owner-requested documentation-only correction clarifies that ENTRY_NOTIONAL_LIMIT and POSITION_NOTIONAL_LIMIT are defensive policy reasons, unreachable as genuine planner ENTRY outcomes under the current fixed-budget, FLAT-only, no-pyramiding runtime. Matching runtime/risk BUY budgets and ordered caps remain unchanged; no policy reason is removed.

Future end-to-end atomic BLOCK acceptance uses reachable ENTRY_COUNT_LIMIT and RISK_LATCH_ACTIVE. Direct defensive pure-policy notional/exposure coverage remains required; invalid configuration, modified planner amounts or bypassed validation cannot substitute for a genuine runtime BLOCK proof. Only Decision 020, this state document and CHANGELOG change; no production/tests/schema/dependencies or runtime risk integration. Real user DB migration/risk activation and authenticated Demo read/order/cancellation: **NOT RUN**.

Local validation of this documentation correction: **2,753 unchanged tests passed**, zero failures/errors/skips; `pip check`, `git diff --check` and `git diff --staged --check` pass. Zero new tests; README and all frozen production/tests/schema/dependencies remain unchanged.

This correction is independently owner-reviewed/FROZEN at `73c1df6227dcaf409df2f254c63f83e63e85aa45`. Stage 11.4b was NOT STARTED at that milestone; its separately authorized implementation is recorded below. Stage 11 remains INCOMPLETE; 11.5–11.8 and Stage 12 remain NOT STARTED.

### Pre-trade risk gate / crash-consistent authorization implementation — Stage 11.4b

Independently owner-reviewed, COMPLETE / FROZEN at `887e6631095fbc37720b49c56c8025807d1e9104`, completing Stage 11.4 under unchanged Decisions 018–020. Parent: `73c1df6227dcaf409df2f254c63f83e63e85aa45`. Stage 11 remains INCOMPLETE. Production changes are limited to `runtime/store.py`, `runtime/cycle.py` and new pure `runtime/risk_gate.py`. Planner/scheduler/state/reconciliation/recovery/pure-risk/exchange/strategy production and all Decisions remain byte-identical. Schema stays **2**, runtime contract **1**; no dependencies.

One new public mutation:

```python
store.commit_live_risk_decision(candle, decision, checkpoint, *,
    expected_sequence, evaluated_at_ms, proposed_action=None) -> bool
```

Inside one IMMEDIATE transaction, independently replan from the current checkpoint/action history, validate full refusal provenance if needed, require consecutive frontier/valuation, recheck predecessor evidence, reconstruct the temporally eligible owned book and call frozen advance/evaluate. Atomically insert candle/decision/LIVE post-state/verdict/optional PREPARED/checkpoint. Return False only for exact committed replay, without another count/action/send. Caller verdicts are never authority. CAS, insertion, validation, commit or rollback faults leave all/none or require explicit reopen for an indeterminate outcome. No network/callback spans the transaction.

Without explicit activation, eligible LIVE ENTRY/EXIT/HOLD returns RISK_NOT_READY with no consumed candle, LIVE row, verdict, action or initialization. Historical BOOTSTRAP/REPLAY_ONLY remains available without risk activation. Active risk catches up every missing durable historical hour through append_risk_replay_valuation before LIVE; missed trips survive with zero historical sends. Changed predecessor fill evidence blocks LIVE without historical rewriting. Placement ownership must match the closed-boundary book and current confirmed quantity. No-action pending accounting retains its cutoff even when later fills are already observed. Authorization/valuation UTC days must agree; counts derive from retained unique ALLOW ENTRY verdicts.

ENTRY_COUNT_LIMIT and RISK_LATCH_ACTIVE are the genuine end-to-end BLOCK cases. Refused ENTRY retains original signal/desired=1/exact quote proposal in WAIT + verdict/frontier, without an action/pending event or attempt. Runtime stays confirmed FLAT. New TRIP reports RISK_TRIPPED without operational HALT/cancel/liquidation. Valid exact owned-base strategy EXIT may ALLOW with the latch retained. All six policy reasons remain unchanged; notional/exposure branches retain defensive pure coverage without invalid planner/configuration inputs.

The pure gate proves complete bounded same-epoch LIVE provenance from refused LONG_ENTRY through consecutive no-action ALLOW/HOLD links. Missing/historical/action/epoch/configuration/ownership/malformed breaks invalidate the exception. Independent planner safety/timing always wins. HOLD is never a delayed BUY, including after UTC count rollover. ENTRY slots remain consumed after preflight/final timing refusal, abandonment, rejection, partial/ambiguous outcomes and restart; no rearm/epoch 2.

RISK_NOT_READY/BLOCKED/TRIPPED and optional immutable risk_verdict/risk_reason are additive cycle results. Frozen post-ALLOW send code is byte-identical: preflight → before_submit/fresh timing → durable ATTEMPT_STARTED → at most one mutation. Unconfirmed attempt persistence still stops without further reads/writes/abandon/resend. Scheduler production is byte-identical; risk outcomes get no immediate 1s/2s retry.

Local validation: **67 additive focused tests passed**; local full suite **2,820 (2,753 + 67)** passed with zero failures/errors/skips. Component checks: pure risk **123**, RuntimeStore **350**, cycle **114**, scheduler **86**, restart **89**, integration **64**, reconciliation **100**, planner **79**, state **188**, Stage 9.4 **136**, Stage 9.5 **100**, frozen EMA **16**, historical/research/backtest **982**; all passed. `pip check` and both diff checks pass. Existing test methods/assertions remain, with explicit permissive temporary activation, the authorized public capability/import expectations, and only store/cycle source hashes refreshed. The future LIVE read fixture now uses an operational NOOP. Golden **54 / 2 / 2 / 0** preserves IDs/links, authorized/submitted amounts, execution quantities/prices/fees, final owned position and restart behavior. Synthetic golden fills gain explicit 1 ms latency; scheduler timing assertions remain unchanged. The known-pending EXIT fixture places its recovered fill at the closed cutoff; a separate post-cutoff EXIT test proves refusal. Equality-boundary late evidence remains explicitly rejected.

Real user DB migration: **NOT RUN**. Real user risk activation: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. At Stage 11.4b completion, Stage 11.5 and Stage 12 were NOT STARTED; the separately authorized hardening milestone follows.

### Circuit breaker runtime hardening / offline regression — Stage 11.5

Independently owner-reviewed, COMPLETE / FROZEN at `f1c542b3deb5d1baebd2ea52f70ea0785292e5df`, on parent `887e6631095fbc37720b49c56c8025807d1e9104`. Stage 11.5 added only `tests/test_runtime_risk_circuit_breakers.py` and current documentation. Production code, existing tests/source hashes, schema/version, dependencies and Decisions are byte-identical to that baseline. No breaker formula or production behavior was added or changed.

The 30 additive tests reuse Stage 11.4 fake-broker/temporary-journal fixtures and exercise the real cycle, planner, persistence and frozen pure engine:

- Inclusive daily loss: fixed capital 1,000 × 0.0001 = 0.1 USDT; exact equity 999.9 trips. Adjacent hundredth-price marks produce exact 0.0005 USDT equity quanta: 999.9005 allows accounting, 999.8995 trips. A profitable midnight baseline of 1,010 followed by equity 1,009.9 still trips at the fixed 0.1 allowance, independent of current equity/profits/peak/wallet.
- Inclusive drawdown: a durable 1,010 peak trips at equity 1,008.99, an exact 1.01 decline while still above initial capital. Adjacent values remain on the correct sides. Simultaneous first daily/drawdown breach keeps DAILY_LOSS_LIMIT and its original time.
- Midnight checks outgoing loss before resetting daily baseline/PnL/count. Healthy rollover preserves peak/epoch; subsequent drawdown still uses that peak. Existing trips survive midnight, price rebound, restart and startup reconciliation. A genuine exact strategy EXIT can ALLOW while latched; a later genuine ENTRY remains BLOCK/RISK_LATCH_ACTIVE.
- Downtime catches both missed daily/drawdown breaches despite later recovery. Crash after the first REPLAY_ONLY commit resumes the next missing hour with no duplicate/gap or historical order/cancellation.
- OPEN ACK creates no inventory. Partial executions/fees can trip while preserving the original unresolved lifecycle, full authorized amount and consumed ENTRY count. The frozen one-pending-action prohibition prevents a second placement, satisfying current-scope conservative reservation safety without another ledger or cash debit.
- Position appreciation above max_position_notional_quote on HOLD causes no automatic trip, SELL or resizing. ENTRY_NOTIONAL_LIMIT and POSITION_NOTIONAL_LIMIT remain pure/defensive in current scope: genuine ENTRY starts FLAT with the exact matching fixed BUY budget inside ordered caps; no invalid configuration or altered amount fabricates coverage. Existing count/latch BLOCK tests remain unchanged.
- Equivalent small/large unrelated BTC/USDT wallets yield identical risk records, equity and trips. Exact durable 0.1 USDT or 0.001 BTC fees cause loss once, including across rereads/restart. Unsupported nonzero fee currency, corrupt history and nonpositive equity fail before another authorization. Operational integrity HALT takes precedence over otherwise healthy risk; risk TRIP alone is not HALT.

Local execution: **30 new tests**, existing risk gate **67**, pure risk **123**, RuntimeStore **350**, cycle **114**, scheduler **86**, restart **89**, integration/golden **64**, reconciliation **100**, planner **79**, state **188**, Stage 9.4 **136**, Stage 9.5 **100**, frozen EMA **16**, historical/research/backtest **982**; all passed. Full suite **2,850 (2,820 + 30)**, zero failures/errors/skips; `pip check`, `git diff --check` and `git diff --staged --check` pass. Unchanged golden **54 decisions / 2 placements / 2 fills / 0 cancellations**, exact IDs/links, authorized/submitted amounts, execution quantities/prices/fees, final ownership and restart behavior.

Stage 11.5 added no rearm/epoch 2/operator control, forced liquidation, new breaker class, production monitoring or Stage 11.6 implementation. Real user DB migration: **NOT RUN**. Real user risk activation: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. At Stage 11.5 completion, 11.6 was next / NOT STARTED; its separately authorized contract follows. Stage 11 remains INCOMPLETE; Stage 12 NOT STARTED.

### Restart / risk rearm / operator controls contract — Stage 11.6a

Stage 11.6a accepted [Decision 021](decisions/021_runtime_risk_rearm_operator_controls.md) as architecture/documentation only, on baseline `f1c542b3deb5d1baebd2ea52f70ea0785292e5df`. It is now independently owner-reviewed / FROZEN at `a45389ae8c4c4b399373c8be8ff2ea0b1046deed`. No callable control existed at that milestone; separately authorized implementation is recorded below.

Future controls are independent. Runtime HALT rearm applies the frozen OPERATOR_REARMED event, HALTED → SYNCHRONIZING, preserving last-known exposure/pending identity/desired intent and requiring subsequent reconciliation; it records rearmed_at_ms and clears current halted_at_ms without touching risk. Risk rearm requires confirmed safe FLAT/desired=0 or LONG/desired=1, no pending work, fresh durable reconciliation/mark, caught-up history, unchanged fill evidence and a surfaced trip notification. When both latches exist: explicitly rearm runtime → reconcile successfully → only then explicitly rearm risk.

Risk rearm atomically creates only a child epoch plus ACTIVATION at the parent's latest accepted candle boundary T, using the same configuration, exact CLOSE and continuous cash/inventory/evidence. It intentionally resets the child's loss baseline and peak to current equity, but carries the same-day consumed ENTRY count across retained epochs. No capital credit, configuration edit, historical rewrite, frontier advance, new decision/verdict/action or delayed BUY. FLAT/desired=1 is rejected because Decision 020 refusal provenance cannot cross epochs. LONG rearm retains exact ownership and buys nothing.

Future production scope is only a new pure rearm_risk_state helper and narrow RuntimeStore controls/child validation/read selection. State/recovery/reconciliation/planner/gate/cycle/scheduler/exchange remain frozen. Schema **2**, runtime contract **1**, Decimal storage/durability/CAS/phase graph unchanged; no migration. Decision 021 explicitly requires same-T parent/child ordering, carried-count validation and next-LIVE child authority without changing orchestration. Crash results are all-or-nothing or require reopen; stale/repeated controls cannot create another reset/epoch. Parent trips/history stay immutable.

Restart, midnight and price recovery never rearm. Initial 11.6 includes no manual pause/trip, forced liquidation, broker read/order/cancel, HTTP or credential access. STOPPING remains separate and cannot resume in the same process. Decision 021 lists at least 25 required future acceptance cases; Stage 11.7 retains the later broad integration scope. The no-rearm golden must remain 54 / 2 / 2 / 0 with one initial epoch and unchanged IDs/economics.

Stage 11.6a changes exactly four Markdown files; zero production/tests/schema/dependencies/previous-Decision/notebook/data/result changes and zero new tests. Local execution: unchanged full suite **2,850 passed**, zero failures/errors/skips; zero new tests. `pip check`, `git diff --check` and `git diff --staged --check` pass.

Real user DB migration: **NOT RUN**. Real user risk activation/rearm: **NOT RUN**. Runtime HALT operator rearm on a real runtime: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. At Stage 11.6a completion, 11.6b was next / NOT STARTED. Stage 11 remains INCOMPLETE; 11.7–11.8 and Stage 12 remain NOT STARTED.

### Runtime risk rearm / operator controls implementation — Stage 11.6b

COMPLETE / independently owner-reviewed / FROZEN at `a16fe071b508394bba3c79953ddc7e6ae018d3e7` under unchanged Decision 021 (`a45389ae…`). Stage 11.6 overall is FROZEN. Its production changes were limited to `risk/runtime_risk.py` and `runtime/store.py`; all other production, Decisions 017–021, schema/DDL, dependencies, notebooks and data/results remained byte-identical to that baseline.

Exactly three additive public APIs:

```python
rearm_risk_state(config: RuntimeRiskConfiguration, previous: RiskState, book: RiskBook, mark_price: Decimal, valued_at_ms: int) -> RiskState
store.rearm_runtime_halt(*, expected_sequence: int, operator_at_ms: int) -> RuntimeCheckpoint
store.rearm_risk_epoch(*, expected_epoch_id: str, operator_at_ms: int) -> RiskValuationRecord
```

The pure helper requires a reported automatic trip, the identical accepted boundary T and exact reproduced equity. It returns an immutable child with peak/partial-day baseline set to current equity, zero daily PnL, cleared trip notification/latch and **unchanged same-day ENTRY count**. It is distinct from initialization; exact arithmetic is independent of global Decimal context, with no I/O.

Runtime HALT rearm uses frozen OPERATOR_REARMED and one checkpoint CAS: HALTED → SYNCHRONIZING, sequence +1, recorded rearmed_at_ms and cleared halted_at_ms. Exposure remains LAST_KNOWN/UNKNOWN; pending identity, intent, history, observations, coverage, budgets/deadlines and every risk row stay unchanged. Normal reconciliation is still required; this control neither confirms exposure nor clears risk TRIP.

Risk rearm requires confirmed aligned FLAT/0 or LONG/1 with no unresolved work/reason, fresh durable reconciliation (after any runtime rearm), fresh accepted mark and aligned frontiers. Changed predecessor fill evidence, including equality-boundary late fills, rejects; **any post-T durable fill rejects even when net quantity is unchanged**. The store reconstructs the continuous book from original capital plus exact retained owned fills through T and verifies accepted cash/base/equity, confirmed quantity and all-epoch same-day ALLOW ENTRY count. No operator-supplied policy/book/mark/state is accepted.

One IMMEDIATE transaction inserts only sequence N+1 / exact-parent / same-config epoch plus ACTIVATION at the parent's final T, same candle/CLOSE/book/evidence. No checkpoint, configuration, decision, verdict, candle, action or fill changes. Parent history remains immutable and closed. Full validation proves linear lineage and pure rearm semantics; reads order shared T by epoch sequence and choose the current highest sequence. The next genuine LIVE or consecutive REPLAY_ONLY uses the child without replaying old decisions or transferring refused-intent provenance.

Both controls are local-only and independent. Repeated/stale controls fail. Faults roll back completely or close and require reopen/validation after an indeterminate commit/rollback; no blind retry. Restart, midnight and price recovery never rearm. Manual pause/kill, forced liquidation, automatic cancellation, risk configuration editing and operational UI are **NOT IMPLEMENTED**. Schema remains **2**, runtime contract **1**, with unchanged Decimal TEXT, durability, CAS, phase graph and account lock; existing v2 databases remain readable without migration.

Local execution: **82 new focused tests**, all required component regressions and full suite **2,932 (2,850 + 82)** pass, zero failures/errors/skips. Existing tests change only for approved exact public surfaces and corresponding preservation guards; no prior behavior assertions are weakened. Golden remains **54 decisions / 2 placements / 2 fills / 0 cancellations / 1 risk epoch when rearm is unused**, with exact IDs/links, amounts, quantities/prices/fees, ownership and restart behavior. `pip check`, `git diff --check` and `git diff --staged --check` pass. Stage 5 EMA/next-OPEN behavior is unchanged.

Real user DB migration: **NOT RUN**. Real user risk activation/rearm: **NOT RUN**. Runtime HALT operator rearm on a real runtime: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. At Stage 11.6b completion, Stage 11.7 was next / NOT STARTED; its completed offline evidence is recorded below. Stage 11 remains INCOMPLETE and Stage 12 NOT STARTED.

### End-to-end runtime risk integration regression — Stage 11.7

Independently owner-reviewed, COMPLETE / FROZEN at `8a57b81b7ea464739d295cf737b057fec79be86f`. Added only `tests/test_runtime_risk_integration_e2e.py` and current documentation: **zero production, existing-test, schema, dependency or Decision changes** relative to frozen `a16fe071b508394bba3c79953ddc7e6ae018d3e7`. Eleven long offline scenarios reuse existing fakes while exercising real EMA, planner, risk gate, atomic store, cycle, scheduler, Stage 9 adapters, reconciliation and operator controls against temporary SQLite/account locks.

| Scenario | Combined evidence |
| --- | --- |
| Healthy lifecycle | Explicit activation, bootstrap, genuine BUY/HOLD/SELL, confirmed-LONG restart, scheduler STOP/restart; two placements/two fills/zero cancellations. |
| Atomic authorization fault | A verdict-insert failure rolls back authorization without PREPARED/send; restart safely processes the unconsumed LIVE candle once. |
| PREPARED crash / count BLOCK / HOLD | Crash before ATTEMPT_STARTED abandons unsent but retains the consumed ENTRY slot/ALLOW; a later genuine ENTRY blocks, subsequent HOLDs never BUY or HALT, and a broken copied provenance chain restores planner safety. |
| Lost ACK / partial pending / trip | One attempted BUY is discovered by exact broker identity after restart, never resent; partial inventory can trip daily loss while pending, remaining fills apply once, and normal exact EXIT remains permitted before a later latched ENTRY refusal. |
| Both latches / child / later EXIT | Daily trip and operational HALT require separate HALT rearm, reconciliation and explicit risk rearm. The LONG child preserves configuration/book/evidence/count; restart and T+1h use it, genuine EMA EXIT follows, and the next ENTRY respects the carried count until actual midnight. |
| Drawdown | A new peak then exact inclusive MAX_DRAWDOWN breach remains latched through restart and price recovery without liquidation. |
| Midnight | Synthetic 22:00/23:00/00:00/01:00 UTC evaluates outgoing daily loss before baseline/count rollover; peak/trip survive restart. |
| Downtime / interrupted catch-up | Consecutive REPLAY_ONLY accounting retains a missed breach despite later recovery; restart resumes the next missing hour without duplicate/gap or historical send. |
| Late execution | Evidence executed at an already-accepted boundary blocks successor LIVE authorization; old valuation history remains immutable. |
| Post-boundary rearm refusal | An isolated copied journal receives adversarial retained BUY+SELL evidence after T with unchanged net quantity **and cash**; rearm rejects without child/reset/source mutation. This is a persistence-evidence guard, not a claim that ordinary reconciliation adopts extra terminal-order fills. |
| Not-ready / healthy-risk HALT | Scheduler does not consume an uninitialized LIVE frontier or retry immediately; explicit temporary activation permits it later. A genuine permanent read failure still HALTs despite healthy risk. |

Every scenario records cycle/results, applicable scheduler wakes/restarts, durable decisions/valuations/verdicts/actions/attempts/fills/epochs and reopened truth. Audits enforce at most one authorization per LIVE candle and one automatic adapter invocation per action; ALLOW + LIVE valuation + decision + PREPARED precede adapter entry, and durable ATTEMPT_STARTED precedes SDK mutation. Fault rollback, no blind resend, no forced liquidation, no automatic cancellation and no automatic rearm are covered. Explicit controls cause zero broker/market/credential calls; normal reconciliation is separate. One initial capital anchor plus unique owned executions reconstructs exact Decimal cash/base/equity and nonzero base/quote fees across epochs; unrelated wallet BTC is excluded and same-day ENTRY counts are never refunded.

Local execution: **11 new tests; full suite 2,943 (2,932 + 11)**, zero failures/errors/skips. All required component suites pass, including rearm **82**, breakers **30**, risk gate **67**, pure risk **123**, RuntimeStore **350**, cycle **114**, scheduler **86**, restart **89**, reconciliation **100**, planner **79**, state **188**, Stage 9.4 **136**, Stage 9.5 **100**, Stage 10.10 integration **64**, frozen EMA **16** and historical/research/backtest **982**. These groups overlap and are not summed. `pip check`, `git diff --check` and `git diff --staged --check` pass.

The existing golden is byte-identical and remains **54 decisions / 2 placements / 2 fills / 0 cancellations / 1 epoch when rearm is unused**, with exact action IDs/order links, authorized/submitted amounts, fill prices/quantities/fees, ownership and restart behavior preserved. The new healthy scenario adds a final accounting HOLD (55 decisions) without changing that golden. Stage 5 financial/EMA/next-OPEN behavior, notebooks and data remain unchanged.

This evidence verifies offline architecture behavior, not profitability, real exchange reliability, production readiness, live-money safety, long-running operational reliability, monitoring or deployment. Real user DB migration: **NOT RUN**. Real user risk activation/rearm: **NOT RUN**. Runtime HALT operator rearm on a real runtime: **NOT RUN**. Authenticated Bybit Demo read/order/cancellation: **NOT RUN**. At Stage 11.7 completion, Stage 11 was INCOMPLETE pending the separately authorized final audit below. Stage 12 remains NOT STARTED and must not start automatically.

### Final Stage 11 audit — Stage 11.8

**At Stage 11.8 completion: audit PASS; Stage 11.8 and Stage 11 overall COMPLETE / owner review pending.** That audit changed only PROJECT_STATE.md, README.md and CHANGELOG.md. Production, tests, schema, dependencies and Decisions were byte-identical to the independently frozen Stage 11.7 baseline `8a57b81b7ea464739d295cf737b057fec79be86f`. No new Decision or audit artifact; no functionality or Stage 12 work. The owner has since reviewed/frozen Stage 11 at `b79d511b94fa6e5dd07f59d95e7c51f175f3f756`.

Current Stage 11 capabilities are pure exact risk policy; the durable schema-v2 risk journal; explicit offline v1→v2 migration and separate activation; consecutive historical risk replay; atomic LIVE risk authorization; daily-loss/drawdown breakers and daily ENTRY limits; durable trip latches with exact normal strategy EXIT while tripped; crash/restart recovery; explicit Runtime HALT rearm and risk child-epoch rearm; and offline E2E regression. Stage 7 `position_fraction` remains historical/research allocation. Runtime BUY uses its fixed explicit planner budget; risk vetoes without resizing.

```text
authoritative closed candle → Strategy → Planner → Risk Gate
→ atomic valuation/verdict/decision + optional PREPARED + frontier
→ preflight → final before_submit timing → ATTEMPT_STARTED
→ at most one Demo mutation → broker observation → reconciliation
→ durable owned executions → later risk accounting
```

Strategy intent, planner proposal, durable risk permission and broker execution remain separate facts. Initial scope stays **one Demo account/bot/EMA strategy/symbol, hourly timeframe 60, Spot LONG/FLAT, MARKET only**, with no short, leverage, margin, borrowing or portfolio/netting across bots/symbols.

#### Verified freeze ledger

Git parent relationships, actual changed files and production contents were checked, rather than inferred from milestone labels. All rows below are independently owner-reviewed / FROZEN and form the consecutive accepted history after Stage 10's `87888719c3e2c87bd3b8979dd9c4ecc33db6cb65`.

| Milestone | Frozen commit | Verified scope |
| --- | --- | --- |
| 11.1 | `e80d318d80c996fd5ba2fd3cac7fbaa59ead43c9` | Documentation only |
| 11.2 | `ffb85663af831f5b723bb949c764ac85b3736683` | Pure risk module, pure tests, docs |
| 11.3a | `9807ed8d9177149ebd578b93d00b149c7f7d2aed` | Documentation only |
| 11.3b / 11.3 | `be0eba0a4a6cb9f2d97165e0eb0da1525cdf951b` | RuntimeStore persistence only in production; tests/docs |
| 11.4a | `6bc9d773040f4f09bb0f9aa103ffe4357a5bb27d` | Documentation only |
| Decision 020 clarification | `73c1df6227dcaf409df2f254c63f83e63e85aa45` | Documentation only |
| 11.4b / 11.4 | `887e6631095fbc37720b49c56c8025807d1e9104` | store.py, cycle.py, risk_gate.py only in production; tests/docs |
| 11.5 | `f1c542b3deb5d1baebd2ea52f70ea0785292e5df` | Tests/docs only |
| 11.6a | `a45389ae8c4c4b399373c8be8ff2ea0b1046deed` | Documentation only |
| 11.6b / 11.6 | `a16fe071b508394bba3c79953ddc7e6ae018d3e7` | runtime_risk.py and store.py only in production; tests/docs |
| 11.7 | `8a57b81b7ea464739d295cf737b057fec79be86f` | New E2E tests/docs only |

#### Contract and implementation findings

| Boundary | Audit result |
| --- | --- |
| Decisions / public APIs | Decisions 017–021 match their accepted frozen bytes, with 020 compared to its reviewed clarification. Original pure function/record definitions are unchanged; rearm_risk_state is the approved additive helper. No standalone LIVE/verdict writer, generic SQL callback or extra operator capability. |
| Configuration / exact book | Explicit finite Decimal budgets/caps/fractions and positive integer ENTRY limit retain ordered invariants and no numeric deployment defaults. One original capital anchor plus deduplicated durable owned executions determines cash/base/equity; signed base/quote fees apply once. ACK/requested quantity/average price and unrelated wallet/USD totals are never fills or risk capital. Unsupported nonzero fee units fail closed. |
| Mark / schema / migration | Mark is the accepted authoritative candle CLOSE at open + HOUR_MS. Schema is 2, runtime contract 1: identity, candles, actions, decisions, fills, checkpoint and the four risk tables, in one canonical locked DB. Ordinary open does not migrate; explicit atomic offline migration preserves legacy truth and leaves risk tables empty. Activation is separate; uninitialized LIVE returns RISK_NOT_READY without consuming the frontier. |
| Atomic authorization / send | One commit_live_risk_decision transaction binds candle/decision/LIVE valuation/verdict/optional PREPARED/checkpoint. Action IDs agree for ALLOW; refusal/no-proposal has NULL action_id. Preflight and final timing precede durable ATTEMPT_STARTED; one automatic adapter invocation per logical action, no blind resend or network inside SQLite transactions. |
| Breakers / ENTRY count | Inclusive daily loss uses fixed risk capital; drawdown uses the active epoch peak. Outgoing-day loss is evaluated before midnight rollover. Trips survive recovery/restart/midnight. Unique durable ALLOW ENTRY verdicts across epochs determine consumed slots; no abandonment/rejection/partial/unknown refund. |
| Refusal / EXIT / pending | Refused ENTRY consumes WAIT/frontier while preserving signal/desired intent and creates no action. Complete same-epoch LIVE refusal provenance permits accounting HOLD only, never delayed BUY; broken provenance restores planner safety. A genuine exact owned-base EXIT may ALLOW while tripped under all operational guards. Pending/partial work remains one lifecycle, without cancellation or forced SELL. |
| Replay / reopen / recovery | Consecutive REPLAY_ONLY accounting retains missed breaches and resumes the next missing hour after interruption. Late predecessor evidence blocks continuation without rewriting history. Healthy/BLOCK/TRIPPED/child/completed/pending/uncertain forms reopen; malformed evidence fails closed without truncation or repair. Original durability, Decimal TEXT, CAS, phase graph, lock and restart rules remain intact. |
| Explicit independent controls | HALT rearm uses OPERATOR_REARMED to SYNCHRONIZING only, with risk unchanged and reconciliation required. Risk rearm requires safe aligned confirmed exposure, fresh caught-up accepted evidence, reported trip, unchanged predecessor and no post-T fill. Only child epoch + ACTIVATION are inserted at shared T, same config/book/evidence/count; baseline/peak reset to current equity, parent immutable, no capital credit. Next LIVE uses the child. Controls are broker/network/credential-free; restart/midnight/recovery/signal/wake never rearm. |
| E2E / frozen isolation | All 11 Stage 11.7 assertion paths were reviewed, including atomic faults, crashes, lost ACK, BLOCK/HOLD, breakers, replay, late/post-T fills, both latches, child/restart/next LIVE/EXIT, pending/partial, wallet exclusion and scheduler readiness. No Stage 11 changes to strategy/backtest/analytics/research/exchange production, notebooks, data or dependencies. Frozen Stage 5 EMA/next-OPEN results remain unchanged. |

There is no manual risk pause/trip/kill, clear-trip shortcut, force-flat/liquidation, cancel-all, risk-generated stop loss/take profit/trailing stop, configuration editing or operational controls UI. Explicit Python rearm APIs do not constitute an operational launch or monitoring layer.

Local execution: **0 new tests; unchanged full suite 2,943 passed**, failures/errors/skips **0/0/0**. Required component suites all pass: E2E **11**, rearm **82**, breakers **30**, risk gate **67**, pure risk **123**, RuntimeStore **350**, cycle **114**, scheduler **86**, restart **89**, reconciliation **100**, planner **79**, state **188**, Stage 9.4 **136**, Stage 9.5 **100**, Stage 10.10 integration **64**, frozen EMA **16**, historical/research/backtest **982**. These groups overlap and are not summed. `pip check`, `git diff --check` and `git diff --staged --check` pass. CI/status checks: **unavailable / none configured for this evidence**; no tracked GitHub workflows and baseline status/PR-workflow queries returned no results. This is local execution, not CI.

The unchanged no-rearm golden remains **54 decisions / 2 placements / 2 fills / 0 cancellations / 1 risk epoch**, exact ENTRY `fc17adafb331e964da8e79112502274620b772ad52ee42c3cfec05f61a86a704`, EXIT `349b4d70a2a702ce3f311c1c43bf523b830c193ef9f4a9128d793f4f37dbbb90`, and `bot1-` + first-23-hex link derivation. BUY authorized/submitted amounts are **10.123456789 / 10.1234567**; SELL **0.04995 / 0.04995**. Fill quantities **0.05 / 0.04995**, prices **100.123456789 / 111.123456789**, fees **0.00005 BTC / 0.01 USDT**, final FLAT ownership and restart behavior remain exact.

Stage 11 proves offline software behavior within this narrow Demo scope. It does **not** establish profitability, real-exchange reliability, long-running Demo reliability, monitoring/alerting, deployment hardening, production readiness or live-money readiness. Those remain Stage 12 work, not permission to operate.

Real user DB migration: **NOT RUN**. Real user risk activation/rearm: **NOT RUN**. Runtime HALT operator rearm on a real runtime: **NOT RUN**. Authenticated Bybit Demo read: **NOT RUN**. Authenticated Bybit Demo order: **NOT RUN**. Authenticated Bybit Demo cancellation: **NOT RUN**. No credentials/.env access, real user journal operation or notebook execution during this audit.

### Stage 11 roadmap

| Milestone | Scope | Current status |
| --- | --- | --- |
| 11.1 | Runtime Risk Management Contract / Architecture | COMPLETE / owner-reviewed / FROZEN at `e80d318` |
| 11.2 | Pure Risk State + Valuation + Policy Engine | COMPLETE / owner-reviewed / FROZEN at `ffb8566` |
| 11.3 | Durable Risk Journal + Schema/Migration Contract | COMPLETE / owner-reviewed / FROZEN at `be0eba0` |
| 11.4 | Pre-Trade Risk Gate + Crash-Consistent Authorization | COMPLETE / owner-reviewed / FROZEN at `887e663` |
| 11.5 | Daily Loss / Drawdown / Exposure Circuit Breaker Hardening & Offline Regression | COMPLETE / owner-reviewed / FROZEN at `f1c542b` |
| 11.6 | Restart + Risk Trip / Rearm / Operator Controls | COMPLETE / owner-reviewed / FROZEN at `a16fe071` (11.6a at `a45389a`) |
| 11.7 | End-to-End Risk Integration Regression | COMPLETE / owner-reviewed / FROZEN at `8a57b81` |
| 11.8 | Final Stage 11 Audit + Docs | COMPLETE / owner-reviewed / FROZEN at `b79d511` |

Stage 11.3 internal subphases are COMPLETE / FROZEN: **11.3a contract at `9807ed8`** and **11.3b implementation at `be0eba0`**. Stage 11.4 internal subphases: **11.4a FROZEN at `6bc9d773`, corrected Decision 020 FROZEN at `73c1df6`**; **11.4b implementation and Stage 11.4 overall FROZEN at `887e663`**. Stage 11.5 is COMPLETE / FROZEN at `f1c542b`. Stage 11.6a is FROZEN at `a45389a`; 11.6b and Stage 11.6 overall are COMPLETE / FROZEN at `a16fe071`. Stage 11.7 is COMPLETE / FROZEN at `8a57b81`. Stage 11.8 and Stage 11 overall are independently owner-reviewed, COMPLETE / FROZEN at `b79d511`. Stage 12.0 and 12.1a are documentation-only contracts above; 12.1b must not start automatically.

### Canonical 12-stage roadmap

Stages 1–11 retain their accepted scope/history. Stage 12 — Production & Live Readiness is the final top-level stage and v1 release gate under frozen Decision 022 at `0b275c9`. Stage 12.1 — Observability & Operator Visibility is STARTED / INCOMPLETE: 12.1a contract COMPLETE / owner review pending under Decision 023; 12.1b–e NOT STARTED. 12.2 Long-Running Bybit Demo Validation, 12.3 Local V1 Hardening and 12.4 Controlled Live Validation remain NOT STARTED. The exact milestone roadmap is recorded above. Prior top-level Stages 13–15 naming is superseded only for future planning; historical records and previous Decisions are unchanged. No implementation, Demo activation or Live operation is authorized by these contracts.

## Completed

Milestone entries and Accepted ADRs retain the status and test totals recorded at their completion; current status and next focus are stated separately.

- Initial repository-style project structure and documentation.
- Empty reusable Python packages and a starter Jupyter notebook.
- Initial architecture decision and permanent Codex instructions.
- Codex-assisted workspace inspection and scaffolding.
- Git repository setup, initial commit, and successful publication to GitHub.
- Reusable historical OHLCV loader with backward pagination through the Bybit V5 Public Market Kline API.
- UTC/numeric normalization, explicit duplicate handling, full-period validation, protected snapshot saving, and validated CSV loading.
- First Bybit spot BTCUSDT hourly snapshot saved under `data/raw/BTCUSDT_1h.csv`: 8,760 rows spanning 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC.
- Validation found zero missing values, duplicates, missing hourly candles, or invalid OHLC/volume rows; download used nine pages and removed zero duplicates.
- Research notebook executed with inspection examples, quality checks, summary statistics, and price/volume plots.
- Thirteen offline tests passed for pagination, normalization, response failures, incomplete coverage, invalid data, and snapshot preservation.
- Stage 2 notebook analysis: simple/log returns, sample return statistics and distribution, trailing 24-hour/7-day hourly-return volatility, volume, extreme movements, and BTC buy-and-hold close-based drawdown.
- All 20 notebook code cells executed successfully using the existing virtual environment, including five plots and checks of the derived calculations.
- The existing 8,760-row raw snapshot remains unchanged; all seven derived columns exist only in notebook memory. No processed dataset, dependencies, or application modules were added.
- Observed hourly mean return: -0.002462%; standard deviation: 0.469127%; minimum/maximum: -4.7946% / +3.9581%. Maximum observed close-based buy-and-hold drawdown: -53.7338%. These describe this snapshot, not predictions or bot performance.
- Stage 3 notebook `notebooks/02_ema_strategy.ipynb`: EMA20/EMA50 long-only crossover events, LONG_ENTRY/LONG_EXIT/HOLD signals, and post-signal flat/long research state.
- All 12 strategy-notebook code cells executed successfully, including full-period and zoomed charts, three event-inspection tables, and signal/state/timing/causal-prefix/raw-preservation checks.
- Original Stage 3 results before cleanup: 79 bullish and 78 bearish crossovers, ending in research state 1. These initialization and state conventions are superseded by Stage 3.1 below.
- Raw OHLCV and existing files remained unchanged during Stage 3. Derived strategy columns stay in notebook memory; no processed dataset, reusable strategy module, dependencies, or trading execution was added.
- Stage 3.1 completed: 50 initialization-only candles, `warmup_complete` eligibility from candle 51, `desired_position` naming, and prior-state gating of LONG_ENTRY/LONG_EXIT signals.
- Current results: 78 bullish and 78 bearish eligible crossovers; 78 valid entries and 77 valid exits. A bearish crossover while flat remains HOLD. Final `desired_position` is 1 (wants long).
- First valid LONG_ENTRY candle: 2025-10-13 02:00 UTC, signal_time 03:00 UTC. First valid LONG_EXIT candle: 2025-10-14 05:00 UTC, signal_time 06:00 UTC.
- All 12 updated notebook code cells ran successfully. Warm-up, previous-state, alternating-event, HOLD-stability, timing, and causal-prefix checks passed; raw CSV and the earlier analytics notebook stayed unchanged. No processed dataset was created.
- Stage 4.1 execution contract recorded in `decisions/002_backtest_execution_contract.md`: completed-candle signals map to the next candle's OPEN, with separate desired/executed state, initial executed state 0, and no execution for final-candle events without a next candle.
- Stage 4.1 documented acceptance cases A–G without implementing execution. All 13 existing market-data tests passed during that milestone.
- Stage 4.2 added the pure function `apply_next_open_execution(candles: pd.DataFrame) -> pd.DataFrame` in `src/trading_lab/backtest/execution.py`, consuming pre-generated signals without generating strategy decisions.
- Required input columns: `timestamp`, `open`, `signal`. Exact output columns: `timestamp`, `open`, `signal`, `execution_time`, `execution_price`, `executed_position`. Optional input columns are neither required nor copied into the output; input is not modified.
- Execution metadata on signal row N describes its fill at N+1 OPEN. `executed_position` describes state during the row's candle: initial 0, with N's event changing state only on N+1. Valid final-candle events retain their signal with missing execution metadata and no resulting state change; invalid transitions raise `ValueError`, including on the final candle.
- Added 23 synthetic execution tests covering cases A–G, invalid inputs, hourly continuity, input preservation, and edge cases. All 36 tests passed, including the existing 13 market-data tests. Stage 3.1 notebook, raw data, and dependencies remain unchanged. No PnL, trade ledger, or full backtesting engine was added.
- Stage 4.3 added `generate_ema_signals(candles: pd.DataFrame, fast_span: int = 20, slow_span: int = 50, warmup_candles: int = 50) -> pd.DataFrame` in `src/trading_lab/strategies/ema_trend.py`. It requires only `timestamp` and `close`, returns a new DataFrame, and remains independent of execution, files, and exchange APIs.
- Exact default strategy output: `timestamp`, `close`, `ema_20`, `ema_50`, `warmup_complete`, `bullish_cross`, `bearish_cross`, `signal`, `desired_position`, `signal_time`. Custom spans use `ema_{fast_span}` and `ema_{slow_span}`. Optional input columns are omitted; input values and index are preserved.
- Preserved first-close EWM seeding with `adjust=False`, 50 initialization-only candles, eligibility from candle 51, crossover equality rules, prior desired-state gating, and `signal_time = timestamp + 1 hour`. No entry is synthesized when warm-up ends in a bullish regime.
- Local snapshot regression exactly matched the original notebook across all 8,760 rows and ten strategy columns: 78 bullish/78 bearish crossovers, 78 entries/77 exits, first entry candle 2025-10-13 02:00 UTC (signal 03:00), first exit candle 2025-10-14 05:00 UTC (signal 06:00), final desired state 1.
- Added 21 synthetic strategy tests covering warm-up, crossovers, state gating, HOLD stability, event alternation, causality, input preservation, timing, parameters, validation, and edge cases. All 57 tests passed: 21 strategy, 23 execution, and 13 market-data tests.
- Updated `notebooks/02_ema_strategy.ipynb` to import the reusable strategy instead of duplicating its calculations. All 12 code cells executed successfully; notebook outputs match the function, fixed snapshot results are asserted, and both charts and inspection tables are retained. Raw CSV, earlier exploration notebook, execution helper, architecture decisions, and dependencies remain unchanged. No strategy/execution composition, PnL, or trade ledger was added.
- Stage 4.4 added `run_ema_execution_pipeline(candles: pd.DataFrame, fast_span: int = 20, slow_span: int = 50, warmup_candles: int = 50) -> pd.DataFrame` in `src/trading_lab/backtest/pipeline.py`. It orchestrates the existing strategy and execution helpers without duplicating their logic or modifying input.
- Required pipeline inputs: `timestamp`, `open`, `close`. Exact default output: `timestamp`, `open`, `close`, `ema_20`, `ema_50`, `warmup_complete`, `bullish_cross`, `bearish_cross`, `signal`, `desired_position`, `signal_time`, `execution_time`, `execution_price`, `executed_position`. Custom spans retain dynamic EMA names; optional market-context columns are omitted.
- Each component's output must match the input row count, index, timestamp values, and chronological order before columns are combined; mismatches raise `ValueError`. Execution output must preserve strategy signals. Existing validation errors propagate without signal repair or index resetting.
- Preserved 50-candle initialization, separate desired/executed states, source-signal-row fill metadata, and next-candle-OPEN execution. A final event has no fill; appending its next candle may populate only that former final row's execution metadata within the shared prefix, leaving its strategy output and executed state unchanged.
- Added 19 synthetic pipeline integration tests covering component consistency, row alignment and failures, input preservation, entry/exit timing, warm-up, final events, causal-prefix boundaries, and validation propagation. All 76 tests passed: 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC snapshot integration retained 8,760 rows, 50 warm-up candles, 78 bullish/78 bearish crossovers, 78 entries/77 exits, and the known first entry/exit signal timestamps. Both final desired and executed states are 1. First entry: candle 2025-10-13 02:00 UTC, signal and execution time 03:00 UTC, execution price 115,332.3 USDT verified against the receiving candle's OPEN; executed state is 0 on the signal row and 1 on the receiving row. Every strategy and execution output equals its direct component result.
- Raw data, both notebooks, existing strategy/execution modules and tests, architecture decisions, and dependencies remain unchanged. No additional notebook was needed; no PnL, trade ledger, capital, fees, or performance metrics were added.
- Stage 4.5 added the pure function `build_trade_ledger(backtest: pd.DataFrame) -> pd.DataFrame` in `src/trading_lab/backtest/trades.py`, called separately after the unchanged pipeline. Required inputs: `timestamp`, `signal`, `execution_time`, `execution_price`, `executed_position`.
- Exact ledger schema: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, `status`. IDs start at 1. Only recorded LONG_ENTRY/LONG_EXIT fills with both execution fields present open/close trades; prices and times come from source-signal-row execution metadata, not signal candle prices or desired state.
- CLOSED trades have both entry and exit fills. OPEN trades have an executed entry and missing exit time/price. A final unexecuted entry creates no trade; a final unexecuted exit leaves the existing trade OPEN. No exit is fabricated at dataset end.
- Ledger validation rejects partial execution metadata, invalid prices/signals, HOLD fills, non-chronological fills, invalid pairing, and inconsistent executed state. Source state must agree with prior recorded fills; where the receiving row exists, its timestamp/state must agree with the fill. No strategy or execution calculations are repeated.
- Added 25 synthetic ledger tests covering cases A–M, validation, empty/typed output, input preservation, and existing execution-helper integration. All 101 tests passed: 25 ledger, 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC integration verified actual fills individually: 78 executed entries and 77 executed exits produce 77 CLOSED trades and one final OPEN trade. First trade entry: 2025-10-13 03:00 UTC at 115,332.3 USDT; exit: 2025-10-14 06:00 UTC at 112,482.0 USDT. Final trade entered at 2026-09-30 13:00 UTC and remains OPEN with missing exit fields. Raw CSV, pipeline input/behavior, notebooks, existing modules/tests, architecture decisions, and dependencies remain unchanged; no PnL, returns, capital, fees, or valuation was added.
- Stage 4.6 added `calculate_trade_results(trades: pd.DataFrame, initial_capital: float = 10_000.0) -> pd.DataFrame` in `src/trading_lab/backtest/performance.py`, consuming the six-column Stage 4.5 ledger separately from pipeline and trade pairing.
- Exact required inputs: `trade_id`, `entry_time`, `entry_price`, `exit_time`, `exit_price`, `status`. Exact output preserves those six columns and appends `capital_before`, `quantity`, `trade_return`, `gross_pnl`, `capital_after`; input context/index are preserved, optional columns omitted, and financial fields use float64.
- First accounting model: long-only spot economics, one trade at a time, 100% of current capital allocated, no leverage/borrowing, zero fees/commissions/slippage, and no quantity rounding. Default initial capital is 10,000 USDT. Quantity is `capital_before / entry_price`; CLOSED return is `exit_price / entry_price - 1`, gross PnL is `quantity * (exit_price - entry_price)`, and capital after is `capital_before + gross_pnl`, compounded into the next trade.
- A final OPEN trade receives capital before and quantity from its executed entry, with missing return, gross PnL, and capital after. Capital before means realized funds available before entering, not cash remaining after allocation. No market price is used to value an OPEN trade; no unrealized PnL or equity curve exists.
- Validation rejects invalid capital, IDs/status/order, overlapping trades, malformed exit metadata, invalid prices, multiple/non-final OPEN trades, and impossible numerical results. Added 27 synthetic accounting tests; all 128 tests passed: 27 accounting, 25 ledger, 19 pipeline, 21 strategy, 23 execution, and 13 market-data tests.
- BTC integration retained 77 CLOSED trades and one OPEN trade. First trade return: -0.0247138052393; quantity: 0.0867059791576 BTC; gross PnL: -247.138052393 USDT; capital after: 9,752.861947607 USDT. Independent decimal arithmetic verified the first trade, and all CLOSED capital identities/compounding checks passed.
- From 10,000 USDT, realized capital after the final CLOSED trade is 9,641.111388344 USDT. The final OPEN trade has that capital before and quantity 0.1130341406801 BTC; it was not valued. Pipeline, ledger, existing tests/notebooks, raw CSV, architecture decisions, and dependencies remain unchanged; results remain in memory with no persistence.

- Stage 4.7 added `calculate_trade_results_with_costs(trades: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0) -> pd.DataFrame` in `src/trading_lab/backtest/costs.py`, called separately on the Stage 4.5 ledger. The Stage 4.6 helper and all earlier components remain unchanged.
- Output preserves the six ledger columns and appends `capital_before`, `effective_entry_price`, `effective_exit_price`, `quantity`, `entry_notional`, `exit_notional`, `entry_fee`, `exit_fee`, `total_fees`, `gross_pnl`, `price_adjusted_pnl`, `net_pnl`, `net_trade_return`, `net_capital_after`. Input is not modified or sorted; optional columns are omitted, index/timezone semantics preserved, and empty financial columns use float64.
- LONG effective entry/exit prices are recorded prices times `(1 + slippage_rate)` / `(1 - slippage_rate)`. Quantity is `capital_before / (effective_entry_price * (1 + fee_rate))`; entry notional plus entry fee equals capital before within float tolerance. Each side's fee uses its effective quote notional. CLOSED gross PnL uses recorded prices with this quantity, price-adjusted PnL uses effective prices, net PnL subtracts both fees, net return divides by capital before, and `net_capital_after = capital_before + net_pnl` compounds into the next trade.
- OPEN trades have capital before, effective entry price, quantity, entry notional, and entry fee. Exit and round-trip fields, including `total_fees`, remain missing, with no realized net result or mark-to-market valuation. Raw ledger entry/exit prices are unchanged.
- Added 21 transaction-cost tests covering zero-cost equivalence, adverse slippage, both fees, self-financing sizing, profitable/losing trades, net compounding, OPEN handling, separate fee/slippage cases, rate/capital/ledger validation, input preservation, empty schema, and arithmetic identities. All 149 tests passed, including all 128 earlier-stage tests.
- Full 8,760-row BTC integration retained 77 CLOSED and one OPEN trade. Zero-cost results matched Stage 4.6 economically; an independent decimal first-trade calculation, self-financing identities, net compounding, and input preservation passed. Scenario rates are test assumptions: 0.10% fee and 0.05% adverse slippage per side, not current Bybit fees.
- First trade recorded/effective entry: 115,332.3 / 115,389.96615 USDT; recorded/effective exit: 112,482.0 / 112,425.759 USDT; quantity: 0.0865760717619 BTC. Entry/exit/total fees: 9.990009990 / 9.733380579 / 19.723390569 USDT. Gross / price-adjusted / net PnL: -246.767777343 / -256.629410936 / -276.352801505 USDT; net return: -0.0276352801505; net capital after: 9,723.647198495 USDT.
- Final CLOSED-trade gross capital: 9,641.111388344 USDT; net capital: 7,652.530163437 USDT; reduction: 1,988.581224907 USDT, including fees, slippage, and compounded sizing effects. The final OPEN trade has capital before 7,652.530163437 USDT, quantity 0.0895852306473 BTC, and entry fee 7.644885278 USDT; it was not valued. These realized-capital figures are before its entry. No raw data, notebooks, architecture, dependencies, or existing source/test files changed.

- Stage 4.8 added `notebooks/03_backtest_review.ipynb`: local validated BTC OHLCV → `run_ema_execution_pipeline` → `build_trade_ledger` → independent `calculate_trade_results` and `calculate_trade_results_with_costs` calls. No strategy, execution, ledger, sizing, PnL, fee, or slippage logic is duplicated; descriptive summaries remain notebook research.
- All 38 notebook cells (18 code, 20 Markdown) were reviewed; all 18 code cells executed successfully in order in the existing virtual environment. Two Matplotlib plots show realized capital after CLOSED trades, including the initial point, and cumulative fees/modeled slippage on the cost-sized trade path. No candle-level equity curve is created.
- Snapshot checks retained 8,760 hourly candles from 2025-10-01 00:00 UTC through 2026-09-30 23:00 UTC, zero missing OHLCV values/duplicate timestamps, 78 LONG_ENTRY/77 LONG_EXIT signals, final desired/executed states 1/1, and 77 CLOSED/one OPEN trade. Fixed references validate results rather than supply calculation outputs; mismatches stop execution.
- From 10,000 USDT, gross realized capital is 9,641.111388344 USDT (change -358.888611656 USDT, return -3.588886%). With research assumptions of 0.10% fee and 0.05% adverse slippage per side, net realized capital is 7,652.530163437 USDT (change -2,347.469836563 USDT, return -23.474698%). The 1,988.581224907 USDT gap includes costs and their compounded sizing impact, not just summed fees; rates are not current Bybit fees.
- CLOSED-trade entry/exit/total fees sum to 577.318661158 / 576.124634617 / 1,153.443295774 USDT; average total fee is 14.979783062 USDT. Modeled slippage impact uses existing Stage 4.7 `gross_pnl - price_adjusted_pnl`: total 576.721493561 USDT, average 7.489889527 USDT. The final OPEN entry fee is excluded from these round-trip summaries.
- First-trade walkthrough uses recorded/effective prices and existing accounting columns. Final OPEN trade entered at 2026-09-30 13:00 UTC; its net-scenario quantity is 0.0895852306473 BTC and entry fee 7.644885278 USDT. Exit and realized fields remain missing, with no mark-to-market valuation. The final realized-capital comparison is before this entry / after the last CLOSED trade.
- All 149 existing unit tests passed. Notebook reference, zero-cost equivalence, and input/raw preservation checks passed; both plots were visually inspected. Existing reusable modules/tests, notebooks 01/02, raw CSV, dependencies, and architecture decisions remain unchanged. No new production financial logic, optimization, validation experiments, or Stage 5 analytics were introduced. Results describe this sample under stated assumptions, not general strategy quality; no out-of-sample or walk-forward validation exists yet.

- Stage 5.1 recorded the CLOSED-trade metric contract in `decisions/003_closed_trade_performance_metrics.md`. It defines counts/rates, mean/median/winning/losing/best/worst returns, total realized PnL, quote-currency expectancy, and profit factor without implementing analytics functions.
- Canonical GROSS source is Stage 4.6 `trade_return` / `gross_pnl`, with `capital_before` / `capital_after` context. Canonical NET source is Stage 4.7 `net_trade_return` / `net_pnl`, with `capital_before` / `net_capital_after` context. Stage 4.7 `gross_pnl` is not the canonical gross strategy simulation because it uses cost-aware quantity.
- Return-based classification uses fixed dimensionless `BREAKEVEN_TOLERANCE = 1e-12`: WIN above +tolerance, LOSS below -tolerance, BREAKEVEN inside or on the boundaries. OPEN rows are excluded from every CLOSED statistic and never valued. Total PnL/expectancy retain source breakeven residuals; profit factor uses PnL only from return-classified WIN/LOSS subsets.
- Recorded empty/subset cases, NaN/infinity profit-factor behavior, the 16-field future summary, and Stage 5.2 acceptance invariants. All 149 existing tests passed. No production code, new tests, notebooks, raw data, or dependencies were changed during Stage 5.1; implementation was pending at that milestone.

- Stage 5.2 added `src/trading_lab/analytics/trade_metrics.py`, implementing decision 003 through two pure public functions: `summarize_gross_trade_performance(results: pd.DataFrame) -> pd.DataFrame` and `summarize_net_trade_performance(results: pd.DataFrame) -> pd.DataFrame`. A small private helper shares calculations; no classes/framework or accounting recalculation was added.
- Each function returns one row indexed `GROSS` or `NET`, with exactly the 16 metric columns shown below in contract order. Counts are integers; other fields are float64. GROSS requires `status`, `trade_return`, `gross_pnl`, `capital_before`, `capital_after`; NET requires `status`, `net_trade_return`, `net_pnl`, `capital_before`, `net_capital_after`. Wrong Stage 4 accounting output fails clearly; capital columns guard source schema without repeating accounting validation.
- Only CLOSED rows enter metrics. Fixed `BREAKEVEN_TOLERANCE = 1e-12` uses unrounded returns: WIN above +tolerance, LOSS below -tolerance, BREAKEVEN inside/on the boundaries. Source values are preserved. Profit factor uses selected-source PnL with WIN/LOSS return masks; breakeven residual PnL remains in totals/expectancy but not those aggregates. Profit-only gives +infinity, loss-only 0.0, and no eligible PnL NaN.
- Empty/OPEN-only summaries have zero counts and total realized PnL, with NaN rates/statistics/expectancy/profit factor. Validation rejects non-DataFrames, duplicate/missing columns, invalid status, and missing/non-finite/non-real CLOSED financial values, including bools and strings. Inputs are never sorted, repaired, coerced from strings, or modified; optional columns are irrelevant.
- Added 35 synthetic metric tests covering all decision 003 conventions, boundary/residual behavior, degenerate populations, source separation, validation, preservation, and real Stage 4 helper integration without the raw CSV. All 184 tests passed, including all 149 earlier tests. No Stage 5.3 metrics were added.
- Local BTC research check ran the unchanged pipeline, ledger, gross accounting, and cost accounting before both summaries. Both retain 77 CLOSED trades; omitting the final OPEN row produces identical summaries. Independent standard-library arithmetic, count/rate/expectancy identities, total-PnL versus realized-capital changes, and input preservation passed. Stage 4 code/tests, all notebooks, raw CSV, decision 003, and dependencies remained unchanged during Stage 5.2.

- Stage 5.3 integrated `summarize_gross_trade_performance(gross_results)` and `summarize_net_trade_performance(net_results)` into the existing `notebooks/03_backtest_review.ipynb`, after the gross/net realized-capital comparison and plot, before transaction-cost analysis. Existing accounting outputs are reused; the pipeline still runs once.
- Added one readable Metric/Gross/Net table containing all 16 Stage 5.2 metrics. Counts display as integers, rates/returns as percentages, PnL/expectancy as USDT, and profit factor as a ratio; formatting leaves source values unchanged. Beginner explanations connect classification, win rate, average wins/losses, historical expectancy, profit factor, and arithmetic return versus compounding to this BTC sample.
- At Stage 5.3, notebook 03 had 44 cells: 21 code and 23 Markdown. All code cells executed top to bottom with sequential counts 1–21 and no error outputs. Both existing plots, transaction-cost analysis, first-trade walkthrough, and final OPEN inspection remained; no new plot or metric formula was added.
- All 16 BTC metric references passed for each path. Both have 77 CLOSED trades, 20 WIN, 57 LOSS, zero BREAKEVEN, and 25.974026% win rate. Gross/net total PnL is -358.888611656 / -2,347.469836563 USDT, expectancy -4.660891060 / -30.486621254 USDT per CLOSED trade, and profit factor 0.945165760246 / 0.675088667158. Classification remained unchanged only for this sample; costs can change classification in other samples.
- Removing the final OPEN row leaves every metric identical; its entry fee, quantity, and capital do not enter CLOSED statistics, and it remains unvalued. Accounting inputs and the raw-file hash are preserved. All 184 existing unit tests passed; no new unit tests were needed. Production modules, including `trade_metrics.py`, all tests, decision 003, notebooks 01/02, raw CSV, and dependencies remained unchanged during Stage 5.3; Stage 5.4 had not started at that milestone.

- Stage 5.4 recorded `decisions/004_realized_capital_drawdown.md`, defining REALIZED-CAPITAL drawdown only. Each independent path begins with explicit initial capital and then observes canonical capital after each CLOSED trade in existing accounting order: Stage 4.6 `capital_after` for GROSS, Stage 4.7 `net_capital_after` for NET. There are `N + 1` observations for `N` CLOSED trades; capital is never reconstructed from PnL.
- Running peak is the maximum capital observed so far. Decimal drawdown is `capital / running_peak - 1`, currency amount is `capital - running_peak`, and maximum realized drawdown is the minimum/most negative drawdown. The negative convention gives `-0.25` for a 25% decline. Empty/OPEN-only, flat, or increasing paths have maximum `0.0`; zero post-CLOSED capital gives `-1.0`, while negative capital is invalid.
- OPEN rows add no point; their capital before, entry fees/notionals, and quantities do not adjust realized observations. The final OPEN trade remains unvalued. This path omits intratrade/unrealized losses and can understate full mark-to-market portfolio drawdown; it must not be presented as the strategy's full drawdown.
- Stage 5.4 defined source-specific schema/finite real-capital validation, explicit gross/net API direction, a six-column observation path, and a small maximum summary. All 184 existing tests passed during that documentation-only milestone; implementation and BTC measurement were then pending Stage 5.5 approval.
- Stage 5.5 implemented decision 004 unchanged in `src/trading_lab/analytics/drawdown.py`, with four pure public functions: `calculate_gross_realized_drawdown`, `calculate_net_realized_drawdown`, `summarize_gross_realized_drawdown`, and `summarize_net_realized_drawdown`. Summaries reuse their source-specific path; accounting is never reconstructed.
- Added 32 synthetic tests in `tests/test_realized_drawdown.py` for schemas/dtypes, initial capital, source separation, peaks, empty/OPEN-only paths, zero capital, input validation/preservation/order, earliest tied minima, percentage-versus-currency minima, and integration with actual Stage 4 helpers. All 216 tests passed: 184 existing plus 32 new.
- The offline BTC research check verified 77 CLOSED trades and 78 observations per path, known final realized capitals, independent scalar drawdown calculations, and identical paths/summaries after removing the final OPEN row. Results are recorded below; OPEN remains unvalued.
- During Stage 5.5, Stage 4 production code/tests, `trade_metrics.py` / `test_trade_metrics.py`, all decisions, notebooks 01/02/03, raw BTC CSV, and dependencies remained unchanged. The existing 16-metric summary gained no drawdown column; notebook integration was then pending approval.

- Stage 5.6 integrated all four existing Stage 5.5 drawdown helpers into `notebooks/03_backtest_review.ipynb`, reusing `gross_results`, `net_results`, and `INITIAL_CAPITAL`. The new REALIZED-CAPITAL DRAWDOWN section follows the CLOSED-trade performance summary and precedes transaction-cost analysis. No accounting or drawdown formulas are duplicated; the pipeline still runs once.
- Added a separate Gross/Net table with maximum realized-capital drawdown, its associated USDT amount, trough observation/CLOSED-trade number, trough capital/peak, final realized capital, and population counts. Percentages, USDT formatting, and integer ordinals affect display only; the 16-metric table remains unchanged.
- Added one Matplotlib realized-capital drawdown plot using helper-provided `closed_trade_number` and `drawdown`, including observation 0 and trough markers derived from path/summary outputs. The existing realized-capital and accumulated-cost plots are retained. Notebook 03 now has 52 cells: 25 code, 27 Markdown, and three plots. All 25 code cells executed successfully with sequential counts 1–25 and no saved errors; all three plots were visually inspected.
- Notebook regression assertions passed for 77 CLOSED trades / 78 observations per path, explicit initial capital, maximum drawdowns, trough observations 33 GROSS / 66 NET, trough capital/peaks, and final CLOSED capital. Removing the final OPEN row leaves both paths and summaries identical. Accounting inputs and the raw-file hash were preserved.
- Beginner explanations and conclusions describe GROSS -26.723425% / NET -37.185533% realized-capital drawdown and the limitation versus mark-to-market portfolio drawdown. OPEN remains excluded and unvalued; intratrade/unrealized losses are not observed.
- All 216 existing unit tests passed during Stage 5.6; no new unit tests or dependencies were needed. Production modules including `drawdown.py` and `trade_metrics.py`, all tests, decisions, notebooks 01/02, and raw BTC CSV remained byte-identical. No new financial metric formulas were introduced; Stage 5.7 was then pending approval.

- Stage 5.7 recorded `decisions/005_trade_duration_and_exposure.md`, defining ledger-based CLOSED duration and simple binary observed time-in-market exposure. Canonical times are actual recorded `entry_time` / `exit_time` fills from `build_trade_ledger(...)`, independent of signal/position-state columns and accounting.
- CLOSED positions occupy half-open `[entry_time, exit_time)` intervals with strictly positive elapsed duration. The final OPEN trade has no completed duration and stays out of CLOSED duration statistics, but its observed `[entry_time, observation_end)` interval must contribute to exposure. No exit or valuation is invented.
- Defined the explicit market window `[observation_start, observation_end)`: first candle OPEN through the end of the final candle (last OPEN plus interval). The full denominator includes warm-up and flat time. Exposure is total non-overlapping observed position time divided by that window, a decimal fraction in `[0, 1]`.
- Chose two future APIs, a six-column per-trade table, and a separate 11-field summary indexed `TIME`. There is no GROSS/NET split because current cost models do not change ledger fill timestamps. Timestamp/window/order/overlap validation, empty/OPEN-only/full-exposure cases, and UTC recommendations are documented below and in decision 005.
- All 216 existing tests passed in Stage 5.7. That documentation-only milestone preserved production code, tests, all notebooks, raw BTC CSV, dependencies, and decisions 001–004. Duration/exposure implementation and BTC measurement were then pending Stage 5.8 approval.

- Stage 5.8 implemented decision 005 unchanged in `src/trading_lab/analytics/trade_time.py` with `calculate_trade_time_breakdown(...)` and `summarize_trade_time_metrics(...)`. Both consume the canonical ledger directly and share validated interval calculations; no accounting is called and no GROSS/NET time split is introduced.
- Added 41 synthetic tests in `tests/test_trade_time.py`, covering exact schemas/dtypes, elapsed/fractional durations, empty/OPEN-only/full exposure, boundaries, order/overlap, missing exits, timestamp/timezone validation, DST, optional fields, duplicate indexes, input preservation, and an actual Stage 4 ledger. All 257 tests passed: 216 existing plus 41 new.
- The offline BTC check has 77 CLOSED trades and one final OPEN trade over 8,760 hours. CLOSED time totals 4,078 hours; the final OPEN contributes 11 observed hours, giving 4,089 hours in market and exposure `0.46678082191780823`. Full results appear below.
- During Stage 5.8, Stage 4 modules/tests, existing trade metrics/drawdown modules/tests, decisions 001–005, notebooks 01/02/03, raw BTC CSV, and dependencies remained byte-identical. Notebook integration was then pending Stage 5.9 approval.

- Stage 5.9 integrated `calculate_trade_time_breakdown(...)` and `summarize_trade_time_metrics(...)` from unchanged `analytics/trade_time.py` into notebook 03 after realized-capital drawdown and before cost analysis. Both consume its existing canonical `trades` ledger directly; the explicit window derives from first candle timestamp through last timestamp plus one hour, including all 8,760 observed hours. No GROSS/NET time split or new financial metric is introduced.
- Added the separate 11-field TIME table, integer count/hour/percentage display formatting, a first/last-three-trade preview, and a derived top-five CLOSED-duration table. BTC references remain 77 CLOSED / one OPEN; average/median/minimum/maximum CLOSED durations are 52.96103896103896 / 34 / 1 / 226 hours, totaling 4,078 CLOSED hours. The first CLOSED duration is 27 hours; the longest is trade 68 at 226 hours.
- Final OPEN trade 78 entered at `2026-09-30 13:00 UTC` and contributes 11 observed hours, giving 4,089 hours in market and exposure `0.46678082191780823` (46.678082%). Its completed duration remains NaN and its exit missing; it remains unvalued. Explanations and conclusions distinguish CLOSED duration statistics from observed exposure and holding-time behavior from profitability.
- Notebook assertions check schemas/dtypes, all time references, first/longest CLOSED trades, final OPEN behavior, and deep-copy ledger/output preservation. The existing raw-file hash check is retained. All time values come from public helpers; no duration/exposure formulas or private-helper calls were added.
- Executed all 28 code cells sequentially with no saved errors: 58 total cells, 30 Markdown, and the same three plots. Saved-output checks confirm 12 existing table-producing cells and all three plot images unchanged. All 257 tests pass; no new unit tests or dependencies. Production analytics including `trade_time.py`, `trade_metrics.py`, and `drawdown.py`, all tests/Stage 4 code, decisions 001–005, notebooks 01/02, and raw BTC CSV remain byte-identical. Stage 5.10 was then pending approval.

- Stage 5.10 recorded `decisions/006_candle_level_mark_to_market_equity.md`: initial capital plus a raw CLOSE valuation after every candle, including the final OPEN position. An explicit fixed interval defines the window; N candles produce N + 1 observations.
- Defined initial-before-fill state, EXIT then ENTRY at each OPEN before that candle's CLOSE mark, independent canonical Stage 4.6 GROSS / Stage 4.7 NET paths, paid-cost semantics without hypothetical liquidation costs, exact future schema/APIs, validation, worked example, and boundary cases. Realized-capital reconciliation applies while flat; shared-OPEN replacement entries are marked as new positions.
- All 257 existing tests passed. This documentation-only milestone preserved production code/tests, all notebooks, raw BTC CSV, dependencies, and decisions 001–005. Equity implementation and BTC mark-to-market measurement were then pending Stage 5.11 approval; portfolio drawdown and notebook integration remained deferred.

- Stage 5.11 implemented decision 006 unchanged in `src/trading_lab/analytics/equity.py` with independent GROSS/NET pure functions, initial-before-fill state, EXIT then ENTRY at OPEN, raw CLOSE marking, and N + 1 observations. Canonical quantities/actual exit capital are reused; incurred costs are not charged twice and no hypothetical liquidation costs are added.
- Added 47 synthetic tests in `tests/test_mark_to_market_equity.py`; all 304 tests pass (257 existing + 47 new). Coverage includes exact schema/dtypes, initial losses, worked example, OPEN/final fills, shared-OPEN replacement, no lookahead, source guards, validation/timezones/DST, arithmetic reconciliation, and input preservation.
- The unchanged BTC loader → EMA pipeline → ledger → independent accounting → equity check produced 8,761 rows per path from 8,760 candles, with 77 CLOSED / one final OPEN. Final marked equity is GROSS 9,451.485313939314 USDT / NET 7,490.776562851941 USDT; all 77 CLOSED exit observations reconcile per path. Stage 4, existing analytics/tests, decisions 001–006, all notebooks, raw data, and dependencies remained unchanged. Notebook integration was then pending Stage 5.12 approval; no portfolio drawdown was implemented or calculated.

- Stage 5.12 integrated the two unchanged Stage 5.11 equity helpers into notebook 03 after realized-capital drawdown and before TIME. They consume its existing candles/GROSS/NET accounting with initial capital 10,000 USDT and an explicit one-hour interval; no equity formulas are duplicated.
- Added compact initial/first-entry/final path previews, a last-realized-versus-final-marked table, one GROSS/NET time-axis MTM plot, final OPEN state display, and regression/input/path-preservation checks. Both paths have 8,761 observations from 8,760 candles. At final CLOSE 83,616.2 USDT, trade 78 remains OPEN, position 1, cash zero: GROSS marked equity 9,451.485313939314 / NET 7,490.776562851941 USDT, versus CLOSED realized capital 9,641.111388344 / 7,652.530163437 USDT.
- Executed all 33 code cells in order with no saved errors: 68 cells total, 35 Markdown, four plots. All three original plot images and their generating code remain byte-identical; exactly one MTM plot was added. Representative exit checks passed for trades 1, 39, and 77 in both paths. All 304 tests pass; production code/tests, decisions 001–006, notebooks 01/02, raw data, and dependencies remain unchanged. No portfolio drawdown was calculated; Stage 5.13 contract was then pending approval.

- Stage 5.13 accepted decision 007 for candle-close portfolio drawdown from the existing independent Stage 5.11 equity paths, with exact path/summary schemas, negative drawdown conventions, and deterministic earliest-trough/latest-peak selection.
- Preserved the supplied initial reference, allowed later zero equity, and included final OPEN marked equity through the source path. Realized-capital drawdown stays separate and unchanged; candle-CLOSE observations still miss intrabar/tick losses.
- All 304 existing tests passed. This documentation-only milestone preserved production code/tests, all notebooks, raw data, dependencies, and decisions 001–006. No portfolio drawdown implementation or BTC measurement was performed; Stage 5.14 was then pending approval.

- Stage 5.14 implemented decision 007's four pure functions in `src/trading_lab/analytics/portfolio_drawdown.py`, consuming existing equity paths with shared validation, causal peaks, exact episode selection, and unchanged input/schema semantics.
- Added 55 focused synthetic tests, including actual Stage 5.11 equity integration and final OPEN inclusion. All 359 tests pass (304 existing + 55 new); existing production modules/tests, decisions 001–007, notebooks, raw data, and dependencies remain unchanged.
- The unchanged BTC pipeline produced 8,761 equity/drawdown observations per path. Maximum candle-close portfolio drawdown is GROSS -27.6794381422% / NET -37.9679609807%; both are deeper than this sample's separate realized-capital drawdowns. Notebook integration was then pending Stage 5.15 approval.

- Stage 5.15 integrated the four unchanged Stage 5.14 portfolio-drawdown helpers into notebook 03 immediately after MTM equity and before TIME. They consume the existing GROSS/NET equity paths directly; no equity or drawdown formulas are duplicated.
- Added a compact ten-result GROSS/NET table, realized-versus-portfolio comparison, initial/peak/trough/final path previews, exactly one time-axis drawdown plot with helper-selected trough markers, final OPEN explanation, and focused regression/preservation assertions. Both paths retain 8,761 rows; maximum drawdowns remain GROSS -27.6794381422% / NET -37.9679609807%, with final drawdowns -7.6771641106% / -25.2825731282%.
- Executed every code cell sequentially without saved errors: 80 cells total, 39 code, 41 Markdown, five plots. All four original plot cells and saved images remain byte-identical. All 359 tests pass; production code/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are unchanged. Equity inputs and drawdown outputs are preserved. No benchmark, time-based returns, Sharpe/Sortino, duration/recovery, or later stage was implemented.

- Stage 5.16 accepted decision 008 and added two reusable first-OPEN Buy-and-Hold APIs in `analytics/benchmark.py`. One synthetic OPEN trade delegates independent GROSS/NET sizing to Stage 4 accounting and CLOSE marking to Stage 5.11; no financial formulas, strategy signals, or exits are duplicated.
- Added 38 focused tests (36 synthetic/delegation/validation checks and two local BTC/alignment checks). All 397 tests pass, including the unchanged 359 earlier tests. Both BTC benchmark paths have 8,761 observations; actual values and EMA comparisons are documented below.
- Notebook 03 now calls the benchmark and existing portfolio-drawdown helpers, displays four-path and relative comparisons, explains absolute versus relative losses, and adds exactly one time-aligned equity plot. All 43 code cells executed sequentially without errors: 88 cells total, 45 Markdown, six plots. All five prior plot sources/images are byte-identical. Existing production modules/tests, decisions 001–007, notebooks 01/02, raw data, and dependencies are unchanged; no Sharpe/Sortino or Stage 6 work was added.

- Stage 5.17 accepted decision 009 and added `analytics/risk_adjusted.py` with one canonical simple-return helper and a summary that reuses it. Each of the four aligned equity paths produces 8,760 actual hourly returns from 8,761 observations, retaining flat cash periods and final OPEN marks.
- Sharpe uses sample excess standard deviation (ddof=1); Sortino uses all-period downside RMS with zero from non-downside hours. Explicit hourly annualization is 8,760 periods/year, with zero per-period risk-free return and zero MAR. 61 Stage 5.17 tests pass; all 458 tests pass (397 earlier + 61 Stage 5.17).
- Notebook 03 now presents eight-result/four-path summaries, compact return previews, interpretation, references/preservation checks, and exactly one NET hourly-return diagnostic. All 47 code cells executed sequentially without saved errors: 96 cells total, 49 Markdown, seven plots. All six previous plot sources/images remain byte-identical. Existing production modules/tests, decisions 001–008, notebooks 01/02, raw data, and dependencies are unchanged. No Stage 5.18 or Stage 6 work was started.

- Stage 5.18 consolidated notebook 03 into the final Stage 5 report: research setup, four-portfolio headline comparison, EMA trade behavior, integrated interpretation, limitations, and one final regression/preservation audit. Tables and explanations reuse existing helper outputs; no financial formulas or production APIs changed.
- All 51 code cells executed sequentially without saved errors: 104 total cells, 53 Markdown, seven plots. All seven existing plot sources/images remain byte-identical; no plot was added. All 458 existing tests pass; no new tests, production modules, decisions, dependencies, or project files were added. Stage 5 is complete; Stage 6 has not started.

- Stage 6.1 accepted [decision 010](decisions/010_generic_strategy_backtest_contract.md), defining canonical strategy fields, strict candle/index alignment, desired-state transitions, next-OPEN timing, optional diagnostics, causality responsibilities, and the frozen EMA regression gate.
- This contract-only milestone changes no production code, tests, notebooks, dependencies, data, or decisions 001–009. The existing 458-test baseline is preserved. Stage 6.2 awaits owner approval; Stage 7 has not started.

- Stage 6.2 added `backtest/strategy_validation.py` with `validate_strategy_output(candles, strategy_output)`, implementing decision 010's canonical fields, strict alignment, fixed one-hour availability, and desired-state machine. It returns an independent full strategy-output copy with diagnostics unchanged; no execution is called.
- Added 48 synthetic unittest methods, including EMA compatibility, DST, typed empty frames, duplicate index labels, strict scalar types, and input/output preservation. All 506 tests pass (458 unchanged baseline + 48 new). Pipeline, execution, EMA, existing tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic are unchanged. Stage 6.3 awaits owner approval; Stage 7 has not started.

- Stage 6.3 added `run_execution_pipeline(candles, strategy_output)` to `backtest/pipeline.py`. It delegates canonical validation, transfers only the validated signal into a local candle copy, and delegates next-OPEN execution. The separate six-column execution output retains authoritative candle OPEN values, dtypes, and index; strategy diagnostics cannot override market prices.
- Added 25 synthetic unittest methods covering timing, final no-fill cases, exact direct-helper parity, colliding diagnostic names, validation delegation, input preservation, causal prefixes, and defensive output checks. All 531 tests pass (506 unchanged baseline + 25 new). The existing EMA pipeline and alignment helper retain their original source; execution, validator, EMA strategy, existing tests, decisions, notebooks, dependencies, data, and Stage 5 financial logic are unchanged. Stage 6.4 awaits approval; Stage 7 has not started.

- Stage 6.4 added `run_backtest_pipeline(...)` in `backtest/pipeline.py`, composing generic execution → ledger → independent GROSS/NET accounting. It returns exactly `execution`, `trades`, `gross_results`, and `net_results`; helper outputs and financial formulas are unchanged.
- Added 15 synthetic unittest methods; the full suite passed once with 546 tests (531 unchanged baseline + 15 new). Non-EMA intent reaches accounting; exact direct-composition parity, OPEN/final no-fill behavior, compounding, costs, diagnostics, errors, preservation, and index/timezone conventions pass. Existing pipeline functions, lower layers, EMA, analytics, old tests, decisions, notebooks, dependencies, data, and Stage 5 logic are preserved. Stage 6.5 awaits approval; Stage 7 has not started.

- Stage 6.5 added `tests/test_ema_generic_regression.py`, proving exact EMA20/50 compatibility between the existing EMA pipeline and generic strategy/execution/ledger/accounting paths on the frozen local BTC snapshot. The existing raw SHA-256 and Stage 5 financial/analytics references pass without changing production logic or tolerances.
- All 16 new regression methods execute with zero failures, errors, or skips; the full suite passed once with 562 tests (546 unchanged baseline + 16 new). All production modules, old tests, decisions, notebooks, dependencies, and raw data remain unchanged. No EMA wrapper migration or notebook execution occurred. Stage 6.6 awaits approval; Stage 7 has not started.

- Stage 6.6 added and executed `notebooks/04_generic_backtest_engine.ipynb`: 23 cells (11 code / 12 Markdown), sequential counts 1–11, zero saved errors, and one embedded GROSS/NET candle-close equity plot. It demonstrates existing EMA intent through the generic engine, separate accounting outputs, downstream equity helpers, and a tiny synthetic non-EMA contract example.
- Frozen BTC sanity references and input/raw-file preservation checks pass. All 562 existing tests passed once; no unit tests or production Python changes were added. Old tests, decisions, notebooks 01–03, `.py` placeholders, dependencies, and raw data are unchanged. Stage 6.7 awaits approval; Stage 7 has not started.

- Stage 6.7 completed the final contract/API, commit-chain, file-scope, frozen Stage 5, and saved notebook audit. Stage 6 — Generic Backtesting Engine is COMPLETE.
- All 104 Stage 6 methods and the full 562-test suite pass with zero failures, errors, or skips. This closure changes documentation only; Stage 7 awaits explicit owner approval.

- Stage 7.1 accepted Decision 011: a fixed current-capital allocation fraction in `(0, 1]`, default 1.0, with risk returning a budget and accounting calculating quantity. Reserve cash, OPEN/final-signal semantics, exact Stage 6 compatibility, and the 7.1–7.9 roadmap are documented.
- Documentation/architecture only: no sizing implementation, production/test/notebook/old-decision/dependency/data changes. The existing test inventory remains 562; Stage 7.2 awaits explicit owner approval and has not started.

- Stage 7.2 added the pure scalar `risk/position_sizing.py` helper, `calculate_position_budget(capital_before, position_fraction=1.0) -> float`. It returns current capital times a valid fixed fraction, with positive finite float validation and no accounting/pipeline/equity integration.
- Added 35 synthetic scalar unittest methods. All 35 targeted tests and the full 597-test suite (562 existing + 35 new) pass with zero failures, errors, or skips. Existing production modules/tests, risk package exports, decisions, notebooks, dependencies, and data are unchanged. Stage 7.3 awaits explicit owner approval and has not started.

- Stage 7.3 integrated the fixed budget helper into direct GROSS accounting via the trailing `position_fraction=1.0` parameter. Partial quantities/PnL compound total capital; raw position-return semantics and the exact output schema are unchanged, with reserve derived rather than stored.
- Added 25 synthetic integration methods. New tests (25), unchanged GROSS tests (27), and sizing-core tests (35) pass; the full suite passed once with 622 tests (597 existing + 25 new), zero failures, errors, or skips. The frozen Stage 6 default EMA regression remains green; NET/equity/pipeline sizing integration remains pending and Stage 7.4 has not started.
- Stage 7.4 integrated fixed-fraction budgets into direct NET accounting through the trailing `position_fraction=1.0` parameter. The budget includes entry fees; reserve is derived rather than stored, and total NET capital compounds independently. Existing return meanings, costs, schema, and OPEN semantics are preserved.
- Added 33 synthetic NET integration methods. New tests (33), unchanged transaction-cost tests (21), GROSS sizing tests (25), and sizing-core tests (35) pass; the full suite passed once with 655 tests (622 existing + 33 new), zero failures, errors, or skips. Frozen Stage 6 default EMA regression remains unchanged. Stage 7.5 awaits explicit owner approval and has not started.
- Stage 7.5 made GROSS/NET candle-CLOSE equity reserve-aware using canonical entry spend. Cash remains reserve while LONG; actual exit capital, raw marks, unrealized PnL, public APIs, schemas, dtypes, and timing are preserved. NET entry fees are paid once; full-allocation reserve remains exact zero.
- Added 31 synthetic partial-equity methods. New tests (31), unchanged equity tests (47), GROSS sizing tests (25), and NET sizing tests (33) pass; the full suite passed once with 686 tests (655 existing + 31 new), zero failures, errors, or skips. Frozen Stage 6 MTM references remain unchanged. Stage 7.6 awaits explicit owner approval and has not started.
- Stage 7.6 added trailing `position_fraction=1.0` to the generic backtest pipeline, forwarding it unchanged to both independent accounting paths. Execution, ledger behavior, four return keys, and exact default compatibility are preserved; equity remains downstream.
- Added 24 synthetic pipeline integration methods. New tests (24), retained generic pipeline methods (15), GROSS sizing tests (25), NET sizing tests (33), and partial-equity tests (31) pass; the full suite passed once with 710 tests (686 existing + 24 new), zero failures, errors, or skips. Frozen Stage 6 references and tolerances are unchanged. Stage 7.7 awaits explicit owner approval and has not started.
- Stage 7.7 verified the complete frozen Stage 5/6 path at fraction 1.0 and downstream analytics compatibility at 0.50/0.25. Canonical BTC partial snapshots are now literal regression constants; execution, ledger, duration/exposure, and benchmark paths remain fraction-independent. No production code, analytics API/formula, existing test, decision, notebook, dependency, or data changes were required.
- Added 37 real-BTC regression methods. New regression (37), frozen EMA regression (16), trade metrics (35), realized drawdown (32), trade time (41), equity (47), portfolio drawdown (55), benchmark (38), risk-adjusted (61), generic sizing pipeline (24), and partial equity (31) targeted tests pass. The full suite passed once with 747 tests (710 existing + 37 new), zero failures, errors, or skips. All frozen Stage 5/6 references/tolerances are unchanged. Stage 7.8 awaits explicit owner approval and has not started.

- Stage 7.8 added executed educational notebook `notebooks/05_risk_position_sizing.ipynb`, comparing fixed fractions 1.0/0.50/0.25 through the existing generic pipeline, reserve-aware GROSS/NET equity, drawdown, and Sharpe/Sortino helpers. All 32 cells (15 code / 17 Markdown) are saved with sequential counts 1–15, zero errors, and two embedded plots.
- The unchanged 37-method position-sizing regression, 16-method frozen EMA regression, and full 747-test suite pass with zero failures, errors, or skips. Frozen references, source/test/decision/dependency/data files, notebooks 01–04, and all existing `.py` placeholders are preserved. Stage 7.9 awaits explicit owner approval and has not started.

- Stage 7.9 completed the final contract/API, milestone-chain, file-scope, frozen regression, and committed-notebook audit. Stage 7 — Risk Manager + Position Sizing is COMPLETE. All 185 Stage 7 test methods, the 16-method frozen EMA regression, and the full suite (run once: 747 tests) pass with zero failures, errors, or skips. Documentation only; Stage 8 — Strategy Robustness is next and has not started.

- Stage 8.1 accepted [Decision 012 — Strategy Robustness Contract](decisions/012_strategy_robustness.md) and the 8.1–8.8 roadmap. Documentation/architecture only; no production, test, notebook, dependency, or data changes. The full existing suite passed once: 747 tests, zero failures, errors, or skips. Stage 8.2 awaits explicit owner approval and has not started.

- Stage 8.2 added the focused `trading_lab.robustness` package: chronological splitting, generic cold-start segment evaluation, and independent IS/OOS orchestration using existing pipeline/equity APIs. The 56 new methods and all 803 suite tests pass with zero failures, errors, or skips; frozen Stage 5–7 references/tolerances, existing modules/tests, decisions, notebooks, dependencies, and data are unchanged. Stage 8.3 awaits explicit owner approval and has not started.

- Stage 8.3 added a generic deterministic parameter-grid evaluator through the unchanged Stage 8.2 core and existing analytics. The 36 new methods and full 839-test suite pass with zero failures, errors, or skips, including the canonical 25-combination BTC research grid and direct EMA20/50 parity. No ranking, selection, optimization, or default parameter changes. Stage 8.4 awaits explicit owner approval and has not started.

- Stage 8.4 added downstream-only two-dimensional parameter stability diagnostics on the existing sensitivity table, using supplied-order radius-one Moore adjacency and finite local statistics. The 39 new methods and full 878-test suite pass with zero failures, errors, or skips, including canonical BTC geometry for three OOS NET metrics. No backtest reruns, ranking, classification, threshold, or score. Stage 8.5 awaits explicit owner approval and has not started.

- Stage 8.5 added deterministic expanding row-count windows and independent fixed-configuration train/test evaluation through the unchanged Stage 8.2 core. The 42 new methods and full 920-test suite pass with zero failures, errors, or skips, including three canonical BTC windows. No state/capital/trade carry, cross-boundary fills, parameter selection, summary metrics, or stitched equity. Stage 8.6 awaits explicit owner approval and has not started.

- Stage 8.6 added downstream-only IS/OOS and walk-forward diagnostic tables over precomputed canonical results, reusing existing analytics. The 62 new methods and full 982-test suite pass with zero failures, errors, or skips. Neutral comparisons and finite-only test-window statistics preserve undefined raw metrics without reruns, window compounding, stitched equity, scores, classification, or parameter recommendations. Stage 8.7 awaits explicit owner approval and has not started.

- Stage 8.7 added and executed `notebooks/06_strategy_robustness.ipynb` using accepted production APIs and only the hash-verified local BTC snapshot. All 34 cells (17 code / 17 Markdown) executed sequentially with zero errors and six visually inspected embedded figures. Canonical split/grid/neighborhood/walk-forward and input/raw-hash checks pass; all 982 tests remain green. No production/test/decision/earlier-notebook/dependency/data/result changes, optimization, score, or stitched equity. Stage 8.8 awaits explicit approval; Stage 8 remains INCOMPLETE.

- Stage 8.8 completed the Decision 012 contract/API, seven-commit milestone chain, file-scope, frozen Stage 5–7 regression, canonical BTC, and saved-notebook audits. Stage 8 — Strategy Robustness is COMPLETE. Its 235 new tests plus the unchanged 747-test baseline give 982 passing tests, zero failures/errors/skips. Documentation only; source, tests, decisions, notebooks, dependencies, data/results, and reference values/tolerances are preserved. Stage 9 — Bybit Demo Exchange Adapter awaits explicit owner approval and has not started.

- Stage 9.2 added the pinned official connector, validated Demo-specific credentials, centralized Demo-only HTTP construction, and 42 offline unittest methods. All 42 new methods, all 16 frozen EMA regression methods, and the full suite run once (1,024 tests = 982 + 42) pass with zero failures/errors/skips. No exchange request, real credential, order, instrument/amount normalization, or runtime loop; Stage 9.3 awaits explicit approval and is not started.

- Stage 9.3 added exact-symbol Spot metadata retrieval, immutable Decimal rules, quote-unit BUY and base-unit SELL round-down normalization, and 93 offline unittest methods. Current fields are authoritative; deprecated fields and dimensionally invalid constraints are not used. All new methods, Stage 9.2's 42 methods, frozen EMA's 16 methods, and the full suite run once (1,117 = 1,024 + 93) pass with zero failures/errors/skips. No real credentials, actual exchange requests, wallet/order reads, placement, or runtime; Stage 9.4 awaits approval and is not started.

- Stage 9.4 added broker-independent immutable account/currency/order/fill snapshots, finite explicit statuses, a read-only Protocol, and a Demo-only Bybit adapter. All 123 new offline tests, 148 existing exchange/API tests, 16 frozen EMA regression tests, and the final full suite (1,240 = 1,117 + 123) pass with zero failures/errors/skips. No trading actions, execution/strategy wiring, real credentials, actual exchange requests, dependency changes, or changes to frozen Stage 5 behavior. Decision 014 records the stable read contract; Stage 9.5 awaits approval and is not started.

- Stage 9.5 added immutable authorized requests and separate placement/cancellation receipts, with a Demo-only two-action adapter. All 76 new offline tests and the unchanged Stage 9.2–9.4/EMA gates pass; full suite: 1,316 tests (1,240 + 76), zero failures/errors/skips. No actual broker request, new dependency, strategy/runtime wiring or portfolio mutation. Stage 9 remains INCOMPLETE; Stage 9.6 is next and NOT STARTED.

- Stage 9.6 added 34 deterministic cross-component regressions and 34 offline manual-smoke control tests, plus the explicitly opt-in bounded CLI. A verified SDK diagnostic leak required client-local log muting in the existing session factory; all public APIs, routing/retry settings and trading/financial behavior remain unchanged. Full suite: 1,384 tests (1,316 + 68), zero failures/errors/skips. No authenticated Demo request, notebook/data change or new dependency. Stage 9 remains INCOMPLETE; Stage 9.7 is next and NOT STARTED.

- Stage 9.7 completed the Decisions 013–016 contract, six-commit scope, Demo/secret/capability/manual-smoke safety and frozen historical regression audits. No blocking findings or production fixes; documentation only, no new tests. All targeted gates and the full 1,384-test suite pass with zero failures/errors/skips; pip check and git diff --check pass. Stage 9.1–9.7 and Stage 9 are COMPLETE; Stage 10 is next and NOT STARTED. No actual authenticated Demo smoke/order was executed during Stage 9.

- Stage 10.1 defined the Demo runtime contract in Accepted Decision 017: durable identity/ownership, original-ID recovery, finite states, anchored closed-candle handling, pure planning, explicit fixed quote BUY/owned base SELL authorization, SQLite intent/checkpoints and a single-host account lock. Documentation only; no implementation, new tests/dependency, authenticated request or order. Stage 9 remains COMPLETE; Stage 10 is INCOMPLETE; Stage 10.2 is next and NOT STARTED.

- Stage 10.2 implemented the broker-independent pure operational state core under unchanged Decision 017: frozen/slotted records, exact eight states, typed events/evidence/reason codes, Decimal ownership invariants, retained pending identities, explicit recovery/rearm and shutdown. Added 188 offline tests, including all 120 state/event pairs. No I/O, ID generation, action planner, sizing, journal phases, persistence, scheduler, reconciliation service or broker action. Stage 10.3 is next and NOT STARTED.

- Stage 10.3 added standard-library SQLite durable identity/configuration, checkpoints, candle/decision/action/fill journals and a canonical POSIX account lock. Short atomic transactions retain exact Decimal money, original IDs, one-attempt phases and a contiguous decision frontier. Added 188 offline tests, including all 49 phase pairs, rollback faults and real subprocess exclusion. Stage 10.1/10.2 remain frozen; 10.4 is next and NOT STARTED.

## Demo Trading Runtime contract

[Decision 017 — Demo Trading Runtime Contract](decisions/017_demo_trading_runtime_contract.md) is Accepted and frozen by Stage 10.1 commit `b9eb945674fb450515164eb54256d7ac7270d29d`; its reviewed Stage 9 baseline is `4113ad653ccd46be40fafd165d78bf75589a2ce5`. Stage 10.2 implements its pure state core; 10.3 adds durable primitives without changing that core. Decisions 010–017, existing production APIs, frozen EMA values/tolerances, next-OPEN/final-candle behavior, notebooks and research accounting remain unchanged.

Initial scope: one Bybit Demo account/bot/strategy/symbol/hourly timeframe, Spot LONG/FLAT and MARKET actions, no borrowing, leverage or shorts. Stable `(broker_id, account_binding, bot_id)` identity survives restart; strategy code/parameters, symbol/timeframe and non-secret configuration are bound to it. Only exact persisted action/link/broker evidence proves order ownership; symbols, link prefixes and wallet holdings alone do not. Stage 9.4's account label is not a verified broker UID.

The pure model now distinguishes STARTING, SYNCHRONIZING, FLAT, LONG, ORDER_PENDING, UNCERTAIN, HALTED and STOPPING, separately from desired intent, order status and partial owned exposure. Future orchestration must persist original logical action IDs/links before a possible send and retain them across restart; receipts remain separate from fills. Missing observations preserve uncertainty. The existing broker-ID lookup and seven-day execution window may leave lost-acknowledgement recovery unresolved; future bounded reconciliation must HALT rather than resend or bypass the adapter.

Stage 10.3 implements standard-library SQLite with short durable transactions (`DELETE` journal / `EXTRA` synchronization) and a process-lifetime canonical account OS file lock. It stores unique candle decisions, action/ownership/fill history and checkpoints, excluding secrets/raw SDK payloads. Intent and a separate attempt-start marker can be committed before a future broker action; broker/database atomicity is not claimed.

Reuse the unchanged hourly EMA strategy from one persisted history anchor. Bootstrap/downtime replay restores intent without historical orders; one unique committed logical decision per closed candle prevents duplicate authorization after restart. Submit only after fresh completed-candle information; Demo execution uses broker prices/timestamps, never modeled next-OPEN fills. The pure planner returns NOOP, PLACE_BUY, PLACE_SELL, WAIT, RECONCILE or HALT. Initial BUY requires an explicitly configured exact quote budget; SELL is bounded by confirmed owned base quantity. Stage 7 `position_fraction` and whole-wallet sizing are not runtime policy. No automatic cancellation/liquidation on shutdown.

### Pure runtime state core — Stage 10.2

`src/trading_lab/runtime/state.py` exports `RuntimeState`, `PositionEvidence`, `PendingActionKind`, `RuntimeReason`, `RuntimeEventType`, frozen/slotted `PendingAction`, `RuntimeEvidence`, `RuntimeStateSnapshot`, `RuntimeEvent`, `RuntimeStateError(ValueError)`, and `transition_runtime_state(current: RuntimeStateSnapshot, event: RuntimeEvent) -> RuntimeStateSnapshot`. The minimal package explicitly re-exports these names.

Snapshots hold state, optional exact owned base quantity, evidence quality, independent desired 0/1/unknown intent, one optional pending action reference, safe reason code and prior state for shutdown. Unknown quantity is None; stale quantity is LAST_KNOWN, not confirmed current truth. FLAT requires confirmed exact zero without pending work; LONG requires confirmed positive quantity without pending work; ORDER_PENDING requires confirmed zero/partial exposure and one unresolved lifecycle. No quantities are rounded/coerced and no quote/base conversion is performed.

Fifteen typed events explicitly encode startup, complete flat/long/pending evidence, validated recovery, no change, externally authorized entry/exit preparation, freshness loss, uncertainty, fatal inconsistency, shutdown, operator rearm, and separate placement/cancellation acknowledgements. Every unlisted state/event pair raises RuntimeStateError. A receipt never changes exposure or clears pending work; terminal recovery must match the exact current action ID. UNCERTAIN may recover directly on complete evidence as Decision 017 allows; HALTED remains latched until explicit rearm through SYNCHRONIZING. STOPPING retains prior state/reason/quantity/pending work and rejects every further event.

RuntimeEvidence asserts already-complete caller-validated facts; this pure module cannot prove broker ownership, fill completeness, freshness or authorization. These belong to later layers. IDs are validated supplied SHA256 references, never generated. Action journal phases remain separate from this pure module and are now implemented in Stage 10.3's store. No broker OrderStatus, SDK/client/raw payload, secret, clock, file handle, logger or database is stored or accessed by the state module.

Validation: **188 Stage 10.2 tests**, including **120 matrix cases (42 allowed / 78 forbidden)**; unchanged Stage 9.6 integration/smoke controls **68** and frozen EMA **16** pass. Full suite **1,572 (1,384 + 188)**, zero failures/errors/skips; `pip check` and `git diff --check` pass. Existing source/tests, Decisions 001–017, notebooks, data/results and installed packages are preserved. No authenticated Demo request/smoke/order, persistence, lock implementation, planner, sizing, market-data gate, scheduler or runtime loop was added.

### Durable storage and account lock — Stage 10.3

`runtime/store.py` and `runtime/locking.py` add infrastructure under unchanged Decision 017. Import these submodules explicitly; the frozen package exports and `state.py` remain unchanged. No new ADR or dependency is needed.

Public records are frozen/slotted: `RuntimeConfiguration`, `RuntimeCheckpoint`, `CandleRecord`, `DecisionRecord`, `ActionRecord`, and `OwnedFillRecord`. Configuration binds `(broker_id, account_binding, bot_id)`, optional supplied broker account ID, schema/contract versions, strategy/configuration SHA256 digests, exact strategy parameters, instrument/currencies/hourly interval, exact BUY quote budget, history anchor and finite age/read/reconciliation/timeout/clock policies. Initial supported configuration is `bybit-demo`, `ema_trend` with EMA20/50 and 50 warm-up candles, timeframe `"60"` and interval `3_600_000`. Digests/IDs and verified account facts must be supplied by the caller; this store does not generate or verify broker identity.

Checkpoint retains the frozen snapshot, sequence, frontier, reconciliation/observation times and coverage, HALT/shutdown/rearm markers and bootstrap/replay cutoffs. Candle and decision records retain supplied OHLCV/fingerprint, hourly identity, signal, desired position, availability, disposition and action reference. Action records preserve original action/link/order/control references, exact authorized/submitted amounts and units/currency, receipts, observations, safe reasons, terminal evidence, attempt count and remaining recovery bounds. Owned fills preserve exact execution identity/ownership, quantity/price/signed fee/currency and execution/observation times. Unavailable values remain `None`/SQL NULL.

`ActionPhase` has exactly PREPARED, ATTEMPT_STARTED, ACKNOWLEDGED, UNKNOWN_OUTCOME, TERMINAL_CONFIRMED, REJECTED and ABANDONED_UNSENT, separate from operational state. `JournalActionKind` is ENTRY/EXIT/CANCEL; cancellation is a subordinate explicit control. `DecisionDisposition` is BOOTSTRAP/REPLAY_ONLY/NOOP/WAIT/ACTION/HALT. No phase, disposition or stored intent causes an action.

Public persistence API:

```python
RuntimeStore.open(lock, configuration, *, initialize=False) -> RuntimeStore
store.durability_settings() -> dict
store.get_configuration() -> RuntimeConfiguration
store.get_checkpoint() -> RuntimeCheckpoint
store.get_candle(candle_open_ms) -> CandleRecord | None
store.get_decision(candle_open_ms) -> DecisionRecord | None
store.get_action(action_id) -> ActionRecord | None
store.get_fill(execution_id) -> OwnedFillRecord | None
store.list_actions() -> tuple[ActionRecord, ...]
store.list_fills(action_id: str | None = None) -> tuple[OwnedFillRecord, ...]
store.save_checkpoint(checkpoint, *, expected_sequence) -> None
store.commit_decision(candle, decision, checkpoint, *, expected_sequence, action=None) -> bool
store.prepare_cancellation(action, checkpoint, *, expected_sequence) -> None
store.start_attempt(action_id, checkpoint, *, expected_sequence) -> None
store.abandon_prepared(action_id, checkpoint, *, expected_sequence, terminal_at_ms) -> None
store.record_observation(action, checkpoint, *, expected_sequence, fills=()) -> None
store.close() -> None
serialize_decimal(value: Decimal) -> str
deserialize_decimal(value: str) -> Decimal
```

Schema and runtime-contract version are **1**, with tables `identity`, `checkpoint`, `candles`, `decisions`, `actions`, `fills`. Required table/index definitions, `PRAGMA user_version`, `quick_check(1)`, foreign keys and every stored record are validated on open. Unsupported/corrupt/missing existing stores fail explicitly; no reset, migration, replacement upsert or historical ID deletion exists. Initialization must use `initialize=True` for a genuinely absent DB; it refuses an existing file. Identity/configuration must match exactly on reopen.

Money is finite Decimal serialized to canonical plain TEXT without float conversion or context rounding; trailing fractional zeroes/signed zero canonicalize without changing numeric value. Timestamps are validated integer UTC milliseconds, with hourly candle keys. Enums serialize explicit values and unknown stored values fail. Integrity checks are bounded at 100,000 rows per table, 256 MiB per DB, 10,000 fills per write and a conservative 4,096-character Decimal representation bound; excessive records fail rather than truncate, and writes cannot exceed store limits.

Effective required PRAGMAs are `journal_mode=delete`, `synchronous=3` (EXTRA), `foreign_keys=1`, and `fullfsync=1` on supported macOS. Settings are checked before reads/writes; drift blocks access. Existing WAL stores are rejected without conversion. Fresh directories/DB entries are explicitly synced. Durability assumes functioning local storage/sync semantics; no network filesystem or distributed locking is supported.

Each public write owns a short `BEGIN IMMEDIATE` transaction. Candle + decision + optional PREPARED action + pending checkpoint + frontier commit together. Identical accepted replay returns `False` without applying the supplied checkpoint; conflicting contents/references fail. New decisions advance one contiguous anchored hour; sequences compare against `expected_sequence` and advance exactly once. Original action/link IDs remain unique tombstones. ATTEMPT_STARTED durably changes attempt count from 0 to 1; a second attempt/backward phase is forbidden. Receipts or UNKNOWN_OUTCOME are separate writes and cannot establish fills. Supplied fills, terminal evidence and supplied owned-quantity checkpoint commit atomically; duplicate execution facts are idempotent, retaining first observation time, while conflicting financial/ownership facts roll back. Indeterminate commit/rollback closes the store and requires reopening/validation, never an assumption of unsent work.

The store validates records, references and persistence invariants; it does not run the pure event graph, verify closure/freshness/finality, discover ownership, authorize size, calculate inventory/PnL or retrieve broker evidence. Terminal completeness and checkpoint quantity remain caller assertions for future reconciliation. Nonzero fees without known currency block terminal ownership settlement. HALT stays latched through persisted STOPPING until recorded rearm through synchronization.

`RuntimeAccountLock(registry_root: Path, account_binding: str, *, broker_id="bybit-demo")` exposes `acquire()`, `release()` and context management. The root must be explicit, absolute and already exist; aliases resolve canonically. Account key is SHA256 of compact ASCII JSON `[broker_id, account_binding]`, using stable non-secret labels, never API keys. Paths are `<root>/locks/<key>.lock` and `<root>/accounts/<key>/runtime.sqlite3`, independent of bot/config/DB selection. Store APIs accept no alternate database path. All cooperating launches **must use the same registry root and account binding**; this is a local cooperative lock, not broker-verified identity or protection against unrelated clients/hostile filesystem changes.

Acquire uses real `fcntl.flock(LOCK_EX | LOCK_NB)` and retains the same descriptor. Contenders fail immediately; file existence/metadata/PID is never ownership. Process death/descriptor close releases OS ownership. Explicit release/context exit never unlinks the persistent file; no metadata/secrets are written. Symlink/hardlink/replaced-path surprises and inherited-process use fail closed. Store requires the held lock and tracks open handles so the lock cannot be released first. Caller lifecycle is: acquire lock → open/validate DB → any separately approved future session/work → close future session → close all stores → release lock last. No session is constructed now. Generated `/runtime_state/` registry and fixed SQLite filenames/sidecars are ignored; tests use temporary directories only.

Errors: `RuntimeStoreError(RuntimeError)`, `RuntimeStoreIntegrityError`, `RuntimeStoreConflictError`, and `RuntimeLockError(RuntimeError)` use safe fixed diagnostics, without raw SQL, file contents, SDK data, environment dumps or secret values.

Validation: **188 new Stage 10.3 tests (165 storage + 23 locking)**, including all **49 phase pairs**, rollback/indeterminate-commit cases, integrity/identity/Decimal/reference/frontier checks and real subprocess exclusion/release. Stage 10.2 **188**, Stage 9.6 **68**, frozen EMA **16** pass. Full suite **1,760 (1,572 + 188)**, zero failures/errors/skips; `pip check` and `git diff --check` pass. All 121 protected tracked files, five local data/results files and 106 installed package versions match the starting baseline. No API key, pybit/HTTP/broker import, network request, authenticated Demo smoke/order, market-data gate, reconciliation service, planner/sizing, scheduler or runtime loop exists in these modules.

### Closed-candle market-data gate — Stage 10.4

Under unchanged Decision 017, `data/closed_candles.py` supplies pure broker-independent observations/validation and `exchange/bybit_public_market.py` isolates Bybit public parsing/HTTP. Existing Stage 1 float64/local-clock historical machinery cannot prove exact runtime closure or provide safe response diagnostics, so it remains frozen. The new reader reuses its fixed public Kline URL and backward pagination direction. No dependency, export change or ADR is needed.

Frozen/slotted `MarketCandle` holds symbol, timeframe, candle-open UTC ms and exact Decimal O/H/L/C/volume, matching durable `CandleRecord` semantics without persistence/fingerprint coupling. `MarketCandlePage` holds normalized ascending candles plus the page's reported server time. `ClosedCandlePrefix` holds symbol/timeframe, anchor, exclusive end, initial authoritative server time, latest page observation and a complete immutable candle tuple; `data_age_ms` is latest observation minus newest close (None only for an empty pure prefix).

Public APIs, imported explicitly from the new submodules:

```python
BybitPublicMarketReader(*, timeout_seconds=10.0)
reader.get_server_time() -> int
reader.get_closed_candles(*, symbol, history_anchor_ms, max_data_age_ms,
                         timeframe="60", end_ms=None, page_limit=1000,
                         max_pages=100) -> ClosedCandlePrefix
normalize_server_time(payload) -> int
normalize_public_klines(payload, *, symbol, timeframe="60") -> MarketCandlePage
validate_closed_prefix(candles, *, symbol, history_anchor_ms, server_time_ms,
                       timeframe="60", end_ms=None, observed_at_ms=None) -> ClosedCandlePrefix
validate_candle_freshness(*, newest_closed_candle_open_ms, server_time_ms,
                         max_data_age_ms) -> int
```

The reader permits only unauthenticated GET `https://api.bybit.com/v5/market/time` and the existing `/v5/market/kline` URL, always `category="spot"`, interval `"60"`. It creates its own short-lived Session, disabling environment/netrc authentication/proxies, clearing auth and refusing redirects. Timeout is finite in (0, 30] seconds; no arbitrary URL/client, credential, private endpoint, automatic retry or sleep exists. Import/construction performs no request.

Server normalization requires an integer non-bool successful `retCode`, result object, unsigned ASCII string `timeNano`/`timeSecond` and integer envelope `time`. Authority is `timeNano // 1_000_000`, cross-checked with seconds and envelope ms, within nonnegative signed-64-bit UTC ms; contradictions/missing values fail without local-clock fallback. Source nanoseconds are floored conservatively. The reader obtains this sample before Kline reads; every page's server timestamp must be at least the sample and previous page, preventing pre-close/cached facts from proving completion.

Closure is exactly `server_time_ms >= open_ms + 3_600_000`. Equality is closed; one millisecond before is not. Default end is the sampled server hour boundary; explicit end is exclusive/aligned and cannot include an unclosed hour. The first default page may contain the forming candle: validate it, then exclude it. Parsed rows have exactly seven fields, matching Spot/symbol context, optional matching interval echo (Bybit does not document a required echo), hourly-grid ASCII timestamps and bounded plain decimal strings. Prices are finite/positive, volume and discarded turnover nonnegative, and low <= open/close <= high. Decimal values never pass through float/context rounding.

Only broker normalization sorts/deduplicates. Identical accepted OHLCV values, including equal decimal values with different scale, may overlap; conflicting duplicates fail, never last-row wins. Pure prefix validation rejects unsorted/duplicate normalized inputs. One bounded backward read gathers complete `[anchor, end)` history, at most 100 pages × 1,000 rows and 100,000 candles. Caller page limits/capacity, row ranges, short pages, repeated/non-progressing pages and overlapping identities are checked. Missing first/last/internal hours, exhausted budget or a late HTTP/parse failure produce an explicit error and no partial result. A history anchor with no closed rows fails explicitly. At least 51 contiguous rows can be supplied for later EMA startup; this gate computes no EMA/signal.

Freshness uses `age_ms = server_time_ms - (newest_open_ms + 3_600_000)`. Pure validation requires a closed candle and a caller-supplied nonnegative integer limit; `age <= limit` is fresh, `age > limit` raises `StaleMarketDataError`. The reader uses the latest page-reported server time here, so pagination elapsed time cannot conceal stale data. Explicit historical end ranges need an explicitly adequate age bound. No local clock, skew threshold, runtime transition or historical action eligibility is inferred; later orchestration owns clock-skew diagnostics and dispositions.

Safe errors: `MarketDataError`, `MarketDataInputError`, `MarketDataTransportError`, `MarketDataResponseError`, `MarketDataIntegrityError`, `MarketDataContinuityError`, `StaleMarketDataError`. Network/JSON/API failures exclude raw bodies, headers and uncontrolled exception text. No account/wallet/order reads, mutations, authenticated session, store open/write, decision/action journal, state transition, reconciliation, strategy execution, sizing/planner, scheduler or runtime loop is reachable.

Public response fields were checked against the official [server-time](https://bybit-exchange.github.io/docs/v5/market/time) and [Kline](https://bybit-exchange.github.io/docs/v5/market/kline) documentation on 2026-10-11. Documentation browsing did not call a market API endpoint.

Validation: **97 new offline tests (34 pure + 63 Bybit boundary)**; frozen Stage 10.3 **188**, Stage 10.2 **188**, Stage 1 **13**, Stage 9.6 **68**, EMA **16** pass. Full suite **1,857 (1,760 + 97)**, zero failures/errors/skips; `pip check` and `git diff --check` pass. Frozen Stage 10.1–10.3, Stage 5 financial/timing baselines, source/tests/Decisions 001–017/notebooks/data/results and installed packages are preserved. No public HTTP smoke, credentials, authenticated Demo request/order or next milestone was executed.

### Startup / broker reconciliation — Stage 10.5 contract review

This records the initial, pre-correction review. The owner-approved correction and current validation are recorded separately below.

Starting HEAD: `1865435bb0310dd5d8e8ce7208d56650dc51590a` on `main`, tracking `origin/main`; the working tree was clean. Reviewed AGENTS, current project documentation, Decisions 010–017, runtime state/store/locking and their tests, Stage 10.4 source/tests, and the Stage 9 read boundary/lifecycle/integration contracts. No production implementation or new public API was added.

**Blocking finding: durable UNKNOWN_OUTCOME cannot recover to observed pending state without an acceptance receipt.** Decision 017 permits exact original-link discovery and recovery of a nonterminal order after a lost acknowledgement. Stage 10.2 permits `UNCERTAIN + RECONCILED_PENDING -> ORDER_PENDING`. However, `RuntimeStore._validate_relations()` rejects any UNKNOWN_OUTCOME action unless the checkpoint is UNCERTAIN, HALTED or STOPPING, even after the exact broker ID, nonterminal status and owned fills have been discovered.

Offline reproduction using a temporary store and the existing Stage 10.3 fixtures/public APIs:

1. Persist PREPARED, then the single ATTEMPT_STARTED marker.
2. Persist UNKNOWN_OUTCOME with an UNCERTAIN checkpoint and the original action/link.
3. Supply a discovered exact broker ID, PARTIALLY_FILLED status and an owned fill; obtain ORDER_PENDING through `transition_runtime_state(..., RECONCILED_PENDING)`.
4. Attempt the atomic `record_observation(action, checkpoint, expected_sequence=..., fills=...)` write.

The pure transition succeeds, but the write raises `RuntimeStoreIntegrityError: Unknown action outcome cannot retain confirmed operational certainty.` The transaction rolls back: the original action/checkpoint remain and no fill is inserted. OPEN with zero fills has the same invariant conflict. Changing phase to ACKNOWLEDGED requires `acknowledgement_broker_ms` and a receipt; broker discovery cannot fabricate that lost receipt. Returning to ATTEMPT_STARTED is forbidden by the frozen phase graph/observation API. Terminal confirmation is not an alternative for a nonterminal order.

**Related finding: explicit rearm cannot be persisted with an unresolved UNKNOWN_OUTCOME action.** After a durable HALT, Stage 10.2's explicit OPERATOR_REARMED event correctly produces SYNCHRONIZING with retained pending work. Even when `rearmed_at_ms > halted_at_ms` is supplied, `save_checkpoint` rejects SYNCHRONIZING under the same UNKNOWN_OUTCOME invariant and rolls back. HALT remains latched; no automatic rearm was attempted.

Owner review is required before changing the frozen Stage 10.3 contract. Proposed narrow review scope: distinguish an absent acceptance receipt from validated current pending-order observations, and permit explicit rearm through nonconfirmed SYNCHRONIZING while retaining uncertainty/pending evidence. Preserve original IDs, one-attempt phases, receipt/fill separation, checkpoint CAS, atomic writes and default rejection of unsupported certainty. Do not synthesize ACKNOWLEDGED receipts, terminal state or another send. No frozen implementation/test/ADR was changed to bypass either finding.

Stage 10.5 is **INCOMPLETE**; implementation stopped under the requested frozen-contract defect rule. No reconciliation broker acquisition, inventory calculation, persistence orchestration or new tests were introduced. Diagnostics used only temporary SQLite files and supplied records, with zero broker calls, credential/environment reads or exchange session construction. Existing regression tests retain their offline fakes/synthetic SDK fixtures. No actual authenticated request, order or cancellation occurred; no strategy, market-data integration, planner, scheduler or loop was added. Stage 10.6 is NOT STARTED and is next only after Stage 10.5 is completed/reviewed.

Validation after this review: **zero new Stage 10.5 unit tests**; targeted Stage 10.4 **97**, Stage 10.3 **188**, Stage 10.2 **188**, Stage 9.4 **123**, Stage 9.6 **68** and frozen EMA **16** pass. The unchanged full suite ran once: **1,857 tests**, zero failures/errors/skips. `pip check` reports no broken requirements; `git diff --check` passes. Production files, existing tests, Decisions 001–017, notebooks, dependencies and frozen financial/timing behavior remain unchanged. No commit or push was made.

### Owner-approved narrow Stage 10.3 persistence correction

Current status: reviewed and FROZEN at `ad3aca759dbb556d736996bf39b0ba035bb0e512`. The following paragraphs retain its original completion record; the separate additive read correction is recorded below.

The correction is **COMPLETE and ready for review/freeze** against starting HEAD `1865435`. Only `RuntimeStore._validate_relations()` changes: UNKNOWN_OUTCOME may coexist with nonconfirmed SYNCHRONIZING while retaining exact pending identity and existing HALT rearm rules. ORDER_PENDING is admitted only for the sole exact unresolved UNKNOWN_OUTCOME placement with attempt_count 1, known broker order ID, observation timestamp and OPEN/PARTIALLY_FILLED status. An unknown subordinate cancellation still blocks this confirmed-state exception. Missing acknowledgement/submitted-amount fields remain missing; no receipt, terminal state or resend is fabricated.

This aligns persistence with unchanged Decision 017 and Stage 10.2 recovery semantics. Schema/runtime-contract version 1, tables/columns/indexes, public signatures/record fields, phase graph, Decimal TEXT, checkpoint CAS, transactions/rollback and locking remain unchanged. Existing valid version-1 databases reopen without migration or record rewriting. Broker identity/freshness/fill completeness and inventory calculation remain future reconciliation responsibilities, not store guarantees.

Validation: **22 added storage tests; zero existing tests changed**. Storage **187 (165 + 22)**, locking **23** (Stage 10.3 total **210**), frozen Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123** and frozen EMA **16** pass. Full suite **1,879 (1,857 + 22)**, zero failures/errors/skips; `pip check` and `git diff --check` pass. All 49 phase-pair tests and the original general certainty guard remain unchanged. Tests cover receipt-free pending recovery, reopen/deduplication, atomic rollback, identity/status/budget/attempt rejection and explicit rearm without HALT bypass.

Stage 10.5 remains **BLOCKED / NOT COMPLETE until this correction is separately reviewed/frozen**. No reconciliation module/tests, broker acquisition, order/cancellation, credentials, actual broker request, planner or scheduler was introduced; Stage 10.6 remains NOT STARTED. Stage 10 remains INCOMPLETE. Stages 10.1, 10.2, 10.4, Stage 9, Decision 017, notebooks, historical data and frozen financial/timing behavior remain unchanged. Do not resume Stage 10.5 automatically.

### Owner-approved additive Stage 10.3 durable read-API correction

Current status: reviewed and FROZEN at `8b3a482f1d7d2586c2f609aa52f32adf283d8a60`. The following paragraphs retain its original completion record; Stage 10.5 implementation is recorded separately below.

The correction is **COMPLETE and ready for separate owner review/freeze** against starting HEAD `ad3aca759dbb556d736996bf39b0ba035bb0e512`, on clean `main`. Stage 10.5's resumed contract audit found that point reads required IDs that a restarted caller may not know: subordinate cancellation IDs are absent from the checkpoint, and durable execution IDs may outlive broker history. Public enumeration now exposes those local records without private SQL access or reconciliation policy.

```python
RuntimeStore.list_actions() -> tuple[ActionRecord, ...]
RuntimeStore.list_fills(action_id: str | None = None) -> tuple[OwnedFillRecord, ...]
```

`list_actions()` returns all ENTRY/EXIT/CANCEL records, unresolved and terminal, ordered by `logical_action_id ASC`. `list_fills()` returns all fills bound to the configured broker/account, or only the exact canonical full SHA256 action ID supplied, ordered by `executed_at_ms ASC, broker_execution_id ASC`. A syntactically valid unknown action ID returns `()`. Empty results describe only the local query, not whether an exchange order filled.

Both methods return immutable tuples of existing validated records. They run the existing complete-store validation before enumeration, including schema/binding, integrity/FK checks, record decoding and the 100,000-row-per-table bound. Corrupt or excessive history fails the whole call, including filtered reads; no LIMIT, skipped rows, partial success or repair occurs. SQLite read failures use safe RuntimeStore errors without raw exception text.

These primitives permit later discovery of cancellation phase/control/parent/target/budgets and retained fill identities/amounts/signed fees/timestamps after reopen. They do not resolve actions, infer fills, calculate inventory/PnL, change checkpoints/phases/budgets, perform transitions, access a broker or retry anything.

Schema/runtime-contract version **1**, tables/columns/indexes, existing write signatures, phase graph, one-attempt rule, Decimal TEXT, checkpoint CAS, transaction/rollback implementation, PRAGMAs and account lock remain unchanged. **No migration or data rewrite**; existing valid databases reopen normally. The first correction's SYNCHRONIZING/observed-pending guards, unknown cancellation block, receipt absence and explicit HALT rearm remain FROZEN. State machine, Stage 10.4, Stage 9, Decision 017, notebooks, historical data and dependencies are unchanged.

Added **24 enumeration tests**, with zero existing tests changed. Targeted results: RuntimeStore **211 (187 + 24)**, locking **23**, frozen Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.6 integration/smoke **68**, EMA **16** all pass. Full suite **1,903 (1,879 + 24)** passes with zero failures/errors/skips; `pip check` reports no broken requirements and `git diff --check` passes. Tests use local temporary databases and offline fixtures only, with no credentials, authenticated requests, account reads, orders or cancellations.

Stage 10.5 remains **BLOCKED / NOT COMPLETE until this additive correction is separately reviewed/frozen**. No reconciliation module/tests or Stage 10.6 work was added. Stage 10 remains INCOMPLETE; Stage 9 COMPLETE; Stage 10.6 NOT STARTED. Do not resume Stage 10.5 automatically.

### Startup / broker reconciliation — Stage 10.5 implementation

Starting baseline: clean `main` at `8b3a482f1d7d2586c2f609aa52f32adf283d8a60`. Both Stage 10.3 corrections are owner-reviewed and FROZEN. Stage 10.5 adds only `runtime/reconciliation.py`, `tests/test_runtime_reconciliation.py` and current documentation; Decision 017 and every previously frozen source/test remain unchanged.

```python
reconcile_startup(
    store: RuntimeStore,
    broker: ReadOnlyBroker,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
) -> ReconciliationResult
```

`ReconciliationResult` is frozen/slotted and contains the committed checkpoint, original/recovered placement, subordinate cancellation and newly accepted execution IDs. `ReconciliationError` reports invalid caller/clock input with fixed safe diagnostics. Import the submodule explicitly; frozen package exports remain unchanged. The caller must hold the canonical account lock and supply an already-open validated store, already-constructed Demo read-only broker and aware UTC control clock. No credentials, SDK session or broker payload is accessed.

Each invocation performs at most one acquisition attempt: account, complete managed-symbol open orders and available managed-symbol executions; a pending candidate additionally receives exact `get_order(order_id)` and `get_executions(order_id=...)` reads. At most five public broker calls, each retaining Stage 9's own timeout/page bounds. A lost acknowledgement searches only the exact persisted link, never a prefix; a unique validated candidate ID is retained even if the order is not yet visible. Multiple IDs, wrong ownership and unrecorded namespace activity HALT. Unrelated managed-symbol open orders block activation and are never adopted or cancelled.

Public `get_configuration()`, `get_checkpoint()`, `list_actions()`, `list_fills()` and the exact pending `list_fills(action_id)` load validated durable history before broker reads. Terminal historical ownership remains authoritative after broker retention expires. A fresh explicitly initialized journal establishes zero bot-owned inventory only when successful reads reveal no owned pending/history conflict; unrelated wallet BTC is not adopted. Caller account labels are compared when present but are not authenticated exchange IDs. A configuration requiring verified broker account identity fails closed because Stage 9's label cannot prove it.

Owned inventory derives from exact deduplicated owned fills. BUY adds base quantity, SELL subtracts it; signed base-currency fees reduce quantity and base rebates increase it. Quote/other-currency fees stay separate, without conversion/PnL. Nonzero fee with missing currency blocks settlement. Previously known quantity must agree with its durable fill history. Positive quantity requires the configured base `total_balance` (walletBalance, including locked holdings) to cover it; missing balance means uncertainty, insufficient coverage HALTs. Account USD aggregates/availability do not prove asset holdings or authorize sizing. A FILLED quote BUY may leave budget unused; a FILLED SELL may leave an exact positive LONG remainder. Negative owned inventory is fatal; no rounding to FLAT.

Coherent OPEN/PARTIALLY_FILLED observations produce ORDER_PENDING and atomically persist ID/status/time, accepted new fills, quantity and checkpoint through `record_observation()`. UNKNOWN_OUTCOME stays UNKNOWN_OUTCOME, attempt count stays 1 and missing receipt/submitted amount remain absent. Terminal status requires cumulative execution completeness and coherent timestamps, then exact resulting quantity selects FLAT/LONG. UNKNOWN, not-found, stale/incomplete reads and non-atomic races remain UNCERTAIN; failed reads have no empty fallback. Safe UNKNOWN diagnostics can be stored, but optional external text outside the frozen safe-text format is omitted instead of being exposed or changing status.

`list_actions()` discovers subordinate controls without their IDs being in the checkpoint. A cancellation receipt does not establish terminal status; observing an OPEN parent does not resolve an unknown cancellation. Coherent terminal parent/fill evidence closes the control lifecycle with the actual parent status (including FILLED if it won the race), without claiming cancellation succeeded. Control settlement is one short write retaining the uncertain pending parent, followed by atomic placement/fills/quantity/checkpoint settlement; a crash between them retains recoverable original pending work. Provably unsent PREPARED placement/control records are abandoned through the existing public API, with IDs retained and no replay.

Before I/O, one reconciliation-round and read-attempt token is durably reserved per unresolved attempted action. Counts never reset across restart; no automatic retry, resend or sleep loop exists. Persisted deadlines and configured elapsed timeout are checked between calls with UTC and monotonic clocks; an in-flight bounded paginated adapter call is not interrupted. Unresolved exhausted recovery HALTs. HALTED and STOPPING return unchanged without reads; operator rearm is never fabricated. Broker reads occur outside SQLite transactions, verified against the real temporary connection in every fake broker operation. No exchange/SQLite atomicity is claimed.

Operational changes use frozen `transition_runtime_state()` events: STARTUP_VALIDATED, FRESHNESS_LOST, RECOVERY_VALIDATED, RECONCILED_FLAT/LONG/PENDING, UNCERTAINTY_DETECTED and FATAL_INCONSISTENCY. Persistence uses only public `save_checkpoint()`, `record_observation()`, `abandon_prepared()` and point action reads for committed results. No private connection/SQL, action creation, strategy, planner, Stage 10.4 reader, scheduler, backtest, PnL or broker mutation path exists. Persistence failure propagates without pretending that a HALT or observation committed.

Validation: **82 new Stage 10.5 tests**, zero old tests changed. RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.6 **68** and frozen EMA **16** pass. Full suite **1,985 (1,903 + 82)** passes with zero failures/errors/skips; `pip check` reports no broken requirements and `git diff --check` passes. No credentials, actual broker/account request, authenticated Demo smoke, order or cancellation was executed. Source/schema/APIs of frozen stages, Decisions 001–017, data, results, notebooks and dependencies are preserved.

Stage 10.5 is **COMPLETE / ready for owner review/freeze**. Stage 9 COMPLETE; Stages 10.1–10.4 and both Stage 10.3 corrections FROZEN; Stage 10 INCOMPLETE. Stage 10.6 — Runtime Action Planner + Explicit Demo Sizing Policy is next and NOT STARTED. Do not begin it automatically.

### Stage 10.5 exact-execution ownership correction

Current status: owner-reviewed and FROZEN at `757682038f2a5686e5d45e98dda378e91901b392`. The following record retains its completion-time status and test totals.

Owner review of published Stage 10.5 (`c450025793a857132b8f29880a5e0afbcb5c600b`) identified incomplete ownership binding at the exact-order execution read. Merged views already guarded persisted known IDs, but a newly recovered ID was not yet in the durable action map: later executions with missing/unmapped links could be skipped and allow false pending or terminal confirmation.

Every exact-order execution now passes through `_execution()` against the original placement and selected broker ID before merging. Missing optional links remain UNCERTAIN; explicit identity contradictions HALT, including a wrong link accompanied by stale timestamps. Matching executions reuse broker/account, symbol/side, UTC/freshness and exact quantity/price/fee validation. No execution from an incomplete/conflicting round is persisted, and an older order snapshot cannot force consistency with newly visible fills.

Added **8 focused tests** covering exact-only missing/wrong/correct links, order-snapshot races, malformed identity/financial fields, stale timestamps, recovered IDs and terminal completeness with retained/earlier fills. The existing missing-link regression and all 82 prior Stage 10.5 tests are preserved. Stage 10.5 **90**, RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.6 **68**, EMA **16** pass; full suite **1,993 (1,985 + 8)** passes with zero failures/errors/skips. `pip check`, `git diff --check` and `git diff --staged --check` pass.

Only Stage 10.5 production/tests and current documentation change. Public APIs, schema, RuntimeStore, state machine, both Stage 10.3 corrections, Stage 10.4, Stage 9, Decision 017, notebooks/data/dependencies and frozen financial/timing behavior remain unchanged. No credentials, actual broker request, order or cancellation. The correction is COMPLETE for owner review; Stage 10.5 remains **NOT FROZEN**, Stage 10 INCOMPLETE and Stage 10.6 NOT STARTED.

### Runtime action planner and explicit Demo sizing — Stage 10.6

Starting baseline: clean `main` at `757682038f2a5686e5d45e98dda378e91901b392`. Stage 10.5, including its exact-execution correction, is owner-reviewed and FROZEN. Only `runtime/planner.py`, `tests/test_runtime_planner.py` and current documentation are added/changed; all earlier production/tests, Decisions 001–017, schema, notebooks, data/results and dependencies are preserved.

Public API, imported explicitly from `trading_lab.runtime.planner`:

```python
class PlannerError(ValueError): ...
class PlanKind(str, Enum):  # NOOP, PLACE_BUY, PLACE_SELL, WAIT, RECONCILE, HALT
    ...
class DecisionMode(str, Enum):  # LIVE, BOOTSTRAP, REPLAY_ONLY
    ...
CanonicalDecision(symbol, timeframe, candle_open_ms, input_fingerprint,
                  signal, desired_position, available_at_ms)
ActionPlan(kind, decision=None, action=None, events=(), reason=None)
plan_action(
    config: RuntimeConfiguration,
    checkpoint: RuntimeCheckpoint,
    decision: CanonicalDecision,
    *,
    evaluated_at_ms: int,
    mode: DecisionMode,
    action_history: tuple[ActionRecord, ...],
) -> ActionPlan
```

The two new records are frozen/slotted. Canonical decisions reuse frozen DecisionRecord validation without assigning a disposition/action prematurely. ActionPlan carries a complete DecisionRecord when a candle may be handled, an optional matching PREPARED ActionRecord, an ordered immutable tuple of frozen RuntimeEvents and an optional safe RuntimeReason. Control refusals (unavailable/already handled candles, consumed actions, RECONCILE or latched shutdown/HALT) can have no decision row. No checkpoint values are advanced or changed; validation reconstructs equal records without modifying inputs.

State precedence: HALTED/STOPPING refuse with HALT and no rearm/event; STARTING/SYNCHRONIZING/UNCERTAIN return RECONCILE; ORDER_PENDING returns WAIT and never another action. In confirmed FLAT/LONG, fresh matching desired intent is NOOP, an eligible LONG_ENTRY from FLAT is PLACE_BUY, and an eligible LONG_EXIT from LONG is PLACE_SELL. Live HOLD/owned-state mismatches HALT. Historical BOOTSTRAP/REPLAY_ONLY never create actions and retain their matching dispositions; pending historical evaluations remain WAIT with the historical disposition. Missing/stale reconciliation blocks even historical handling in FLAT/LONG. NO_CHANGE proposals preserve holdings/pending identity while carrying latest desired intent. A journaled fatal live decision supplies NO_CHANGE followed by FATAL_INCONSISTENCY so its final proposed HALT retains the new intent required by the frozen store. Tests commit the final checkpoint atomically, not an intermediate operational state.

BUY authorization is **exact `config.buy_quote_budget` / QUOTE / `config.quote_currency`**. SELL is **exact confirmed `owned_base_quantity` / BASE / `config.base_currency`**. No pre-rounding, wallet/equity/price input, fraction, fee reserve, sizing callback or Stage 7 policy. Stage 9.5 alone later fetches rules and normalizes submission downward; `submitted_amount`, broker IDs/receipts/status remain absent in these PREPARED records. No dust retry or cancellation is planned.

Causal availability is candle open + 3,600,000 ms. Evaluation is explicit integer UTC milliseconds: availability equality is eligible; earlier evaluation returns WAIT without a decision. Decision age and both checkpoint reconciliation/observation ages accept equality with the configured maximum; one ms beyond blocks placement. Future reconciliation/observation timestamps HALT. Stale satisfied intent is REPLAY_ONLY; stale unmatched live intent HALTs, without catching up. Durable bootstrap/replay cutoffs cannot be overridden by LIVE. Already handled candles return WAIT without a new row; missing contiguous history returns RECONCILE. New action deadline is **available_at_ms + reconciliation_timeout_ms**, independent of evaluation time, and evaluation at/after that deadline cannot authorize. Round/read budgets are copied exactly from configuration.

Canonical identity bytes are UTF-8 JSON with sorted keys, compact separators and ensure_ascii=True, exactly:

```json
{"action_kind":"ENTRY","authorized_amount":"<serialize_decimal(amount)>","candle_open_ms":0,"configuration_digest":"<sha256>","instance_key":{"account_binding":"<label>","bot_id":"<bot>","broker_id":"bybit-demo"},"runtime_contract_version":1,"side":"BUY","unit":"QUOTE"}
```

EXIT substitutes EXIT/SELL/BASE and exact owned amount. Full ID is `sha256(encoded).hexdigest()`; link is `bot_id + "-" + id[:23]` (maximum 36 characters). No evaluation time, fingerprint, wallet, price, normalized amount or process/repository data enters this encoding. The golden ENTRY example uses budget 10.123456789, candle 0, digest `b` × 64 and instance research/bot1/bybit-demo: SHA256 **7ad9ceb690c4a52e25b96d6c3408489f66924eb1ed05e002e9f1358e8c216b20**, link **bot1-7ad9ceb690c4a52e25b96d6**.

Caller supplies immutable complete relevant history; no store lookup occurs. Conflicting full IDs, truncated links, same-candle placement IDs, incompatible original intent/deadline and inconsistent unresolved work HALT. Cancellation IDs share the consumed-ID protection. Exact compatible historical actions return WAIT without new authorization, irrespective of their phase; IDs and budgets are never replaced/reset. Repeated identical fresh inputs and later evaluation within the eligible window produce identical action/decision/event records.

Validation: **79 new offline tests**, including **32 state/intent matrix cases**, golden bytes/SHA/link, exact sizing, timing/freshness boundaries, historical/pending behavior, collisions/consumed IDs, input/result preservation and purity. Three temporary-store round trips verify BUY, SELL and journaled HALT through unchanged public commit_decision()/reopen behavior; production imports no RuntimeStore and performs no store operation. Frozen Stage 10.5 **90**, RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.5 **76**, Stage 9.6 **68**, EMA **16** pass. Full suite **2,072 (1,993 + 79)** passes with zero failures/errors/skips; `pip check`, `git diff --check` and `git diff --staged --check` pass.

No broker/account/wallet/metadata/market-data read, credential/env access, mutation adapter, order/cancel/attempt dispatch, strategy calculation, scheduler, runtime loop or Stage 10.7 orchestration exists. Planning produces data only. Stage 10.6 COMPLETE/ready for owner review; Stages 10.1–10.5 FROZEN, Stage 10 INCOMPLETE, Stage 10.7 next/NOT STARTED.

### Stage 9.5 crash-consistent pre-submit hook correction

Current status: owner-reviewed and **FROZEN at `77a88fe1b1250cabde6a1a6fa4aa492db056084b`**. The completion record below retains its original review status and test totals; Stage 10.7 uses the frozen hook without changing it.

Separate owner-approved correction against clean `main` at `6865a1e38b91ab3519fe5b84e4864a59db5ff8bd`; no Stage 10.7 implementation. The original placement method combined safe metadata/amount preflight with mutation. Marking ATTEMPT_STARTED before method entry could therefore leave a provably unsent preflight failure recorded as attempted; frozen storage permits ABANDONED_UNSENT only from PREPARED and REJECTED only with a real broker rejection code.

Additive API:

```python
place_market_order(
    self,
    request: SpotMarketOrderRequest,
    *,
    before_submit: Callable[[], None] | None = None,
) -> SpotMarketOrderAcknowledgement
```

Ordering: request/hook type, symbol/side/unit/link validation → Demo guard → one fresh Stage 9.3 metadata fetch/identity/status validation → unchanged amount normalization/constraints → exact fixed Spot MARKET parameters → final pre-submit Demo guard → optional zero-argument callback exactly once → dispatch Demo guard → at most one place_order → acknowledgement parsing.

All safe preflight failures precede the callback and make zero placements. Callback exceptions propagate unchanged, with no send, acknowledgement parse or retry. Successful callback return means only readiness for a possible send; it supplies no broker ID, submitted amount, acceptance or fill. The adapter has no RuntimeStore/state/planner/SQLite dependency. Existing no-hook callers retain one metadata fetch, at most one placement, unchanged receipts/error classes, exact caller link and no retry. Cancellation is unchanged.

The dispatch guard remains after callback return so the callback cannot enable unsafe routing/retries/logging. A safety refusal there is **after the caller's durable attempt boundary**: future runtime recovery must conservatively retain attempted/uncertain evidence, never treat it as a PREPARED-safe failure or automatically resend. No additional metadata/amount preflight follows successful callback return. Broker nonzero retCode remains confirmed rejection; malformed acknowledgement remains parsing/unknown outcome; transport/SDK failure remains ambiguous.

Validation: **29 new offline tests** (**24 adapter cases + 5 temporary-store proofs**); complete Stage 9.5 **100 (76 + 24)**, Stage 9.6 **68**, Stage 10.6 **79**, Stage 10.5 **90**, RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, EMA **16**, full suite **2,101 (2,072 + 29)** pass with zero failures/errors/skips. `pip check` and both diff checks pass. One existing signature assertion is updated for the approved keyword-only addition; no other prior test is changed.

The real temporary-store integration commits planner-generated PREPARED work first. Its callback calls frozen start_attempt(); the fake placement observes committed ATTEMPT_STARTED/attempt_count=1 through both the store and a separate SQLite reader, with no writer transaction active. Commit failure prevents send and preserves PREPARED; indeterminate post-commit failure prevents send and retains the attempted marker on reopen. Safe metadata/constraint failures leave PREPARED; a post-callback safety refusal retains ATTEMPT_STARTED. Tests do not persist receipts, reconcile, or implement an operational send workflow.

Runtime/store/state/planner/reconciliation, schema v1, locking, Stage 10.4, Decisions 001–017, Stage 9.4/cancellation, strategies/backtests/financial timing, notebooks/data/results and dependencies are unchanged. No credentials, actual broker request, order/cancellation or manual Demo smoke occurred. Stage 9 remains COMPLETE/FROZEN except this correction pending review; Stages 10.1–10.6 remain FROZEN. Stage 10.7 BLOCKED / NOT STARTED until review/freeze and separate authorization; Stage 10 INCOMPLETE; Stage 10.8 and later NOT STARTED.

### Single-cycle Demo runtime orchestration — Stage 10.7

Current status: owner-reviewed and **FROZEN at `728bf6d74d38f5f686f738c71bbf34048e032619`**, including the correction. The completion record below retains its original test totals. Stage 10.8 uses this cycle unchanged.

Starting baseline: clean `main` / `origin/main` at `77a88fe1b1250cabde6a1a6fa4aa492db056084b`. Stage 9 plus its pre-submit correction and Stages 10.1–10.6 are owner-reviewed/FROZEN. Only `runtime/cycle.py`, `tests/test_runtime_cycle.py` and current documentation are added/changed.

The separate correction for the owner review findings starts from published `e6c7b6817404eeaf672cc158b7afae7ea5759a7f`. It changes only the cycle, its tests and current documentation; frozen contracts remain unchanged.

Explicit `trading_lab.runtime.cycle` API:

```python
class CycleError(ValueError): ...
class CycleOutcome(str, Enum):
    # BOOTSTRAP, REPLAY_ONLY, NO_NEW_DATA, NOOP, WAIT, RECONCILE,
    # HALTED, STOPPING, OBSERVED, ABANDONED_UNSENT
    ...
SingleCycleResult(checkpoint, outcome, processed_candle_open_ms=(), planner_kind=None,
                  logical_action_id=None, broker_order_id=None, new_execution_ids=(), reason=None)
run_single_cycle(
    store: RuntimeStore,
    market_reader,
    broker: ReadOnlyBroker,
    order_adapter: BybitDemoOrderAdapter,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
) -> SingleCycleResult
```

The result is frozen/slotted, with processed_candle_count derived from its immutable timestamp tuple. It exposes only durable checkpoint/outcome/planner/action facts, new execution IDs and fixed reasons. Broker order ID is exposed only with a durably acknowledged receipt; lost-ack discovery does not invent one. OBSERVED means a bounded round completed, not necessarily a fill or terminality. CycleError has fixed diagnostics; persistence errors stop execution for reopen/recovery.

Ordering: **reconcile_startup → public closed prefix → unchanged EMA + canonical validation → planner → atomic decision/PREPARED/frontier commit → Stage 9.5 metadata/normalization → callback rechecks timing and commits ATTEMPT_STARTED → at most one placement → durable ACKNOWLEDGED/UNKNOWN_OUTCOME/REJECTED → at most one post-send reconciliation round**. Initial HALTED/STOPPING return without market/decision/action; unresolved UNCERTAIN/SYNCHRONIZING return safe evidence without planning. Every external call is outside SQLite transactions. Resources are injected and caller-owned; no lock/store/session/adapter construction or credential access.

The reader receives exact configured symbol/timeframe/history anchor and **max_data_age_ms = config.decision_max_age_ms**. Only a complete revalidated ClosedCandlePrefix is accepted; no sorting, repair, forming candle or partial-history fallback. Both authoritative public timestamps must lie within the explicit UTC interval of the market read, expanded by max_clock_skew_ms. This distinguishes pagination latency from clock skew. Newest-candle freshness reuses Stage 10.4. Observations use integer UTC milliseconds with explicit microsecond flooring, matching frozen reconciliation; no hidden datetime.now().

StaleMarketDataError, locally stale prefixes and missing/transient/empty market observations persist frozen FRESHNESS_LOST from FLAT/LONG to SYNCHRONIZING, retaining exact exposure as LAST_KNOWN and inventing no pending lifecycle. ORDER_PENDING retains its safe existing state because that event is invalid there. Integrity/configuration contradictions still HALT; ordinary market timeouts do not. The next invocation reconciles before planning again.

CandleRecord OHLCV remains exact Decimal. Fingerprint bytes are sorted compact ASCII-escaped UTF-8 JSON with exactly candle_open_ms, close, high, low, open, symbol, timeframe and volume; OHLCV strings use serialize_decimal. SHA256 is the full lowercase hex digest. Golden bytes:

```json
{"candle_open_ms":0,"close":"105.25","high":"110","low":"90","open":"100","symbol":"BTCUSDT","timeframe":"60","volume":"1.23456789"}
```

Golden SHA256: **c51b1a702fd5f7270194b8f349d0e955895853a59bc17ae0190f7f2aebde67bd**. Decimal scale equivalence preserves identity; observation times, indicators, signals and account facts are excluded. Float conversion occurs only for close values entering the existing EMA20/50/50 strategy. Existing pure Decision-010 validate_strategy_output checks exact row/index/timestamp/availability and integer signal/desired-state transitions; no backtest execution/fills. Every retained candle and canonical decision must reproduce before the frontier advances; disagreement HALTs without rewriting history.

Fresh initialization reserves bootstrap_until_ms through the initial prefix before any decision commit. Restart never extends that reserved bootstrap range, even if no decision committed. Additional missed candles beyond it reserve replay_until_ms before catch-up commits. Each candle is classified separately: through bootstrap_until_ms → BOOTSTRAP; beyond bootstrap and through replay_until_ms → REPLAY_ONLY; only a genuinely future contiguous candle beyond both cutoffs may be LIVE. For a crash after candle 10 with bootstrap reserved through 49 and a later prefix through 55, candles 11–49 remain BOOTSTRAP and 50–55 are REPLAY_ONLY. Neither historical mode trades. Every decision uses public list_actions() and the frozen planner; ordered events are applied unchanged through transition_runtime_state. ORDER_PENDING decisions remain WAIT and may update desired intent without queuing/replacing/cancelling. Exact commit replay returns without invoking the adapter.

The final pre-submit callback samples fresh injected integer UTC milliseconds before start_attempt and requires **submit_ms >= decision.available_at_ms**, **submit_ms - decision.available_at_ms <= config.decision_max_age_ms**, and **submit_ms < action.reconciliation_deadline_ms**. Process-local flags are **callback_entered**, **pre_submit_timing_accepted**, **start_attempt_call_begun**, and **attempt_commit_returned**. Callback entry alone is not a persistence attempt; no schema or public API changes.

| Boundary / outcome | Durable behavior |
| --- | --- |
| Decision/PREPARED commit failure | Stop; no adapter invocation. |
| Adapter fails before callback entry | ABANDONED_UNSENT/count 0; exact terminal-action evidence clears pending to unchanged FLAT/LONG exposure. ID stays consumed. |
| Known timing refusal before invoking start_attempt | ABANDONED_UNSENT/count 0 via public store and exact terminal-action clearing event; exposure unchanged, ID consumed, zero placement. |
| Callback clock/read failed before start_attempt | Stop without further reads/writes/abandon/send; do not fabricate a known timing refusal. |
| start_attempt invoked, did not return successfully | No further read/write/abandon/send; safe persistence error. Reopen discovers PREPARED or committed ATTEMPT_STARTED. |
| Valid receipt after successful attempt commit | Validate identity/unit/exact amount/UTC timing; persist ACKNOWLEDGED with no fills/status/terminality; quantity unchanged. |
| Confirmed nonzero broker rejection | Persist exact bounded code and REJECTED/count 1; clear pending, then HALT with INCONSISTENT_EVIDENCE. No code is assumed harmless. |
| Ambiguous/malformed receipt or post-callback safety refusal | UNKNOWN_OUTCOME/count 1 and ACTION_OUTCOME_UNKNOWN uncertainty; retain original pending identity, no invented receipt/amount/ID. |
| Receipt/outcome persistence failure | Stop before post-send reads; no memory-based repair/resend. Attempt/possibly committed receipt remains reopen evidence. |

After successfully persisted ACKNOWLEDGED or UNKNOWN_OUTCOME, one frozen reconciliation call consumes actual order/fill evidence and may end ORDER_PENDING, LONG, FLAT, UNCERTAIN or HALTED. OPEN/partial fills stay pending; complete actual fills determine exposure. A FILLED SELL can retain a positive remainder or HALT on oversold inventory. Lost-ack discovery preserves missing receipts. No polling, sleep, retry, second ID or second placement.

Validation: **97 offline tests (78 original + 19 correction regressions)**; placement-boundary **29 (24 adapter + 5 integration)**, Stage 9.5 **100**, Stage 9.6 **68**, Stage 10.6 **79**, Stage 10.5 **90**, RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, EMA **16**, full suite **2,198 (2,179 + 19)** pass with zero failures/errors/skips; pip check and both diff checks pass. Fakes check the real temporary SQLite transaction flag at every external boundary. Correction tests cover early/mixed/bootstrap-before-first-commit crashes, interrupted replay, first future LIVE candle, inclusive decision-age/exclusive deadline boundaries after metadata delay, expired SELL exposure, regressing clock refusal, durable FLAT/LONG freshness loss and reconciliation before replanning. Existing crash/receipt/unknown/no-resend tests remain unchanged.

Frozen runtime/Stage 9/market gate/strategy/validator/schema/Decisions 001–017, notebooks/data/results/dependencies and financial/next-OPEN regressions are unchanged. No real credentials/session/authenticated request/Demo order/cancellation/manual run. No scheduler/Stage 10.8, automatic cancellation, wallet sizing or Stage 7/backtest fill orchestration. Explicit operator cancellation needs a separate owner-approved API contract. Stage 10.7 and its correction are now COMPLETE/FROZEN at `728bf6d`. Stage 10 was incomplete at milestone completion; later milestones and the final audit are recorded below.

### Long-running candle scheduler — Stage 10.8

Current status: COMPLETE/FROZEN at `f3e9fe6bb9770031c121314c67e4177d0299e095`. The completion record below retains its original test totals.

Starting baseline: clean `main` / `origin/main` at `728bf6d74d38f5f686f738c71bbf34048e032619`. Stage 9 with all approved corrections and Stages 10.1–10.7 are owner-reviewed/FROZEN. Only new `runtime/scheduler.py`, `tests/test_runtime_scheduler.py` and current documentation change.

Explicit `trading_lab.runtime.scheduler` API:

```python
class SchedulerError(RuntimeError): ...
class SchedulerExit(str, Enum):
    STOP_REQUESTED = "STOP_REQUESTED"
    HALTED = "HALTED"
    STOPPING = "STOPPING"
SchedulerResult(checkpoint, exit_reason, cycle_count, wake_count, last_cycle=None)
run_hourly_scheduler(
    store: RuntimeStore,
    market_reader,
    broker: ReadOnlyBroker,
    order_adapter: BybitDemoOrderAdapter,
    stop_signal,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
) -> SchedulerResult
```

The result is frozen/slotted and contains only final durable checkpoint, exit enum, invocation/wake counts and the last normalized SingleCycleResult. cycle_count includes startup/retry invocations; wake_count counts due hourly batches, excluding startup/retries. No session, raw payload/exception, secret or DataFrame is exposed. No test-only run-duration/count arguments exist.

The caller supplies already-created locked store, market reader, normalized broker, action adapter and an event-like stop object with **is_set() -> bool** and **wait(timeout_seconds) -> bool**. Structural compatibility includes threading.Event; the scheduler constructs no event/thread or signal handler. Missing methods, nonboolean results and control-clock failures raise fixed SchedulerError. UTC must be aware with zero offset and within the nonnegative integer millisecond range; microseconds explicitly floor through integer arithmetic. Injected finite real monotonic and UTC observations must never regress.

Flow: **immediate startup cycle → reserved absolute next UTC-hour boundary → interruptible wait → serialized frozen cycle → at most two safe retries (1s, 2s) → next absolute UTC boundary**. Every invocation forwards the exact resources/clock callables to frozen run_single_cycle. No direct broker/market/action calls or action/decision/fill inspection; no strategy, sizing, planner or reconciliation logic is copied.

The first target is reserved before startup work using **(utc_ms // config.interval_ms + 1) * config.interval_ms**, with frozen interval 3,600,000. A startup cycle crossing that target triggers one immediate due batch. If startup/scheduled work spans several hours, there is one catch-up invocation/batch, never one callback per missed hour. After a scheduled batch, jump arithmetically to the first boundary strictly after current UTC. No finish-plus-one-hour drift or local/DST/calendar scheduling. Early/spurious waits recheck clocks and wait the remainder; they never license an early cycle. Only frozen Stage 10.4/10.7 prove closure/freshness and handle anchored historical replay.

Retry is limited to normally returned **WAIT / RECONCILE / NO_NEW_DATA** with **EVIDENCE_MISSING / ACTION_OUTCOME_UNKNOWN**; frozen cycle semantics guarantee these paths dispatched no new placement. Each startup/wake batch has **at most three total attempts**, fixed **1s then 2s** interruptible backoff, and one original monotonic elapsed window bounded by **config.reconciliation_timeout_ms**. Backoff and retry starts must fit that budget, including equality; it never resets per attempt. Scheduled retries must also fit **utc_ms - scheduled_boundary_ms <= config.decision_max_age_ms**, checked before backoff and again before retry. In-flight cycles cannot be interrupted. Spurious backoff returns wait the remaining monotonic delay.

No immediate retry for **OBSERVED, ABANDONED_UNSENT, NOOP, BOOTSTRAP, REPLAY_ONLY, HALTED or STOPPING**, a pending WAIT without a transient reason, or a permanent reason. No automatic order/fill polling, adapter/page retries, placement resend or special uncertain-action recovery. Every exception from run_single_cycle propagates unchanged: no retry/wait, broker read, finally/shutdown write, local repair, close or release. The scheduler contains no restart normalization; caller-owned process entry belongs to separate Stage 10.9.

An already-set stop skips startup. Stop during boundary wait/backoff prevents the next cycle; stop during a normally returning cycle is handled after that bounded call, before any retry/wake. Ordinary stop loads the public checkpoint; unless already STOPPING, apply frozen **SHUTDOWN_REQUESTED**, preserve all unrelated fields, increment sequence once, set **shutdown_at_ms** from explicit UTC, and public **save_checkpoint(..., expected_sequence=old_sequence)**. Exact owned quantity, pending action, desired intent, uncertainty/HALT reason, halted_at_ms and stopped_from are retained; known exposure becomes LAST_KNOWN, unknown stays unknown. No cancellation, SELL/liquidation, pending clearing or false FLAT claim. Store write errors propagate without another attempt.

HALTED without an operator stop exits as HALTED without rearm/shutdown conversion. Existing STOPPING exits as STOPPING without cycle/wait/write. A stop request takes precedence and returns STOP_REQUESTED, preserving an existing STOPPING checkpoint without another transition. The caller closes session/store and releases the lock last; scheduler constructs/destroys none. There is no CLI, credential/env loader, session construction, real broker run, daemon or deployment.

Validation: **79 new offline scheduler tests**, including fake clocks/stop scripts, exact timing/budget limits, spurious wakes, exception no-follow-up proofs, six durable shutdown states, published frozen-source hashes, AST boundary guards and two real frozen-cycle integrations with synthetic broker/session responses. Stage 10.7 **97**, Stage 10.6 **79**, Stage 10.5 **90**, placement boundary **29**, Stage 9.5 **100**, Stage 9.6 **68**, RuntimeStore **211**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, EMA **16**, full suite **2,277 (2,198 + 79)**, pip check and both diff checks pass with zero failures/errors/skips.

At Stage 10.8 completion: COMPLETE/ready for owner review/freeze; Stage 10 INCOMPLETE; Stage 10.9 next/NOT STARTED. All frozen source/tests/APIs/schema/Decisions 001–017, next-OPEN/financial regressions, notebooks/data/results and dependencies remained unchanged. No credentials, actual authenticated Demo request/order/cancellation or activation occurred.

### Stage 10.3 / RuntimeStore additive restart-validation correction

Current status: owner-reviewed and FROZEN at `a22199f9abd1ce2484aa6dbde500ad126cb66b21`. The completion record below retains its original test totals and scope.

Starting baseline: clean `main` / `origin/main` at `f3e9fe6bb9770031c121314c67e4177d0299e095`. Owner approval covers only the store validation correction, focused tests and documentation; Stage 10.9 recovery is not implemented.

`RuntimeStore._validate_relations()` previously allowed durable UNKNOWN_OUTCOME in SYNCHRONIZING, UNCERTAIN, HALTED or STOPPING, plus the strict observed ORDER_PENDING exception. Its general allowance now also includes STARTING. This single-condition change permits a future new process to persist nonconfirmed STARTING while retaining unresolved original action evidence. STARTING does not resolve the action or license mutation; frozen reconciliation remains responsible for recovery.

FLAT/LONG still reject unresolved unknown actions. The observed ORDER_PENDING exception, exact pending ID/kind, one-unresolved-placement guard, decision/link/broker/fill ownership, cancellation-parent binding, configuration identity, contiguous frontier, deadlines, recovery budgets and HALT latch remain unchanged. No automatic state transition, action conversion/abandonment, counter reset/decrement, broker query or recovery API is added. Public APIs, enums/state transitions, schema version 1, Decimal storage, SQLite durability, checkpoint CAS, action phase graph and single-instance lock are unchanged. Existing valid Stage 10.3 databases remain readable without migration.

**19 new offline store regressions** include real temporary SQLite **close → release lock → acquire a new canonical lock → RuntimeStore.open(initialize=False)**. STARTING preserves exact checkpoint/action/fill/history records and database bytes with zero, positive partial-fill or unknown owned quantity, missing receipt fields, original IDs, exhausted/nonexhausted budgets and deadlines. Valid subordinate UNKNOWN_OUTCOME cancellation evidence also survives; invalid pending identities, a second placement, cancellation rebinding, new attempt/cancellation, budget resets and HALT clearing still fail atomically.

Validation: correction **19**, complete RuntimeStore **230 (211 + 19)**, Stage 10.5 **90**, Stage 10.7 **97**, Stage 10.8 **79**, Stage 10.6 **79**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.5 **100**, placement boundary **29**, Stage 9.6 **68**, frozen EMA **16**, full suite **2,296 (2,277 + 19)**; zero failures/errors/skips. `pip check`, `git diff --check` and `git diff --staged --check` pass. The scheduler test's store-source hash and explanatory comment are refreshed for the approved change; scheduler production code, assertions and 79-test count are unchanged. Other frozen production/tests, Decisions 001–017, financial/next-OPEN behavior, notebooks/data/results and dependencies are preserved. No credentials, actual broker request/order/cancellation or Demo activation occurred.

At correction completion: COMPLETE for owner review/freeze; Stages 10.1–10.8 FROZEN; Stage 10.9 BLOCKED until correction review/freeze, with no recovery implementation. Stage 10 remained INCOMPLETE and Stage 10.10 NOT STARTED. The correction is now FROZEN; Stage 10.9 is recorded separately below.

### Restart / crash / ambiguous-action recovery — Stage 10.9

Starting baseline: clean `main` / `origin/main` at `a22199f9abd1ce2484aa6dbde500ad126cb66b21`. Stages 10.1–10.8, the RuntimeStore restart-validation correction and approved Stage 9 corrections are FROZEN. Only new `runtime/recovery.py`, `tests/test_runtime_restart_recovery.py` and current documentation change; no old test expectation needs updating.

Import explicitly from `trading_lab.runtime.recovery`:

```python
class RestartRecoveryError(RuntimeError): ...
prepare_process_restart(store: RuntimeStore) -> RuntimeCheckpoint
```

This small process-entry boundary accepts an already-open existing store and uses only public `get_checkpoint()` and at most one `save_checkpoint(proposed, expected_sequence=current.sequence)`. No broker/market/adapter/scheduler argument, implicit clock, loop, private store access, SQL, action read/write, phase change, budget decrement/reset, resource construction or corruption repair exists. Persistence errors propagate unchanged with no second read/write/retry; reopen determines old/new durable truth. Invalid store input raises fixed RestartRecoveryError.

| Durable state | Process-entry result |
| --- | --- |
| STARTING | Exact checkpoint unchanged; no write or sequence increment. |
| SYNCHRONIZING | STARTING; retained quantity becomes LAST_KNOWN, or UNKNOWN for None. |
| FLAT | STARTING with exact zero / LAST_KNOWN; fresh reconciliation must prove FLAT again. |
| LONG | STARTING with exact positive quantity / LAST_KNOWN; no second BUY. |
| ORDER_PENDING | STARTING with exact pending ID/kind and LAST_KNOWN exposure. |
| UNCERTAIN | STARTING with LAST_KNOWN/UNKNOWN exposure; only snapshot reason is cleared. |
| HALTED | Exact checkpoint/latch unchanged; no write, rearm or broker call. |
| STOPPING from a non-HALTED state | STARTING; consume shutdown marker and clear stopped_from/reason. |
| STOPPING from HALTED | HALTED; consume shutdown marker, retaining exact reason/halted_at_ms. |

Every changed checkpoint advances sequence exactly once. Exact quantity, desired intent, pending action, frontier, reconciliation/observation times, coverage, rearm timestamp and bootstrap/replay cutoffs survive. STARTING has no halted/shutdown marker; retained HALTED keeps the original halted timestamp. Action/link/broker IDs, origin candle, side/unit/authorization/kind, fills, original recovery counters and deadline are untouched. No PROCESS_RESTARTED event or frozen transition change is added.

Canonical activation order:

```text
process N: crash / graceful STOPPING → process exits
process N+1:
  acquire canonical RuntimeAccountLock
  → RuntimeStore.open(..., initialize=False)
  → prepare_process_restart(store)
  → construct caller-owned external resources
  → frozen reconciliation / run_single_cycle / run_hourly_scheduler
  → only a genuinely future eligible decision may authorize a new order
```

Call preparation only at new-process entry, before any trading in that process; it is not a reset button. **Restart never resends an unresolved action.** Frozen reconciliation retires PREPARED as ABANDONED_UNSENT, retaining its ACTION decision/frontier/consumed IDs. ATTEMPT_STARTED conservatively becomes UNKNOWN_OUTCOME even if the old process died before sending. Exact-link/order observations recover OPEN/partial/final evidence without fabricating receipts. Missing history remains uncertain until retained finite budgets/deadline HALT with RECOVERY_EXHAUSTED. No restart extends a deadline or restores tokens.

**89 new offline tests** cross real temporary SQLite close/release/new-lock/open(initialize=False) boundaries. Crash A–H cover rolled-back PREPARED transactions, committed unsent intent, attempted-before-send, lost ACK, retained ACK, partial/deduplicated/new/conflicting fills, durable UNKNOWN_OUTCOME and terminal commits whose return was lost. Terminal LONG survives an empty newer execution window; FILLED SELL zero/remainder remains FLAT/LONG respectively. Rejected/HALT and subordinate cancellation evidence, opposite pending intent, original historical cutoffs and ownership conflicts remain safe. Missing/corrupt/config-mismatched/schema-invalid stores fail without initialization/repair/migration. Failed/indeterminate preparation commits and CAS conflicts propagate without follow-up activity; a second restart of committed STARTING is idempotent.

Real frozen-cycle proofs include PREPARED, ATTEMPT_STARTED, lost-ACK OPEN/FILLED and terminal/partial cases. Real frozen scheduler proofs exhaust original ATTEMPT_STARTED/UNKNOWN_OUTCOME budgets without resend, plus graceful pending shutdown/restart. Placement and cancellation guards assert no invocation on recovery paths. Network, credential lookup and real sleep are blocked; all broker observations/mutations are synthetic test fixtures only.

Validation: Stage 10.9 **89**, RuntimeStore **230**, Stage 10.8 **79**, Stage 10.7 **97**, Stage 10.6 **79**, Stage 10.5 **90**, locking **23**, Stage 10.2 **188**, Stage 10.4 **97**, Stage 9.4 **123**, Stage 9.5 **100**, placement boundary **29**, Stage 9.6 **68**, frozen EMA **16**, full suite **2,385 (2,296 + 89)**; zero failures/errors/skips. `pip check` and both diff checks pass. All frozen production/tests, public APIs/schema, Decisions 001–017, financial/next-OPEN behavior, notebooks/data/results and dependencies are unchanged. No credentials, real network request, authenticated Demo session/order/cancellation, launch layer or Stage 10.10 work.

Stage 10.9 is owner-reviewed and FROZEN at `fef6b6ee4a8d4fceb9526ed1e3bc1705fda6b7d5`. Its completion results above retain their original totals. Stage 10 was incomplete at milestone completion; offline integration and the final audit are recorded below. No Demo activation is authorized.

### Runtime integration regression — Stage 10.10

Current status: independently owner-reviewed and FROZEN at `329252658aa703b90f107d862e34dbabd81f0f64`. The completion record below retains its original 58-test / 2,443-total results. The separately approved read-failure correction is documented after it.

Starting baseline: clean `main` / `origin/main` at `fef6b6ee4a8d4fceb9526ed1e3bc1705fda6b7d5`. Scope: **OFFLINE integration regression only**. Added `tests/test_runtime_integration_regression.py`; zero production changes, new public APIs, schema/dependency changes or activation scripts. Stages 10.1–10.9, approved store/Stage 9 corrections, Decisions, existing tests, next-OPEN financial behavior, notebooks and data remain FROZEN and byte-identical.

The real canonical account lock, RuntimeStore, process restart preparation, hourly scheduler, cycle, bounded reconciliation, public closed-candle parser, EMA strategy, planner, Stage 9.3 normalization and Stage 9.4/9.5 adapters run together. Only public HTTP/SDK responses, UTC/monotonic clocks and stop events are synthetic. Each scenario uses a temporary registry, closes the store before releasing its lock, and creates new resources for process restart. Explicit guards block sockets, real requests/pybit sends, credential/session factories, environment credential lookup and wall-clock sleep. Private connection access only observes transaction state; labeled fault injection simulates durability failures/crashes.

Golden lifecycle:

```text
STARTING → SYNCHRONIZING → FLAT → ENTRY ACTION → ORDER_PENDING
→ LONG → HOLD wakes → EXIT ACTION → ORDER_PENDING → FLAT
→ STOPPING(FLAT) → close/release/new lock/open(initialize=False)
→ STARTING/LAST_KNOWN → reconciliation → FLAT
```

Exactly **54 contiguous hourly candles** (open times `0` through `190800000` ms), **54 decisions**, **2 placement actions**, **2 executions**, **0 CANCEL actions** and **0 cancellation sends**. Fifty candles are BOOTSTRAP, with cutoff `176400000` ms. LIVE entry opens at `180000000` ms / available at `183600000`; two HOLD wakes follow; LIVE exit opens at `190800000` / available at `194400000`. The frozen EMA output equals every durable signal/desired-position record. Reopen retains history without reauthorizing an originating candle.

| Exact synthetic golden record | ENTRY | EXIT |
| --- | --- | --- |
| Logical action ID | `fc17adafb331e964da8e79112502274620b772ad52ee42c3cfec05f61a86a704` | `349b4d70a2a702ce3f311c1c43bf523b830c193ef9f4a9128d793f4f37dbbb90` |
| Order link | `bot1-fc17adafb331e964da8e791` | `bot1-349b4d70a2a702ce3f311c1` |
| Authorization | `10.123456789` QUOTE USDT | `0.04995` BASE BTC |
| Stage 9 submitted amount | `10.1234567` | `0.04995` |
| Execution ID | `exec-buy-1` | `exec-sell-1` |
| Execution quantity | `0.05` BTC | `0.04995` BTC |
| Execution price | `100.123456789` | `111.123456789` |
| Execution fee | `0.00005` BTC | `0.01` USDT |
| Confirmed owned base afterward | `0.04995` BTC | `0` BTC |

These prices, fees, quantities and metadata limits are test fixtures, not current exchange terms or actual trades. All money assertions use exact Decimal; receipts alone never prove position. A separate rounded SELL case retains exact owned dust `0.0000009` BTC as LONG. Wallet BTC is coverage only, never ownership or sizing.

**58 new tests** cover scenarios A–Z: historical LONG/no-send bootstrap; future BUY/SELL and HOLD; OPEN/partial/final observations and cross-read execution deduplication; graceful FLAT/LONG/pending restart; hidden accepted/missing/malformed acknowledgements; PREPARED, ATTEMPT_STARTED, lost ACK, durable ACK and lost terminal-return crashes; uncertain recovery exhaustion/HALT latch; stale market synchronization; absolute UTC boundaries/crossing/missed-hour replay; bounded 1s/2s safe retries; propagated SQLite failures; duplicate lock refusal; foreign namespace/fill conflicts; six configuration mismatches; missing/corrupt/schema-invalid/journal-invalid activation. Independent golden runs match exact logical records; terminal-commit crash recovery matches uninterrupted economic/identity truth. Selected milestones reopen normally through RuntimeStore. Seventeen source hashes guard frozen production/smoke code. Secret/raw-payload absence and no writer transaction at every external boundary are checked.

Every logical placement has at most one SDK send, including across restarts and ambiguity. This proves exactly one committed logical authorization per candle, **not exactly-once exchange delivery**. No automated cancellation, wallet sizing or historical fill-engine use. The frozen cycle's shared pure strategy-output validator remains unchanged.

Local validation (not CI): Stage 10.10 **58**, Stage 10.9 **89**, RuntimeStore **230**, 10.8 **79**, 10.7 **97**, 10.6 **79**, 10.5 **90**, locking **23**, 10.2 **188**, 10.4 **97**, 9.4 **123**, 9.5 **100**, placement boundary **29**, 9.6 **68**, frozen EMA **16**, all historical/research/backtest tests **982**, full suite **2,443 (2,385 + 58)**; zero failures/errors/skips. `pip check` and both diff checks pass. These groups overlap and are not additive.

At Stage 10.10 completion: offline regression COMPLETE / ready for owner review/freeze; Stage 10 INCOMPLETE; 10.11 next / NOT STARTED. It is now FROZEN at `3292526`. **Optional explicit authenticated Bybit Demo run: NOT PERFORMED / NOT AUTHORIZED.** No real credentials, broker network call, account read, order or cancellation occurred; Git publication is separate. No production launcher or activation capability was added. The subsequent audit blocker and its owner-approved correction are recorded below.

### Owner-approved Stage 10.11 read-failure classification correction

Current status: independently owner-reviewed and FROZEN at `4e947b192d9e2b3be8b9b050917ca9e03a250320`. The completion record below retains its original test totals and review status; the subsequent public market correction is separate.

Starting baseline: clean `main` / `origin/main` at `329252658aa703b90f107d862e34dbabd81f0f64`. The Stage 10.11 audit reproduced malformed-wallet and unsafe-Demo failures becoming EVIDENCE_MISSING, then three scheduler cycles with 1s/2s backoff. This separate owner-approved correction restores Decision 017's permanent/configuration/malformed failure semantics. **The Stage 10.11 audit is not resumed or completed here.**

Additive broker-independent API in `exchange/account_state.py`, also available by explicit package import (the Stage 9.2 wildcard export list is unchanged):

```python
class BrokerReadFailureKind(str, Enum):
    TRANSIENT = "TRANSIENT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    MALFORMED_DATA = "MALFORMED_DATA"
    PERMANENT = "PERMANENT"

BrokerReadError(kind: BrokerReadFailureKind)  # RuntimeError descendant
BrokerReadError.kind                        # immutable enum classification
```

The base exception accepts only the explicit enum and carries a fixed safe message plus immutable classification, without payload/SDK exception/retry policy. Existing BybitDemoReadError remains catchable as RuntimeError and now derives from BrokerReadError; its legacy safe message is preserved and its default kind is PERMANENT. BybitDemoStateParseError remains its subclass and always uses MALFORMED_DATA. BrokerOrderNotFoundError stays separate and unchanged.

| Read failure / evidence | Adapter classification | Reconciliation behavior |
| --- | --- | --- |
| Unsafe Demo/testnet/endpoint/retry/logging settings, at construction or every read | INVALID_CONFIGURATION | HALTED / INVALID_CONFIGURATION; zero SDK requests after guard failure |
| Existing account/order/execution/decimal/timestamp/shape/pagination parse failures | MALFORMED_DATA | HALTED / INCONSISTENT_EVIDENCE |
| Unclassified nonzero retCode | PERMANENT | HALTED / INCONSISTENT_EVIDENCE |
| TimeoutError, ConnectionError, requests.exceptions.Timeout or requests.exceptions.ConnectionError at the SDK transport boundary | TRANSIENT | Nonfatal EVIDENCE_MISSING; frozen bounded scheduler retries remain eligible |
| Arbitrary SDK/HTTP exception | PERMANENT | HALTED / INCONSISTENT_EVIDENCE |
| Unclassified generic ReadOnlyBroker exception, including an unclassified timeout | No trusted classification | HALTED / INCONSISTENT_EVIDENCE |
| BrokerOrderNotFoundError | Separate existing exception | Existing not-observed / unknown-outcome handling |
| Syntactically valid future order status | Valid OrderStatus.UNKNOWN observation, not a read failure | Existing uncertainty handling unchanged |

No numeric code is newly mapped to INVALID_CONFIGURATION; unclassified nonzero codes default PERMANENT. No retMsg/error-message inspection. Diagnostics retain only adapter-authored operation/code/type facts; original SDK text/object/context, headers, signatures, credentials and raw payloads are absent. Transport exceptions are raised outside the SDK catch block so the sanitized exception retains no SDK __context__ or __cause__.

Reconciliation imports only the broker-independent classification. Existing token reservation remains durably before I/O; fatal reads use existing reason/state transitions. Three active-action regressions reach zero remaining read attempts and preserve INVALID_CONFIGURATION or INCONSISTENT_EVIDENCE instead of replacing the cause with RECOVERY_EXHAUSTED. Original action/link, attempt count, deadline and pending identity persist without resend/cancellation. The frozen scheduler exits on HALTED before considering retryability; its source is unchanged.

**30 new focused tests**: 13 adapter/classification, 10 reconciliation, three scheduler and four integration regressions. The two audit reproducers now yield one cycle, HALTED, no backoff, zero placements/cancellations; malformed wallet makes one account read, unsafe configuration makes zero SDK reads. Verified timeouts retain three attempts with 1s/2s waits. Normalized broker fakes now inject explicit TRANSIENT classifications where their original intent was temporary read loss; the post-callback unsafe-configuration assertion is strengthened to HALT while retaining UNKNOWN_OUTCOME/attempt count 1. No tests are removed/skipped/weakened. Source-preservation assertions refresh only the read-adapter hash and the three reconciliation hash occurrences.

The Stage 10.10 golden remains exact: **54 candles/decisions, 2 placements/actions, 2 fills, 0 cancellations**, original action IDs/links and Decimal amounts/fees/owned quantities, including shutdown/restart repeatability. Full local validation: focused **30**, Stage 9.4 **136 (123 + 13)**, 10.5 **100 (90 + 10)**, 10.8 **82 (79 + 3)**, 10.9 **89**, 10.10 **62 (58 + 4)**, RuntimeStore **230**, 10.7 **97**, 10.6 **79**, locking **23**, 10.2 **188**, 10.4 **97**, 9.5 **100**, placement boundary **29**, 9.6 **68**, EMA **16**, historical/research/backtest **982**, full suite **2,473 (2,443 + 30)**; zero failures/errors/skips. `pip check` and both diff checks pass. These groups overlap; no CI result is claimed.

At correction completion, production changes were limited to account_state.py, bybit_demo_read_only.py, reconciliation.py and two additive exports in exchange/__init__.py. Scheduler/state/store/locking/planner/cycle/recovery, Stage 9.5 mutation code, schema v1, Decisions, dependencies, notebooks/data/results and financial/next-OPEN behavior were unchanged. No authenticated Demo read, order, cancellation, real credential access or broker network call occurred. The correction was COMPLETE / pending owner review/freeze, and the audit remained BLOCKED. It is now FROZEN at `4e947b1`; the later public market correction is recorded below.

### Owner-approved Stage 10.11 public market-data error-classification correction

Current status: independently owner-reviewed and FROZEN at `c273a8be3213a1cbeb3fc12271d17618f2d28b94`. The completion record below retains its original scope, test totals and review status; the resumed final audit is recorded separately below.

Starting baseline: clean `main` / `origin/main` at `4e947b192d9e2b3be8b9b050917ca9e03a250320`. The final audit reproduced malformed public `timeNano` and unknown public API code `987654` becoming WAIT/EVIDENCE_MISSING, with three scheduler reads and 1s/2s backoff. This separately approved correction covers only public market classification and the two cycle exception boundaries. **The Stage 10.11 audit is not resumed here.**

`data/closed_candles.py` adds finite `MarketDataReadFailureKind` (TRANSIENT, PERMANENT). The existing `MarketDataTransportError(message="Public market read failed.", *, kind=MarketDataReadFailureKind.PERMANENT)` remains catchable through its existing hierarchy, with immutable `.kind`. Legacy unclassified construction defaults PERMANENT. Existing input/response/integrity/continuity/stale exception classes retain their names and hierarchy.

| Public market failure/evidence | Classification | Cycle / scheduler behavior |
| --- | --- | --- |
| Builtin or requests timeout/connection exception at the actual HTTP GET boundary | TRANSIENT | WAIT/EVIDENCE_MISSING; existing bounded retry eligible |
| Malformed server time, JSON, Kline structure/context/decimal or response envelope | MarketDataResponseError | HALTED/INCONSISTENT_EVIDENCE; no retry |
| Unknown/nonzero public retCode or unverified non-200 HTTP response | PERMANENT | HALTED/INCONSISTENT_EVIDENCE; no retry |
| Arbitrary external transport/response-read exception, or unclassified transport error | PERMANENT | HALTED/INCONSISTENT_EVIDENCE; no retry |
| Unclassified exception from a supplied market reader | Fail closed | HALTED/INCONSISTENT_EVIDENCE; no retry |
| Existing input/integrity/continuity failures | Existing exception classes | Existing HALTED/INCONSISTENT_EVIDENCE behavior |
| Otherwise valid stale data | StaleMarketDataError | WAIT/EVIDENCE_MISSING; existing bounded retry eligible |

No message/retMsg matching, speculative API-code/HTTP retry mapping or new RuntimeReason. Public transport errors retain only fixed adapter-authored messages and the finite classification; original external exception text/object/context/cause, response bodies and environment contents are absent. Errors are raised outside the external catch block with `from None`. Fixed public URLs, `trust_env=False`, `auth=None`, redirects disabled, one attempt per HTTP request and bounded pagination remain unchanged. A later-page permanent/malformed failure returns no partial prefix.

The cycle's initial market read now handles these facts explicitly. Its second freshness-validation boundary waits only on StaleMarketDataError; every other failure HALTs. Fatal failures from FLAT/LONG retain exact LAST_KNOWN ownership; pending orders retain their original action/link/order ID, attempt count, deadline, exposure and fills without resend/cancellation. Scheduler production is unchanged: HALTED exits before retry logic. Verified transport and valid stale-data cases still allow at most three whole-cycle attempts, with 1s then 2s waits under the original bounds.

Both audit reproducers now give **one cycle, HALTED/INCONSISTENT_EVIDENCE, zero waits, one public server-time request, zero Kline requests, zero placements and zero cancellations**. All broker/HTTP observations are synthetic. No real credential/session use, authenticated Demo request or actual broker mutation occurred.

**37 additive focused tests** pass: reader/classification **14**, real-cycle **17**, real-scheduler **4**, integration reproducers **2**. Coverage includes immutable/default classification, sanitized external context, late-page atomicity, both freshness boundaries, fatal FLAT/LONG/partial/open preservation and transient/stale retries. Existing tests/guards remain; two intended temporary cycle fixtures now explicitly use TRANSIENT without changing their assertions. Preservation hashes refresh only closed_candles.py, bybit_public_market.py and cycle.py; the Stage 10.9 test change is hash-only.

The frozen Stage 10.10 golden remains **54 candles/decisions, 2 placement actions, 2 fills, 0 cancellations**, with original logical IDs/links, exact Decimal amounts/fees/owned quantities and shutdown/restart results. The account-read correction at `4e947b1`, scheduler/state/store/locking/planner/reconciliation/recovery, Stage 9.5 mutation code, strategy, schema v1, Decisions, dependencies, notebooks/data/results and financial/next-OPEN behavior are unchanged.

Local validation (not CI), zero failures/errors/skips:

| Suite | Passing tests |
| --- | ---: |
| New focused correction tests | 37 |
| Stage 10.4 / public market + closed candles | 111 |
| Stage 10.7 / cycle | 114 |
| Stage 10.8 / scheduler | 86 |
| Stage 10.9 / restart | 89 |
| Stage 10.10 / integration | 64 |
| Stage 10.5 / reconciliation | 100 |
| Stage 9.4 / account/order reads | 136 |
| RuntimeStore | 230 |
| Stage 10.6 / planner | 79 |
| Stage 10.2 / state | 188 |
| Locking | 23 |
| Stage 9.5 / actions | 100 |
| Placement boundary | 29 |
| Stage 9.6 / integration + smoke controls | 68 |
| Frozen EMA | 16 |
| Historical/research/backtest | 982 |
| Full suite | 2,510 (2,473 + 37) |

Groups overlap. `pip check`, `git diff --check` and `git diff --staged --check` pass. No tests are removed/skipped/weakened. Production changes are limited to the three approved market/cycle files; other frozen source, schema, dependencies, Decisions, strategy and research artifacts are byte-identical to `4e947b1`.

At public market correction completion: COMPLETE / pending independent owner review/freeze; Stage 10.11 remained BLOCKED and Stage 10 INCOMPLETE. No authenticated Demo read/order/cancellation, real credentials or actual broker network was used; Stages 11–15 were NOT STARTED. The correction is now FROZEN at `c273a8b`; the final audit below resumes only after that independent review and explicit owner authorization.

### Final Stage 10 audit — Stage 10.11

Reviewed clean `main` / `origin/main` baseline: `c273a8be3213a1cbeb3fc12271d17618f2d28b94`. Both previously discovered blockers are resolved, independently reviewed and FROZEN. No further material implementation defect was found within the accepted initial scope. **Documentation only: zero production, test, Decision, schema or dependency changes; zero new tests.** All other tracked files, including scripts, notebooks, data/results and financial code, remain byte-identical to the reviewed baseline.

#### Accepted milestone and correction ledger

Each SHA is a verified commit and ancestor of the reviewed baseline. Entries are grouped by milestone; corrections retain their original milestone labels.

| Accepted milestone / correction | Published SHA |
| --- | --- |
| 10.1 — Runtime Contract / Architecture | `b9eb945674fb450515164eb54256d7ac7270d29d` |
| 10.2 — State Model / Pure State Machine | `8b41427d669f5c17717a296113aa7b28b9dd23e3` |
| 10.3 — Initial persistence and lock | `56584c462b1226f36941ab02726ed7a621a82dac` |
| 10.3 — Recovery guards correction | `ad3aca759dbb556d736996bf39b0ba035bb0e512` |
| 10.3 — Durable read APIs correction | `8b3a482f1d7d2586c2f609aa52f32adf283d8a60` |
| 10.3 — STARTING / UNKNOWN_OUTCOME restart correction | `a22199f9abd1ce2484aa6dbde500ad126cb66b21` |
| 10.4 — Closed-Candle Market Data Gate | `1865435bb0310dd5d8e8ce7208d56650dc51590a` |
| 10.5 — Reconciliation including exact-execution correction | `757682038f2a5686e5d45e98dda378e91901b392` |
| 10.6 — Pure planner / explicit sizing | `6865a1e38b91ab3519fe5b84e4864a59db5ff8bd` |
| Stage 9.5 — Pre-submit placement boundary correction | `77a88fe1b1250cabde6a1a6fa4aa492db056084b` |
| 10.7 — Cycle including historical/freshness correction | `728bf6d74d38f5f686f738c71bbf34048e032619` |
| 10.8 — Serialized hourly scheduler | `f3e9fe6bb9770031c121314c67e4177d0299e095` |
| 10.9 — Crash / restart recovery | `fef6b6ee4a8d4fceb9526ed1e3bc1705fda6b7d5` |
| 10.10 — Offline runtime integration regression | `329252658aa703b90f107d862e34dbabd81f0f64` |
| 10.11 audit blocker — Account/order read classification | `4e947b192d9e2b3be8b9b050917ca9e03a250320` |
| 10.11 audit blocker — Public market classification | `c273a8be3213a1cbeb3fc12271d17618f2d28b94` |

Initial 10.5 (`c450025`) and 10.7 (`e6c7b68`) work and their separate correction records remain in Git and in the milestone records above; the ledger lists their final accepted baselines. The final audit was subsequently owner-reviewed and FROZEN at `87888719c3e2c87bd3b8979dd9c4ecc33db6cb65`.

#### Decision 017 final contract matrix

Evidence is the frozen source plus unchanged local offline tests. PASS applies to the accepted initial scope and documented caller responsibilities, not to production or live-money readiness.

| Contract area | Frozen implementation / evidence | Result |
| --- | --- | --- |
| Initial scope | RuntimeConfiguration binds one account/bot/EMA strategy/symbol, interval 60; Spot LONG/FLAT Market actions, isLeverage=0. Store/planner/action tests. | PASS |
| Demo routing | bybit_demo.py and both Demo adapters fix demo=True, testnet=False, api-demo endpoint; per-operation guards. Public reader uses unauthenticated fixed endpoints only. | PASS |
| Identity/config binding | RuntimeStore.open compares complete non-secret configuration, strategy digest/parameters, account/bot/symbol/currencies/timeframe/budget. Mismatch activation tests refuse reopen. | PASS |
| Ownership | Reconciliation binds exact durable action/link/order identities and symbol/side/type/unit. Wallet is coverage only; prefix candidates never establish ownership; foreign open orders/conflicts block. | PASS |
| State model | state.py retains exactly eight operational states, independent desired intent/exposure/pending records and a closed transition table; 188 state tests. | PASS |
| Persistence/schema | store.py: schema v1, exact Decimal TEXT, integer UTC milliseconds, CAS, atomic records, contiguous monotonic frontier and consumed IDs; no reset/migration/repair. | PASS |
| Action phase graph | Seven frozen phases; only permitted forward/repeated-observation edges, attempt_count 0/1, immutable intent/IDs and no terminal rewrite. Store phase tests. | PASS |
| Crash ordering | commit_decision makes PREPARED + decision + frontier durable; preflight then before_submit commits ATTEMPT_STARTED before one placement. Indeterminate persistence stops without follow-up/resend. | PASS |
| Closed-candle gate | closed_candles.py / bybit_public_market.py validate server time, OHLCV, unique hourly continuity, anchored coverage, closure and freshness; scheduler/local sleep is not closure authority. | PASS |
| Public market failure classification | Frozen c273a8b: verified transport TRANSIENT/stale → WAIT/EVIDENCE_MISSING; malformed, permanent and unclassified failures → HALTED/INCONSISTENT_EVIDENCE at both cycle boundaries. | PASS |
| Authenticated broker read classification | Frozen 4e947b1: TRANSIENT → EVIDENCE_MISSING; configuration → HALTED/INVALID_CONFIGURATION; malformed/permanent/unclassified → HALTED/INCONSISTENT_EVIDENCE. Fatal cause wins over last-token exhaustion. | PASS |
| Bootstrap/replay | Durable per-candle BOOTSTRAP then REPLAY_ONLY cutoffs survive interrupted commits/restart; neither may authorize mutations. Only fresh future LIVE events can act. Cycle/recovery tests. | PASS |
| EMA strategy reuse | Cycle calls unchanged generate_ema_signals(EMA20/50, warmup50) and pure canonical intent validation on the full anchored prefix; no duplicate EMA or historical fill engine. | PASS |
| Runtime sizing | Planner BUY is explicit configured fixed quote budget; SELL is exact confirmed owned base. Stage 9 rounds down; no wallet sizing, compounding or Stage 7 position_fraction. | PASS |
| Reconciliation | One bounded normalized read round, exact original-ID/link discovery, complete coherent observations and public durable action/fill APIs. Missing/window-limited evidence remains uncertain. | PASS |
| ACK != fill | Placement/cancellation receipts are separate from order/execution evidence; neither changes exposure or proves terminality. OPEN/partial stays pending; missing order never proves unsent. | PASS |
| Execution/fill ownership | Exact execution-ID deduplication; conflicting duplicates HALT; signed base fees affect inventory exactly, SELL remainders stay owned. Durable terminal fills survive broker retention expiry. | PASS |
| No automatic resend | Original consumed IDs and durable attempt marker prevent resend after timeout, malformed ACK, persistence uncertainty, retry, restart, UNKNOWN_OUTCOME or partial fill. | PASS |
| No automatic cancellation | Runtime cycle/planner/scheduler/recovery have no cancellation dispatch. HALT, shutdown, uncertainty, reversed desire and order age never cancel; operator orchestration remains deferred. | PASS |
| Restart recovery | Account lock → existing store open(initialize=False) → prepare_process_restart → reconciliation/cycle/scheduler. Confirmed states lose freshness; STARTING/HALTED stay; STOPPING(HALTED) restores latch. | PASS |
| Recovery exhaustion | Action rounds/read tokens reserved durably before I/O, never reset; persisted exclusive deadlines survive restart. Exhaustion HALTs, retaining action/pending evidence. | PASS |
| Scheduler serialization | scheduler.py is synchronous/serialized on an absolute UTC hourly grid; reserves next wake before startup work, performs bounded replay and skips missed-hour bursts. | PASS |
| Scheduler retry classification | HALTED exits before retry; only WAIT/RECONCILE/NO_NEW_DATA with EVIDENCE_MISSING/ACTION_OUTCOME_UNKNOWN can retry, max three attempts with 1s/2s waits under original bounds. | PASS |
| HALT latch | State/store retain safe cause/time/exposure/pending; no automatic rearm. Explicit recorded rearm enters SYNCHRONIZING; restart/shutdown cannot bypass latch. | PASS |
| Shutdown | External stop stops scheduling/actions and persists STOPPING with prior exposure, pending work and HALT/uncertainty; no liquidation/cancel. Persistence exceptions propagate. | PASS |
| Single-instance lock | Canonical account-level POSIX flock is exclusive/nonblocking, held for process lifetime before store/session; duplicate cooperating launch refused, same descriptor retained and lock released last. | PASS |
| Secret safety | Neither correction retains raw external error context/text/payload/retMsg. Runtime uses normalized models/safe codes; synthetic secret guards cover results, logs and SQLite. Public trust_env=False/auth=None/fixed URLs/no redirects remain. | PASS |
| Offline integration regression | Real lock/store/restart/scheduler/cycle/reconciliation/reader/EMA/planner/adapters, only external transports/clocks/stop faked. Golden IDs/links/Decimal economics and crash repeatability unchanged. | PASS |
| Historical/backtest preservation | Git shows no Stage 10 changes to historical backtest/analytics/research sizing/robustness/strategy/notebooks/data/dependencies; frozen EMA and all 982 historical/research tests pass. | PASS |
| Optional authenticated Demo activation | NOT RUN; Decision 017 requires separate explicit owner authorization. Tests use synthetic credentials and mocked transports; no actual authenticated Demo operation is part of this audit. | PASS |

Both blocker reproducers now HALT immediately without scheduler backoff or mutation. Malformed wallet makes one account read; unsafe Demo settings make zero SDK reads. Malformed public timeNano and unknown retCode 987654 each make one cycle/one public-time request, zero Kline requests, zero waits, zero placements/cancellations. Verified transient cases at both boundaries and valid stale-data cases retain bounded retries. BrokerOrderNotFoundError and valid OrderStatus.UNKNOWN retain uncertainty semantics.

Guarantees are **one durable logical authorization per candle and at most one automatic placement invocation per durable action**. Exactly-once exchange/network delivery is not guaranteed; orderLinkId is correlation, not delivery proof. A crash after ATTEMPT_STARTED is potentially sent even before physical transport. No transaction spans external I/O; receipts/fills/terminal checkpoints follow later in separate short transactions.

The unchanged golden lifecycle is STARTING → SYNCHRONIZING → FLAT → ENTRY/ORDER_PENDING → LONG → HOLD → EXIT/ORDER_PENDING → FLAT → STOPPING → new process → STARTING → FLAT. Exactly **54 candles/decisions, 2 placement actions, 2 fills, 0 cancellations**, with the original IDs/links and exact Decimal records in the Stage 10.10 table above. Historical next-OPEN fills remain a separate model from broker-reported runtime executions.

Final local execution (not CI): Stage 10.4 **111**, 10.7 **114**, 10.8 **86**, 10.9 **89**, 10.10 **64**, 10.5 **100**, 9.4 **136**, RuntimeStore **230**, 10.6 **79**, 10.2 **188**, locking **23**, 9.5 **100**, placement boundary **29**, 9.6 **68**, frozen EMA **16**, historical/research/backtest **982**, full suite **2,510**. Groups overlap. Zero failures/errors/skips; zero tests added/removed/changed. `pip check`, `git diff --check` and `git diff --staged --check` pass.

```text
Authenticated Bybit Demo read: NOT PERFORMED
Authenticated Bybit Demo order: NOT PERFORMED
Authenticated Bybit Demo cancellation: NOT PERFORMED
```

Stage 10 provides an **offline-regression-validated single-account, single-bot, single-strategy hourly Spot LONG/FLAT Demo runtime architecture** with durable intent, closed-candle gating, fail-closed reads, ownership-safe reconciliation, crash/restart recovery and serialized scheduling. It establishes no profitability, production readiness, live-money safety, full runtime risk management, long-running Demo reliability, exchange fill quality or deployment readiness. No production launcher or actual Demo activation was added.

Caller responsibilities remain explicit: correct non-secret account/profile binding and configuration/digests, canonical local lock before store/clients, existing-store restart, bounded client settings and cleanup with lock last. Stage 9 account_id is a caller label, not an exchange-verified UID; initial ownership assumes cooperative account use without external management of owned inventory. Reads cover limited broker windows and are not atomic exchange snapshots. Deadlines are checked between bounded calls, not guaranteed to interrupt an in-flight paginated SDK request. SQLite durability assumes reliable local storage; the POSIX lock protects cooperating local launches, not multi-host/external clients.

At audit publication, Stage 10.11 was COMPLETE / ready for final owner review/freeze and later stages were NOT STARTED. **Stage 10 is now independently owner-reviewed, COMPLETE / FROZEN at `87888719c3e2c87bd3b8979dd9c4ecc33db6cb65`.** Current Stage 11.1 architecture and the canonical 12-stage roadmap are recorded above; existing correctness/HALT/stop guards do not implement that risk policy. No authenticated Demo run is authorized.

### Accepted Stage 10 roadmap

| Milestone | Status |
| --- | --- |
| 10.1 — Runtime Contract / Architecture | COMPLETE; Accepted; published/frozen; documentation only. |
| 10.2 — Runtime State Model + Pure State Machine | COMPLETE; published/frozen at `8b41427`; pure state core only. |
| 10.3 — Durable Runtime Persistence + Single-Instance Lock | COMPLETE/FROZEN; baseline `56584c4`; corrections FROZEN at `ad3aca7`, `8b3a482` and `a22199f`. |
| 10.4 — Closed-Candle Market Data Gate | COMPLETE; published/frozen at `1865435`; public/read-only only. |
| 10.5 — Startup / Broker Reconciliation | COMPLETE/FROZEN at `7576820`, including the exact-execution correction. |
| 10.6 — Runtime Action Planner + Explicit Demo Sizing Policy | COMPLETE/FROZEN at `6865a1e`; pure planner. |
| 10.7 — Single-Cycle Demo Runtime Orchestration | COMPLETE/FROZEN at `728bf6d`, including the correction. |
| 10.8 — Long-Running Candle Scheduler | COMPLETE/FROZEN at `f3e9fe6`; serialized hourly control. |
| 10.9 — Restart / Crash / Ambiguous-Action Recovery | COMPLETE/FROZEN at `fef6b6e`; checkpoint-only process entry and offline crash proofs. |
| 10.10 — Runtime Integration Regression + Optional Explicit Demo Run | OFFLINE COMPLETE/FROZEN at `3292526`; optional authenticated run NOT PERFORMED / NOT AUTHORIZED. |
| 10.11 — Final Stage 10 Audit + Docs | COMPLETE / owner-reviewed / FROZEN at `8788871`; final contract audit PASS. Both blocker corrections FROZEN at `4e947b1` / `c273a8b`; documentation only. |

The former top-level Stages 11–15 directions are now mapped to Stage 11 — Runtime Risk Management and Stage 12 — Production & Live Readiness under Decision 018. Stage 11.1 defines architecture; 11.2 implements standalone pure policy only. No operational risk integration, multi-bot allocation, live-money functionality or actual authenticated Demo activity is introduced.

Stage 10.1 validation: zero new tests; unchanged full suite **1,384 tests**, zero failures/errors/skips. `pip check` and `git diff --check` pass. Source/tests, Decisions 001–016, notebooks, data/results and installed package versions remain unchanged; only Decision 017 and current documentation change. No runtime implementation, installation, notebook execution or authenticated Demo smoke/order occurred.

## Bybit Demo exchange adapter contract

[Decision 013 — Bybit Demo Exchange Adapter Contract](decisions/013_bybit_demo_exchange_adapter.md) is Accepted. Stage 9.1 freezes the exchange boundary against completed baseline `83e6df19377339ccb3c937f18e1067704e357035` (`Complete Stage 8 strategy robustness`). Stages 6, 7, and 8 remain COMPLETE; Decisions 010–012 and historical strategy/execution/risk/accounting/research behavior are unchanged.

The future flow is Market Data → Strategy → Signal / desired position → Risk Manager → Execution / Runtime → Exchange Adapter → Bybit Demo. Strategy decides WHEN / desired position; risk decides HOW MUCH capital is allocated; execution/runtime supplies explicit authorized intent; the adapter decides HOW to express it to Bybit and normalize exchange state. It does not choose allocation, strategy policy, or backtest fills/PnL. Wallet reads do not authorize spending.

Core accepted rules:

- Bybit Demo Trading UTA only, not Testnet or real trading: centralized `pybit.unified_trading.HTTP` construction uses `testnet=False`, `demo=True`, authenticated REST `https://api-demo.bybit.com`. Credentials are generated while the user's production website account is switched into Demo mode. Missing/ambiguous configuration fails closed, never falling back to real trading; no real-trading switch.
- Initial scope is Spot LONG/FLAT, no margin, borrowing, or leverage, MARKET orders only. BTCUSDT is canonical for integration/smoke; other valid Spot symbols may be supplied. REST only; no WebSockets.
- Explicit market BUY uses `marketUnit="quoteCoin"` (USDT for BTCUSDT); SELL uses `marketUnit="baseCoin"` (BTC). No implicit units or adapter-selected allocation.
- Instrument metadata is authoritative. Decimal-safe canonical strings and round DOWN toward zero only; never increase authorized exposure to meet a minimum. Reject below-minimum/above-maximum requests without automatic splitting or strategy resizing.
- Optional caller `orderLinkId` is validated/forwarded without replacement. Ambiguous placement must not be blindly retried, including inside the SDK; Stage 10 reconciles order state before deciding whether replacement is safe.
- Normalize small instrument/wallet/acknowledgement/order/fill structures; validate `retCode == 0`, shape, and relevant symbol/category. Acceptance does not prove a fill. Actual Demo fills/fees are separate from next-OPEN historical fills and research fee/slippage assumptions.
- Runtime credentials only, never committed, logged, exposed in errors/repr, or included in raw diagnostics. Stage 9.2 accepts only `BYBIT_DEMO_API_KEY` / `BYBIT_DEMO_API_SECRET`; `.env.example` contains those empty placeholders. No session/network activity on import.
- Offline mocked/fake tests by default, with no keys, internet, account, funds, or orders required. Any Stage 9.6 manual Demo smoke is explicit opt-in, starts read-only, and never places an order merely to test connectivity.
- Stage 9 provides exchange/reconciliation primitives. The trading loop, scheduling, polling cadence, signal-triggered orders, state machine, and continuous reconciliation belong to Stage 10 — Demo Trading Runtime, initially using REST polling.
- The Stage 1 public historical Kline helper remains unchanged and separate from later authenticated Demo modules.

Stage 9.1 was documentation/architecture only: Decision 013 and project documentation, with **0** new tests and the unchanged **982-test** suite passing once, zero failures/errors/skips. No source, tests, old decisions, dependencies/environment, `.env.example`, notebooks, data/results, or financial references changed at that milestone; no sessions, credential reads, exchange API calls, or orders occurred. Stage 9.2 is now complete below.

## Secure Demo configuration / session construction

Stage 9.2 is **COMPLETE**. `src/trading_lab/exchange/bybit_demo.py` provides exactly four new public names, also explicitly exported by `trading_lab.exchange`:

```python
BybitDemoConfigurationError(ValueError)
BybitDemoCredentials(api_key: str, api_secret: str)
load_bybit_demo_credentials(environ: Mapping[str, str] | None = None) -> BybitDemoCredentials
create_bybit_demo_session(credentials: BybitDemoCredentials) -> HTTP
```

Credentials are a frozen, slotted dataclass; both values are fully omitted from `repr`/`str`. Construction validates non-empty Python strings with no surrounding whitespace, without stripping/coercion/case changes or arbitrary length/pattern rules. Errors name the relevant variable without exposing values. The loader reads only **BYBIT_DEMO_API_KEY** and **BYBIT_DEMO_API_SECRET** from a supplied Mapping or `os.environ` at CALL TIME. Supplied mappings remain unchanged; there is no `EXCHANGE_*` / `BYBIT_API_*` fallback, credential/session cache, import-time loading, `.env` file loader, or dotenv dependency.

The single session factory requires a `BybitDemoCredentials` instance and accepts no environment-routing overrides. It hard-codes `testnet=False`, `demo=True`, `force_retry=False`, `max_retries=1`, `retry_delay=0`, and `log_requests=False`, forwarding credential strings exactly. Each call returns an independent official pybit HTTP client whose endpoint is **https://api-demo.bybit.com**. The SDK request loop is limited to one attempt; no retry wrapper, read retry, placement retry, or SDK monkey-patch is added. Our code never prints/logs the raw SDK client, which internally holds authentication material.

Both package/module imports require no credentials and construct no client or network request. Credential loading and client construction also make no request; offline tests patch request/send boundaries to fail if invoked, and fresh-process import tests guard against environment reads, client construction, and network calls. No account, key, Demo funds, or internet is needed for tests; all values are synthetic. Stage 9.2 added no wallet/instrument/order adapter APIs, normalization, placement/cancellation, reconciliation, or runtime loop. Stage 9.3's metadata and amount-formatting boundary is described below.

Dependency gate: **Python 3.11.17** in the existing parent `.venv`, satisfying Python >= 3.10; **pybit==5.17.0** appended to requirements and installed at that exact version. `pip check` passes. Pip added pybit's `pycryptodome` dependency; all 104 previously installed distribution versions and all five existing requirement lines are unchanged. The virtual environment was not recreated in this milestone. `.env` remains ignored and untracked; `.gitignore` is unchanged; `.env.example` has exactly two empty Demo-specific placeholders.

Stage 9.2 validation: **42 new tests**, **16 unchanged frozen EMA regression tests**, and its full suite run once: **1,024 tests (982 + 42), zero failures, errors, or skips**. The explicit offline construction smoke reported only safe type/endpoint/flag fields and confirmed the settings above; `git diff --check` passed. Historical Kline, other production modules, existing tests, Decisions 001–013, notebooks, raw data/results, and frozen financial values/tolerances were preserved. Stage 9.3 is now complete below; Stage 9 remains INCOMPLETE.

## Spot metadata / Market amount normalization

Stage 9.3 is **COMPLETE**. `src/trading_lab/exchange/bybit_spot_rules.py` defines six public APIs, available by explicit import from `trading_lab.exchange`; Stage 9.2's existing wildcard-export contract is preserved:

```python
BybitSpotInstrumentError        # RuntimeError subclass
BybitSpotOrderConstraintError   # ValueError subclass
BybitSpotInstrumentRules
fetch_bybit_spot_instrument_rules(session, symbol: str) -> BybitSpotInstrumentRules
normalize_spot_market_buy_quote_amount(rules: BybitSpotInstrumentRules, amount) -> str
normalize_spot_market_sell_base_quantity(rules: BybitSpotInstrumentRules, quantity) -> str
```

The frozen/slotted rules structure contains only `symbol`, `base_coin`, `quote_coin`, `status`, and five positive finite **Decimal** fields: `base_precision`, `quote_precision`, `min_order_amount`, `max_market_order_quantity`, and `tick_size`. It contains no credentials, session/raw response, wallet balance, price, strategy state, or deprecated rules. Direct construction also rejects invalid numeric fields.

Fetching requires a non-empty already-uppercase symbol without surrounding whitespace and a caller-supplied client with callable `get_instruments_info`. It makes exactly one logical call, `session.get_instruments_info(category="spot", symbol=symbol)`, with no pagination kwargs, retry loop, session construction, credential/environment reads, or global cache. SDK/transport exceptions propagate unchanged. The response must be a Mapping with integer `retCode == 0`, a Mapping result with category `spot`, and exactly one instrument Mapping matching the requested symbol, with status `Trading` and non-empty base/quote coins. Both nested filters and all current numeric fields are required; numeric metadata must be valid positive finite decimal strings, parsed without float conversion. Malformed responses fail without raw response/client diagnostics.

Current authoritative fields are `basePrecision`, `quotePrecision`, `minOrderAmt`, `maxMarketOrderQty`, and `tickSize`. Deprecated Spot `minOrderQty`, `maxOrderQty`, and `maxOrderAmt` are ignored even when contradictory; they never replace missing current fields. Unknown extras are tolerated. Maximums come from each fetched response; no BTC limit is hard-coded or cached indefinitely. Synthetic fixture values are not permanent exchange limits. [Current Bybit Spot instrument documentation](https://bybit-exchange.github.io/docs/v5/market/instrument).

Normalizers accept **Decimal**, integral scalars (including Python int), or decimal strings without surrounding whitespace. Floats/NumPy floats, bools, complex values, containers, non-finite/non-positive values, and values rounding to zero are rejected. Generic floor-to-step uses exact integer ratios and Decimal tuple construction so even a small caller Decimal context cannot round exposure up. Outputs are canonical plain decimal strings with no scientific notation, plus sign, or unnecessary fractional trailing zeros. Inputs/rules/responses remain unchanged and repeated calls are deterministic.

- **BUY:** quote-currency budget, rounded DOWN by `quote_precision`; the normalized amount must meet `min_order_amount`. Never raise a below-minimum budget. No quote maximum is invented from the base-unit `max_market_order_quantity` or deprecated `maxOrderAmt`.
- **SELL:** base-asset quantity, rounded DOWN by `base_precision`; the normalized quantity must not exceed `max_market_order_quantity`. Above-maximum values fail without clipping or splitting. `min_order_amount` is quote notional, not a base minimum; no price is supplied to convert it, and deprecated `minOrderQty` is not a fallback.

These are deliberate same-unit validation limits: price-dependent/execution constraints remain authoritative at the exchange and belong to later reviewed preflight work. `tick_size` is retained as metadata and does not change Market amounts. Stage 9.3 added no order body, wallet/order-state read, placement/cancellation, reconciliation, or runtime loop. Imports require no credentials and perform no session construction, metadata fetch, or network call; actual I/O occurs only through an explicit fetch. Tests use fake clients, synthetic responses, and guarded network boundaries; no real credentials or actual Bybit request was used. Stage 9.4 adds read-only snapshots below.

Stage 9.3 validation: **93 new unittest methods**, unchanged Stage 9.2 **42** and frozen EMA **16** passed. Its full suite ran once: **1,117 tests (1,024 + 93), zero failures, errors, or skips**; `pip check` and `git diff --check` passed. Python **3.11.17**, installed/pinned pybit **5.17.0**, all 106 installed distribution versions, requirements, `.env.example`, `.gitignore`, Demo session code/settings, historical Kline, existing tests, decisions, notebooks, data/results, and frozen financial values/tolerances were preserved. Stage 9.4 is now complete below; Stage 9 remains INCOMPLETE.

## Read-only Demo account / order state

Stage 9.4 is **COMPLETE**, ready for owner review/freeze. [Decision 014](decisions/014_read_only_account_and_order_state.md) documents the normalized read-only contract. `exchange/account_state.py` defines frozen/slotted `CurrencyBalance`, `AccountState`, `OrderState`, and `ExecutionState`, the finite `OrderStatus` enum, `BrokerOrderNotFoundError`, and the structural `ReadOnlyBroker` Protocol. `exchange/bybit_demo_read_only.py` implements `BybitDemoReadOnlyAdapter` and the safe `BybitDemoReadError` / `BybitDemoStateParseError` errors. New names are available by explicit package import; prior wildcard exports are unchanged.

```python
BybitDemoReadOnlyAdapter(session, *, account_id=None)
get_account_state() -> AccountState
get_open_orders(symbol: str | None = None) -> tuple[OrderState, ...]
get_order(order_id: str) -> OrderState
get_executions(order_id: str | None = None, symbol: str | None = None) -> tuple[ExecutionState, ...]
```

Account snapshots separate authoritative **USD** UTA totals from individual coin balances/equity/locked amounts. Optional caller `account_id` is a diagnostic label, not an invented broker UID. Unavailable values stay `None`; deprecated coin availability fields are ignored, and per-coin spendable cash is not fabricated from wallet-minus-locked or USD aggregates. This availability information does not authorize capital allocation.

Order snapshots include identifiers, symbol, side/type, finite status plus original `external_status`, requested/filled/remaining amounts with explicit BASE/QUOTE units, separate filled base quantity/quote value, optional average/limit/stop prices, and aware UTC creation/update/server/fetched timestamps. QUOTE Market BUY uses executed quote value when calculating remaining budget; base execution quantity is never subtracted from quote authorization. Remaining means unfilled authorization, including a cancelled remainder or a FILLED quote order's unused budget; it does not imply an active order. Missing fill prices remain `None`. Exact Decimal parsing/subtraction and integer-millisecond conversion avoid implicit float/context rounding.

Orders and fills retain optional reported caller `order_link_id`; absent/blank identifiers stay `None`. Execution snapshots contain the broker execution/order IDs, account label, symbol, side, positive base execution quantity, positive quote-per-base execution price, finite signed fee, optional reported fee currency, and UTC execution/server/fetch timestamps. Multiple fills per order remain separate exchange observations. Require Spot `execType="Trade"`; unsupported execution types and reported margin flags fail explicitly. Missing fee currency stays unavailable; no fee conversion, order-status inference, backtest fill, modeled slippage, or research cost assumption is used.

Status mapping: New → OPEN; Untriggered/Triggered → NEW; PartiallyFilled → PARTIALLY_FILLED; Filled → FILLED; Cancelled/PartiallyFilledCanceled/Deactivated → CANCELLED; Rejected → REJECTED. Other non-empty statuses remain UNKNOWN with their original value; missing/malformed status fails. EXPIRED is reserved internally, not guessed from unsupported Bybit values. Unknown open-query records are not silently dropped or declared active.

The adapter receives the existing Demo session and rechecks its fixed endpoint/flags, one-attempt retry settings, and disabled request logging before every call. Its closed dispatch allowlist contains only four SDK GET reads: UNIFIED wallet balance, Spot realtime orders, exact-ID history fallback, and Spot Trade executions. Wallet reads make one logical call and order lookup at most two; open-order and execution pagination return complete tuples, detect duplicate IDs/cursor failures, and each have a 100-page bound. `get_order` uses history only after a valid empty realtime result; absent records raise `BrokerOrderNotFoundError` with unknown outcome, never a fabricated terminal state. History has broker retention/latency limits. Execution reads use the default seven-day window, optionally filter by order ID/symbol, and validate returned identities; an empty collection only means no observed fills in that window. There is no automatic reconciliation.

API/network/parsing failures raise explicit safe errors with operation/code/type or field context. No raw broker response, client, credential, or SDK exception text is exposed; no snapshot/trading state is cached or partially updated. Imports/construction perform no requests. There are **no placement, cancellation, modification, balance mutation, execution-engine/strategy wiring, or runtime methods**. Existing Limit/conditional records may be observed without introducing those trading actions. Stage 5 remains the frozen EMA regression baseline, including accepted next-OPEN timing; other historical financial contracts remain unchanged.

Validation: **123 new Stage 9.4 tests**, **148 unchanged exchange/API tests** (42 session + 93 Spot + 13 historical data), and **16 frozen EMA regression tests** pass. The final full suite passes: **1,240 tests (1,117 + 123), zero failures, errors, or skips**. Tests use synthetic fixtures, fake clients, fail-on-network guards, SDK GET-path checks, and AST/dispatch mutation guards; no real broker connection/credentials were used. `pip check` and `git diff --check` pass. All 105 protected tracked files, five data/result files, and 106 installed package versions are unchanged; no earlier-stage tests, old decisions, notebooks, dependencies, or frozen values/tolerances changed. Stage 9.4 remains read-only and unchanged; Stage 9.5 is now complete below; Stage 9 remains INCOMPLETE.

## Explicit Demo Spot Market order actions

Stage 9.5 remains **COMPLETE/FROZEN, including its pre-submit correction at `77a88fe`**. [Decision 015](decisions/015_spot_market_order_lifecycle.md) records the original stable action contract; the additive correction is documented above without changing the ADR. `exchange/order_actions.py` defines frozen/slotted broker-independent `SpotMarketOrderRequest`, `SpotMarketOrderAcknowledgement`, and `OrderCancellationAcknowledgement`. `exchange/bybit_demo_orders.py` defines `BybitDemoOrderAdapter`, `BybitDemoActionError`, `BybitDemoOrderRejectedError`, `BybitDemoActionParseError`, and `BybitDemoAmbiguousActionError`. All eight names are explicit package imports; previous wildcard exports remain unchanged.

```python
BybitDemoOrderAdapter(session)
place_market_order(request: SpotMarketOrderRequest, *, before_submit: Callable[[], None] | None = None) -> SpotMarketOrderAcknowledgement
cancel_order(symbol: str, order_id: str) -> OrderCancellationAcknowledgement
```

Request fields: symbol, BUY/SELL side, exact authorized_amount (Decimal/int/decimal string), amount_unit (QUOTE for BUY, BASE for SELL), optional caller order_link_id. Adapter validates the request before mutation. Caller supplies authorization; there is no wallet/risk/position sizing or quote/base conversion. Each placement fetches fresh rules through Stage 9.3 and reuses its exact round-down/constraint helpers. No duplicated precision/min/max logic, increased exposure, permanent metadata cache, clipping or splitting.

Pinned pybit 5.17.0 `place_order` / `cancel_order` signatures and authenticated POST behavior were inspected and tested offline. Placement sends only `category="spot"`, caller symbol, `side="Buy"`/`"Sell"`, `orderType="Market"`, canonical normalized `qty`, `marketUnit="quoteCoin"`/`"baseCoin"`, `isLeverage=0`, and optional caller `orderLinkId`. Cancellation sends only Spot category, symbol and exact `orderId`; no link-only/symbol-only/bulk cancellation. The mutation allowlist contains exactly place_order and cancel_order.

Before preflight and every mutation, require Stage 9.2's exact Demo routing, flags, one-attempt retry settings and disabled request logging; no Testnet/live override or hidden session/environment access. Optional caller links use documented 1–36 ASCII letters/digits/dashes/underscores, forwarded unchanged and matched to the acknowledgement; no ID generation, replacement or uniqueness policy.

Placement receipt fields: broker_id, broker_order_id, optional order_link_id, symbol, side, MARKET order_type, submitted_amount (Decimal), amount_unit, broker_timestamp and fetched_at (aware UTC). Cancellation receipt fields: broker_id, matching broker_order_id, optional reported order_link_id, symbol and both timestamps. Require successful exact integer retCode, valid result/identity/time, and matching category/symbol if echoed. **Placement acknowledgement is not a fill; cancellation acknowledgement is not terminal cancellation.** No status, fake fill/fee/PnL or local state mutation is introduced. Caller separately invokes unchanged Stage 9.4 order/fill reads; concurrent fills and broker cancellation rejection remain possible.

Errors distinguish confirmed nonzero broker rejection (including pinned SDK InvalidRequestError), malformed/mismatched acknowledgement with unknown outcome, and ambiguous transport/SDK failure. SDK retry-code exhaustion is conservatively ambiguous. Metadata failures are sanitized preflight errors with no placement attempt. No raw payload, unsafe SDK message/request/headers/client repr or exception chain is exposed. At most one logical mutation and one actual SDK send are verified; no automatic retry, replacement ID, follow-up read, polling, sleep/reconciliation loop or scheduler exists.

Validation: **76 new Stage 9.5 tests**, unchanged Stage 9.2 **42**, Stage 9.3 **93**, Stage 9.4 **123**, frozen EMA **16**, and full suite **1,316 (1,240 + 76)** pass with zero failures/errors/skips. `pip check` and `git diff --check` pass. Offline fixtures/guards cover exact requests, normalization reuse, receipts, failures, SDK paths/send counts, Demo safety and scope. All 109 protected tracked files, five data/result files, and 106 installed package versions are unchanged; earlier production/tests/decisions/notebooks, financial values/tolerances and next-OPEN timing remain frozen. No actual Demo placement/cancellation, credentials, broker connection or manual smoke. Stage 9.1–9.5 are COMPLETE; Stage 9 remains INCOMPLETE; Stage 9.6 and Stage 10 are NOT STARTED.

## Demo adapter integration and manual diagnostics

Stage 9.6 is **COMPLETE**, ready for owner review/freeze against published baseline `9508eb659a22b55b5d5674bac7714ec0ea6de330`. `tests/demo_broker_fixture.py` reuses existing synthetic broker fixtures in one coherent session; production Stage 9.2–9.5 APIs perform all parsing and normalization. No fake derives fills from placement or chooses amounts/statuses. `tests/test_exchange_integration.py` contains **34 tests**; `tests/test_bybit_demo_smoke.py` contains **34 tests**.

Explicit scenarios cover quote BUY/base SELL authorization through metadata/round-down normalization, separate acceptance/order/fill observations, multiple and partial fills, unused terminal quote budget, cancellation followed by CANCELLED/FILLED/PARTIALLY_FILLED/UNKNOWN observations, exact-ID history fallback, unobserved orders, pagination and late failure. Confirmed broker rejection remains separate from ambiguous timeout/reset/SDK failure or malformed acceptance; no scenario automatically resends, generates a replacement ID or invents state. Fresh metadata/preflight constraints stop invalid orders. Changed wallets cannot resize fixed requests.

Cross-component guards cover every authenticated read/action with unsafe Demo routing, retry/logging flags or malformed settings, including drift between steps/pages; finite read/mutation allowlists, immutable snapshots, safe exceptions/models/diagnostics, import/construction safety, and absence of strategy/backtest coupling or runtime loops. Stage 9.4 remains strictly read-only; only Stage 9.5 SDK place_order/cancel_order are reachable mutations.

**Genuine integration-bug exception:** pinned pybit logs raw retMsg/HTTP response text outside its log_requests guard. An offline real-SDK probe and initially failing regression reproduced the leak. `create_bybit_demo_session()` now assigns each client its own disabled standard-library logger; no global SDK/root logger suppression, changed constructor kwargs, retry policy or public API. All other prior production files and all prior tests/ADRs remain byte-for-byte unchanged. Adapters still provide safe operation/code/type errors; financial results/tolerances and next-OPEN timing stay frozen.

`scripts/bybit_demo_smoke.py` is a manually invoked diagnostic under [Decision 016](decisions/016_manual_demo_smoke.md); [scripts/README.md](scripts/README.md) documents exact commands. No mode/help makes no request or credential read. Explicit read mode queries metadata/account/open orders, optionally executions. Place/cancel modes require explicit symbol/identifiers, placement side/amount/caller link, and additional --confirm-demo-action. BUY implies QUOTE; SELL implies BASE. Read-only account connectivity precedes the single action but never sizes it. Validated authorization is shown before Stage 9.5's fresh normalization/mutation; acknowledgements remain separate from state/fills. Optional --read-after requests bounded observations only after valid acceptance. No automatic cancellation, polling, retry, persistence or runtime. Arguments/errors never echo secrets or raw SDK text; clients close on success/failure.

Validation: **68 new Stage 9.6 tests (34 integration + 34 smoke controls)**; unchanged Stage 9.2 **42**, Stage 9.3 **93**, Stage 9.4 **123**, Stage 9.5 **76**, frozen EMA **16**; full suite **1,384 (1,316 + 68)**, zero failures/errors/skips. `pip check` and `git diff --check` pass. Tests use only synthetic credentials/fixtures and guarded/mocked sends. No actual authenticated Demo smoke/order was executed; future manual execution requires separate owner authorization. Synthetic success proves software contracts, not profitability, actual Demo fills, execution quality or production readiness. Stage 9.1–9.6 are COMPLETE; Stage 9 remains INCOMPLETE; Stage 9.7 and Stage 10 are NOT STARTED.

## Final Stage 9 audit

Stage 9.7 — Final Stage 9 Audit + Docs is **COMPLETE**. Stage 9 — Bybit Demo Exchange Adapter is **COMPLETE** under Accepted, unchanged Decisions 013–016. The audit started from clean `main` at published baseline `10549172e8634a2aef8dafb3579aecc26e64bb50`, with no pre-existing local changes or untracked files. **No blocking Stage 9 audit findings.** No production/test fix or new ADR was needed.

The six commits after Stage 8 completion `83e6df19377339ccb3c937f18e1067704e357035` form the expected chain:

| Milestone / commit | Contract audit |
| --- | --- |
| 9.1 / `e79cb33` | PASS — Demo Spot REST, explicit authorization, historical/runtime separation. |
| 9.2 / `13363dc` | PASS — Demo-specific repr-safe credentials, fixed routing/one-attempt settings, offline construction. |
| 9.3 / `0f32196` | PASS — Current metadata, exact Decimal round-down, quote BUY/base SELL, same-unit constraints. |
| 9.4 / `816f539` | PASS — Immutable Decimal/UTC account/order/fill snapshots, complete bounded reads, UNKNOWN outcomes. |
| 9.5 / `9508eb6` | PASS — Authorized Spot Market placement/exact-ID cancellation, separate receipts, no blind resend. |
| 9.6 / `1054917` | PASS — Cross-component regressions, client-local diagnostic hardening, bounded opt-in smoke controls. |

Authenticated routing retains `testnet=False`, `demo=True`, `https://api-demo.bybit.com`, `force_retry=False`, `max_retries=1`, `retry_delay=0`, `log_requests=False`. No public routing override exists; drift fails closed before reads/actions and after metadata preflight. The factory's disabled logger is client-local, with no shared SDK/root suppression or API/routing/retry change. Offline real-SDK mocked sends verify safe diagnostics. Secret scans found no real-secret candidates; `.env` is ignored/untracked and `.env.example` contains only empty Demo placeholders.

Stage 9.4 remains strictly read-only, isolating payloads behind immutable snapshots. USD aggregates, BASE/QUOTE quantities, exchange-provided fees/currencies, missing values and separate fills preserve their meanings. Unknown statuses remain UNKNOWN; malformed state and late-page failures return no invented or partial snapshot. Unobserved orders remain uncertain. Reading existing Limit/conditional records does not authorize their placement.

Only SDK `place_order` and `cancel_order` mutations are reachable. BUY uses QUOTE/quoteCoin; SELL uses BASE/baseCoin; placement fixes `category="spot"`, `orderType="Market"`, `isLeverage=0`. Fresh Stage 9.3 rules/normalizers are reused without floats, rounding up, clipping, splitting, BTC limits or dimensionally invalid constraints. Caller amounts/links remain authorization; no wallet sizing, replacement IDs or automatic resend. Placement acceptance is not a fill, cancellation acceptance is not terminal state, and confirmed rejection remains distinct from transport/parsing uncertainty.

The optional CLI is bounded: import/default/help makes no credential/network request; read cannot mutate; actions require explicit inputs and --confirm-demo-action. Connectivity never chooses an amount; --read-after observes state/fills only after valid acceptance, and clients close on exit. No automatic cancellation, polling, reconciliation, scheduler, persistence, strategy/backtest wiring or portfolio mutation exists. The unchanged Stage 1 mainnet public Kline URL is unauthenticated historical data, not a live trading route.

**No actual authenticated Demo smoke/order was executed during Stage 9.** Tests use synthetic credentials/responses, fakes and guarded/mocked SDK sends; repository records contain no actual Demo execution evidence.

| Final validation | Passing methods / result |
| --- | ---: |
| Stage 9.2 | 42 |
| Stage 9.3 | 93 |
| Stage 9.4 | 123 |
| Stage 9.5 | 76 |
| Stage 9.6 | 68 (34 integration + 34 smoke controls) |
| Stage 9 additions total | 402 |
| Frozen EMA | 16 |
| Full suite, run once: 982 + 402 | 1,384 |
| pip check / git diff --check | PASS |

All required gates pass with **zero failures, errors or skips**; 9.7 adds zero tests. All 97 protected pre-Stage-9 paths stayed unchanged in every implementation commit. Only accepted env placeholders, the pinned pybit requirement and exchange exports changed in pre-Stage-9 non-documentation files. During 9.7, all 118 protected tracked files, five data/result files and 106 installed package versions remain unchanged; only PROJECT_STATE.md, README.md, CHANGELOG.md and the smoke guide's current-status line change. Notebooks were neither edited nor re-executed.

Frozen Stage 5 values/tolerances, final-candle no-fill and next-OPEN timing, Stage 6 generic contracts, Stage 7 sizing/accounting and Stage 8 robustness remain intact. BTC SHA256 stays `0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`: 8,760 candles, 78 ENTRY / 77 EXIT, 77 CLOSED / one OPEN; last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 and final MTM 9,451.485313939314 / 7,490.776562851941.

Completion verifies exchange infrastructure contracts, not profitability, actual Demo execution quality, live-trading readiness, real-money safety or deployment readiness. Runtime orchestration and complete reconciliation remain absent; strategy → action integration belongs to **Stage 10 — Demo Trading Runtime**, next and **NOT STARTED**, requiring separate explicit approval.

## Accepted Stage 9 roadmap

| Milestone | Direction | Status |
| --- | --- | --- |
| 9.1 — Demo Exchange Adapter Contract | Decision 013 and project documentation only. | COMPLETE; Accepted. |
| 9.2 — Pybit Dependency + Secure Demo Configuration / Session | Pinned pybit, Demo-specific variables, empty `.env.example`, centralized Demo-only offline client construction and 42 tests. | COMPLETE; no exchange requests. |
| 9.3 — Instrument Metadata + Order Normalization | Current Spot Decimal rules, quote BUY minimum/base SELL maximum, exact round-down formatting, 93 offline tests. | COMPLETE; no wallet/orders or actual exchange requests. |
| 9.4 — Read-Only Demo Account / Order State Adapter | Immutable account/order/fill snapshots, explicit statuses, complete bounded reads/exact-ID history fallback, 123 offline tests. | COMPLETE; read-only, no execution capability. |
| 9.5 — Spot Market Order Lifecycle Adapter | Explicit Demo Spot Market BUY/SELL and exact-ID cancellation, separate receipts, 76 offline tests; no loop or local state mutation. | COMPLETE; ready for owner review/freeze. |
| 9.6 — Adapter Integration + Offline Regression + Optional Manual Demo Smoke | 68 offline integration/control tests; bounded opt-in CLI and client-local SDK diagnostic hardening. No actual smoke. | COMPLETE; ready for owner review/freeze. |
| 9.7 — Final Stage 9 Audit + Docs | Contract/regression/scope/secret/Demo safety audit; close Stage 9 and declare Stage 10 next. | COMPLETE; no blocking findings, documentation only. |

## Strategy robustness contract

[Decision 012](decisions/012_strategy_robustness.md) is Accepted. Stage 8 evaluates stability across chronological periods and nearby strategy parameters; it does not optimize profit, choose one best EMA pair, or deploy parameters automatically. Splits use predefined chronological half-open windows, never random splitting or shuffled candles, with no look-ahead. EMA20/50 with 50 warm-up candles remains the existing research baseline, not an optimal or validated strategy.

Every independent IS/OOS/walk-forward segment cold-starts FLAT with its own initial capital and fresh strategy, execution, accounting, and ledger state. Initialization/warm-up occurs inside the segment and remains in its observation window. No pre-window indicators, portfolio state, or trades carry in; no synthetic boundary entry or terminal liquidation is added. Existing strategy generation, generic backtest, independent GROSS/NET accounting, reserve-aware equity, and analytics are reused without duplicate formulas or changed responsibilities.

Sensitivity uses a predefined valid finite grid with consistent window/cost/sizing assumptions; isolated peaks are robustness warnings. Normally hold the accepted fixed `position_fraction` constant while varying time or strategy parameters. Fixed-parameter walk-forward supports the initial research; adaptive selection is not required, and no magic robustness score is introduced. Independent windows do not imply continuous compounded equity. Existing undefined metrics remain honest. The BTC snapshot is already-seen research data; chronological OOS checks within it are methodological evidence, not pristine unseen validation.

Stage 8.1 was documentation/architecture only; Stage 8.2 implements the split/evaluation core, Stage 8.3 adds descriptive parameter sensitivity, Stage 8.4 analyzes local surface variation, Stage 8.5 adds independent expanding walk-forward evaluation, and Stage 8.6 summarizes precomputed IS/OOS and walk-forward results below. Stage 8.7 presents these outputs in executed notebook 06. Stage 7 remains COMPLETE and Stage 5 analytics remains frozen. Current suite: 1,857 tests, zero failures, errors, or skips; the Stage 8 baseline remains 982. `git diff --check` passes. Decision 012 remains unchanged; Stage 8.8 final audit and Stage 8 are COMPLETE.

## Accepted Stage 8 roadmap

| Milestone | Status |
| --- | --- |
| 8.1 — Robustness Contract | Complete; Decision 012 Accepted, documentation/architecture only. |
| 8.2 — Time Split / OOS Evaluation Core | Complete; chronological split and independent cold-start evaluation. |
| 8.3 — Parameter Sensitivity Engine | Complete; deterministic descriptive grid through the existing IS/OOS core. |
| 8.4 — Parameter Stability Analysis | Complete; downstream-only two-dimensional local variation diagnostics. |
| 8.5 — Walk-Forward Evaluation | Complete; fixed-configuration expanding windows with independent cold starts. |
| 8.6 — Robustness Summary / Diagnostics | Complete; downstream neutral comparisons and finite-only independent-window statistics. |
| 8.7 — Strategy Robustness Notebook | Complete; executed local-only research with six embedded figure groups. |
| 8.8 — Final Stage 8 Audit + Docs | Complete; contract/API, history/scope, frozen regression, data, and saved-notebook audits passed. |

## Chronological split / OOS evaluation core

Stage 8.2 introduced three helpers from `trading_lab.robustness`, implemented in `src/trading_lab/robustness/evaluation.py`:

```python
chronological_split(
    candles: pd.DataFrame, train_fraction: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame]

evaluate_strategy_segment(
    candles: pd.DataFrame, strategy_generator, *, candle_interval,
    strategy_kwargs=None, initial_capital: float = 10_000.0,
    fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0,
) -> dict

evaluate_train_test_split(
    candles: pd.DataFrame, strategy_generator, *, candle_interval,
    train_fraction: float = 0.70, strategy_kwargs=None,
    initial_capital: float = 10_000.0, fee_rate: float = 0.0,
    slippage_rate: float = 0.0, position_fraction=1.0,
) -> dict
```

The default is a chronological 70/30 row-count split, with IS size `int(len(candles) * validated_fraction)`. It validates strictly increasing datetime timestamps and a finite real fraction in `(0, 1)` producing two non-empty sides. There is no overlap, gap, sorting, shuffling, or index reset; copies retain all columns, dtypes, timezone, values, and original labels. The frozen local 8,760-row BTC snapshot splits into **6,132 IS / 2,628 OOS** rows; the first OOS timestamp is **2026-06-13 12:00 UTC**. This is a research default, not a universal financial standard.

The generic strategy callable receives only an independent copy of its supplied segment and unchanged keyword settings. EMA initializes from that segment's first CLOSE and performs its own 50-candle warm-up inside the observation window. The evaluator delegates to the existing generic pipeline and reserve-aware GROSS/NET equity; financial validation, formulas, and schemas remain authoritative downstream. It returns exactly `strategy_output`, `execution`, `trades`, `gross_results`, `net_results`, `gross_equity`, `net_equity`, in that order, without summary analytics or added financial-frame metadata.

Train/OOS orchestration returns exactly `split_index`, `split_timestamp`, `in_sample`, `out_of_sample`, in that order. Both evaluations receive the same strategy, interval, kwargs, initial capital, fees, slippage, and fraction. Each starts independently from the configured initial capital; no desired/executed state, signal, OPEN trade, ledger, or capital carries across. A final IS signal cannot use the first OOS OPEN. Segment-end OPEN positions remain unliquidated with missing realized exits and existing final-CLOSE equity marks.

All 56 new `tests/test_robustness_oos.py` methods pass: 18 split, 23 segment, 11 train/OOS, and four local BTC integration cases. They cover exact composition/schema parity, arguments/validation/error propagation, copy preservation, boundary fills, independent state/capital, and exact seven-frame invariance when only the other segment's prices change. The BTC integration verifies cold-start EMA and deterministic local-only composition without downloading data or claiming profitability/robustness. Compatibility gates pass: generic sizing pipeline 24, partial equity 31, frozen EMA regression 16. The full suite passed once: **803 tests (747 existing + 56 new), zero failures, errors, or skips**. Existing files/data and all frozen references/tolerances are preserved; no notebooks were executed.

Stage 8.2 remains complete and frozen. Stage 8.3 composes it for the descriptive grid, Stage 8.4 analyzes that table downstream, Stage 8.5 composes independent expanding train/test windows, and Stage 8.6 summarizes precomputed segment/window results. No new benchmark orchestration or robustness score is implemented.

## Parameter sensitivity engine

Stage 8.3 — Parameter Sensitivity Engine is **COMPLETE**. `src/trading_lab/robustness/sensitivity.py` exposes this generic API by explicit import from `trading_lab.robustness`; the existing three-name wildcard `__all__` contract stays unchanged for Stage 8.2 compatibility:

```python
evaluate_parameter_sensitivity(
    candles: pd.DataFrame,
    strategy_generator,
    parameter_grid,
    *,
    candle_interval,
    train_fraction: float = 0.70,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict
```

The caller supplies a non-empty Mapping of non-empty ordered sequences (such as list, tuple, or range). Mapping key order and candidate order define a deterministic sequential Cartesian product, with one row per combination. Strings/bytes, unordered containers, scalars, invalid keys, empty grids/candidates, overlapping common/grid keys, and names colliding with fixed metric columns are rejected. Strategy parameter semantics remain with the supplied generator. Errors propagate without skipped rows or partial results. Candles, grid/candidate values, and common kwargs are preserved; mutable keyword values are copied per combination.

Each combination calls the unchanged `evaluate_train_test_split(...)` with the same candles, chronological split (default 70/30), interval, initial capital, costs, and fixed allocation. Stage 8.2 supplies independent cold-start IS/OOS behavior. Split metadata must reconcile exactly across combinations. The return keys are exactly `split_index`, `split_timestamp`, `parameter_names`, `results`, in that order; `parameter_names` is the supplied key-order tuple. The table uses a fresh RangeIndex, parameter columns first, then these 11 metrics with `is_` prefixes followed by the same 11 with `oos_` prefixes:

```text
trade_count, closed_trade_count, exposure_ratio,
gross_final_equity, net_final_equity,
gross_max_portfolio_drawdown, net_max_portfolio_drawdown,
gross_sharpe, gross_sortino, net_sharpe, net_sortino
```

Counts are int64; other fixed metrics are float64; parameter columns retain pandas' inferred scalar dtypes. Counts come from canonical trades. Existing trade-time analytics uses the equity path's complete first-to-last valuation window. Final equity includes canonical OPEN-position CLOSE marks; existing portfolio drawdown and risk-adjusted helpers consume the same paths with explicit annualization/risk-free/MAR settings. Undefined NaN and signed infinities remain unchanged. No financial formula, terminal liquidation, ranking, best pair, selection, or optimization is added; EMA defaults stay 20/50 with 50 warm-up candles.

The predefined canonical research grid is fast spans **[10, 15, 20, 25, 30]** × slow spans **[40, 50, 60, 70, 80]** = **25 combinations**, with common warm-up 50 and EMA20/50 included. It is explicitly caller-supplied, never an implicit production default or recommendation. The frozen local BTC snapshot has 8,760 rows; every combination uses **6,132 IS / 2,628 OOS**, first OOS **2026-06-13 12:00 UTC**. Assumptions: initial capital 10,000, fee 0.001, slippage 0.0005, fraction 1.0, periods/year 8760, per-period risk-free/MAR zero. Costs are research assumptions, not current exchange settings. The EMA20/50 row exactly matches direct Stage 8.2 evaluation plus the same analytics.

All **36 new methods** (32 synthetic/contract and four focused local BTC integration cases) pass. Compatibility gates: Stage 8.2 **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. Full suite passed once: **839 tests (803 existing + 36 new), zero failures, errors, or skips**; `git diff --check` passes. Evaluation/backtest/analytics/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 8.3 remains complete and frozen; Stage 8.4 consumes its output below.

## Parameter stability analysis

Stage 8.4 — Parameter Stability Analysis is **COMPLETE**. The downstream-only `src/trading_lab/robustness/stability.py` API is explicitly importable from `trading_lab.robustness`:

```python
analyze_parameter_stability(sensitivity_result, metric: str) -> dict
```

It consumes an existing Stage 8.3 result with the four canonical fields, without calling sensitivity, IS/OOS evaluation, a strategy, or a backtest. This milestone requires exactly two distinct non-empty parameter names in a tuple and a non-empty DataFrame with unique columns and RangeIndex 0..N-1. Both parameter columns and one non-parameter real numeric metric must exist. Boolean/complex metrics, missing/unhashable parameter labels, and parameter names colliding with diagnostic columns are rejected. Each parameter pair must occur exactly once in a complete rectangular Cartesian grid; no missing/duplicate cells are repaired.

Parameter levels are recovered in first-occurrence order, never sorted numerically or converted to strings. Adjacency means one step in each supplied axis, including diagonals: a radius-one Moore neighborhood, excluding the center and without wraparound or numeric-distance weighting. Ordinary two-dimensional corners, non-corner edges, and interiors have **3 / 5 / 8** neighbors; smaller axes retain only the cells that exist. Every source row is retained in its original order.

Return keys are exactly `parameter_names`, `metric`, `parameter_levels`, `surface`, `local_stability`, in that order. `parameter_levels` maps the two names to ordered tuples. The fresh unpivoted `surface` has exactly the two parameter columns followed by the original metric. The fresh `local_stability` has the two parameter columns followed by:

```text
metric_value, neighbor_count, finite_neighbor_count,
neighbor_mean, neighbor_std, neighbor_min, neighbor_max,
mean_absolute_delta, max_absolute_delta,
local_min, local_max, local_range
```

`neighbor_count` includes every geometric neighbor; `finite_neighbor_count` uses `np.isfinite`. Counts are int64, all metric/diagnostic values float64, and parameter columns retain their source dtypes. Neighbor statistics exclude the center and non-finite neighbors; standard deviation uses **ddof=1**, remaining NaN with fewer than two finite neighbors. Mean/min/max are NaN with zero finite neighbors. Absolute deltas use finite neighbors only when the center is finite; otherwise, or with no finite neighbors, they are NaN. Local min/max/range uses the finite center plus finite neighbors, or finite neighbors alone when the center is non-finite; an empty finite region yields NaN. All quantities stay in the metric's own units.

Original NaN, +infinity, and -infinity remain in the surface and `metric_value`; no grid cell is dropped or filled. Inputs are preserved and repeated analysis is exact and deterministic. These diagnostics describe local similarity/variation without deciding performance direction, classifying robust/fragile regions, applying universal thresholds, ranking/selecting parameters, or creating a stability/robustness score. EMA defaults remain unchanged. Broad plateaus versus isolated variation can be interpreted later; no winner or parameter recommendation is recorded.

The hash-checked local BTC integration generates the accepted Stage 8.3 **25-cell** research grid through its production API, with the unchanged fast/slow levels, warm-up 50, default 70/30 split, capital/cost/allocation/annualization assumptions above. It analyzes **OOS NET final equity, Sharpe, and maximum portfolio drawdown**. All three retain every cell; **10/40 has three neighbors, 10/50 five, and EMA20/50 eight**. EMA20/50's exact neighbors are 15/40, 15/50, 15/60, 20/40, 20/60, 25/40, 25/50, and 25/60. Across the 5×5 geometry: four corners with 3, twelve edges with 5, nine interiors with 8. No performance preference is asserted.

All **39 new methods** (35 synthetic/contract, four focused BTC integration cases) pass. Unchanged compatibility gates: sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. Full suite passed once: **878 tests (839 existing + 39 new), zero failures, errors, or skips**; `git diff --check` passes. Existing evaluation/sensitivity/backtest/analytics/strategy modules, tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are preserved. The three-name wildcard export contract stays unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.4 remains complete and frozen; Stage 8.5 composes independent segment evaluations below.

## Expanding walk-forward evaluation

Stage 8.5 — Walk-Forward Evaluation is **COMPLETE**. `src/trading_lab/robustness/walk_forward.py` exposes two APIs by explicit import from `trading_lab.robustness`; the existing three-name wildcard `__all__` contract remains unchanged:

```python
generate_expanding_walk_forward_windows(
    candles: pd.DataFrame,
    initial_train_rows,
    test_rows,
) -> pd.DataFrame

evaluate_expanding_walk_forward(
    candles: pd.DataFrame,
    strategy_generator,
    *,
    candle_interval,
    initial_train_rows,
    test_rows,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> dict
```

The initial mode is expanding training history only: training always starts at positional row zero and grows by `test_rows`. Tests have fixed length, are chronological, non-overlapping and gap-free, and begin exactly at the train slice's exclusive end. Only full test windows are evaluated; a partial final test is excluded and reported as `unused_tail_rows`. Row counts are explicit positive Python/NumPy integral scalars; bools, floats, non-scalars, and insufficient data are rejected. Candles require unique columns and a datetime timestamp column with no missing, duplicate, or non-increasing values. Source order, index labels, dtypes, values, and timezone are preserved without sorting or repair.

The fresh RangeIndex definition table has exactly these columns, in order: `window_id`, `train_start_index`, `train_end_index`, `test_start_index`, `test_end_index`, `train_rows`, `test_rows`, `train_start_timestamp`, `train_last_timestamp`, `test_start_timestamp`, `test_last_timestamp`. Index fields use half-open Python slice semantics; timestamp fields record actual first/last observations without invented calendar boundaries.

The evaluator returns exactly `window_definitions`, `unused_tail_rows`, `windows`, in that order. `windows` is a tuple; each mapping contains exactly `window_id`, `train`, `test`. Each train/test result is the unchanged seven-frame `evaluate_strategy_segment(...)` output. Every segment independently cold-starts FLAT with the same initial capital, fixed generator/configuration, interval, costs, and position fraction. Fresh candle slices and deep-copied strategy kwargs isolate mutable settings between runs and preserve caller inputs. Warm-up occurs inside every segment. No strategy/execution/ledger state, trades, or capital carry across runs; no cross-boundary fill or terminal liquidation is added. Errors propagate without skipping windows or returning partial results. No sensitivity/stability engine is called, no training-based parameter selection occurs, and no summary metrics or stitched equity are produced.

Canonical local BTC research uses **8,760 rows**, `initial_train_rows=4380`, `test_rows=1460`: **three complete windows**, train sizes **4,380 / 5,840 / 7,300**, test size **1,460 each**, and **zero unused tail rows**. Every train begins at **2025-10-01 00:00 UTC**. These are row counts, not exact calendar months.

| Window | Train slice | Test slice | Train last (UTC) | Test start (UTC) | Test last (UTC) |
| --- | --- | --- | --- | --- | --- |
| 1 | `[0, 4380)` | `[4380, 5840)` | 2026-04-01 11:00 | 2026-04-01 12:00 | 2026-06-01 07:00 |
| 2 | `[0, 5840)` | `[5840, 7300)` | 2026-06-01 07:00 | 2026-06-01 08:00 | 2026-08-01 03:00 |
| 3 | `[0, 7300)` | `[7300, 8760)` | 2026-08-01 03:00 | 2026-08-01 04:00 | 2026-09-30 23:00 |

All six evaluations use predefined **EMA20/50**, **50 warm-up candles inside every segment**, initial capital **10,000**, fee **0.001**, adverse slippage **0.0005**, position fraction **1.0**, and the existing one-hour candle interval. Costs are research assumptions. Integration reads only the hash-checked frozen local snapshot, with no download or parameter comparison; it verifies window metadata, fresh EMA initialization/warm-up, unchanged settings, and input/raw preservation without freezing profitability conclusions.

All **42 new methods** pass: **14** window-definition, **24** evaluation, and **4** BTC integration cases. Exact seven-frame direct-composition parity, future-data independence, boundary signals, fresh capital/state, kwargs isolation, tail exclusion, and determinism are covered. Unchanged compatibility gates pass: stability **39**, sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. The full suite passed once: **920 tests (878 existing + 42 new), zero failures, errors, or skips**; `git diff --check` passes. Existing evaluation/sensitivity/stability, backtest/analytics/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.5 remains complete and frozen; Stage 8.6 summarizes its precomputed independent outputs below.

## Robustness summary / diagnostics

Stage 8.6 — Robustness Summary / Diagnostics is **COMPLETE**. `src/trading_lab/robustness/diagnostics.py` exposes exactly two new public APIs by explicit import from `trading_lab.robustness`; all existing explicit imports and the historical three-name wildcard `__all__` contract are preserved:

```python
summarize_train_test_diagnostics(
    train_test_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict

summarize_walk_forward_diagnostics(
    walk_forward_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict
```

Both consume precomputed Stage 8.2/8.5 mappings only. They accept no candles, strategy generator/settings, costs, or sizing parameters and rerun no strategy, backtest, sensitivity grid, stability calculation, or walk-forward evaluation. Structural validation checks canonical fields/types and reconciles window IDs with definition rows in supplied order; existing analytics validate financial frames and propagate their errors without partial summaries. Inputs remain unchanged and every summary table has a fresh RangeIndex.

The exact 14 segment metrics, in order, are `trade_count`, `closed_trade_count`, `exposure_ratio`, `initial_equity`, `gross_final_equity`, `net_final_equity`, `gross_total_return`, `net_total_return`, `gross_max_portfolio_drawdown`, `net_max_portfolio_drawdown`, `gross_sharpe`, `gross_sortino`, `net_sharpe`, `net_sortino`. Counts are int64; the other metrics are float64. OPEN trades remain in total count and final marked equity, without forced closure. Each segment's GROSS and NET initial equity must match exactly or raise ValueError. Total return is the unannualized endpoint diagnostic `final_equity / initial_equity - 1`, not a sum of trades/periods/windows.

Exposure calls `summarize_trade_time_metrics(...)` over the first/last GROSS valuation times. GROSS/NET drawdown calls their existing public portfolio-drawdown summaries. Sharpe/Sortino calls `summarize_risk_adjusted_performance(...)` separately on each independent equity path, forwarding annualization, risk-free return, and MAR unchanged. No financial formula is duplicated.

The single-split return keys are exactly `split_index`, `split_timestamp`, `segment_metrics`, `comparison`. `segment_metrics` has two rows, **IN_SAMPLE** then **OUT_OF_SAMPLE**, with `segment` followed by the 14 metrics. `comparison` has 13 rows in that same metric order excluding contextual `initial_equity`; columns are `metric`, `in_sample_value`, `out_of_sample_value`, `oos_minus_is`. Differences are neutral OOS minus IS values, without interpreting metric desirability.

The walk-forward return keys are exactly `unused_tail_rows`, `window_metrics`, `window_comparison`, `test_metric_summary`. Each wide window row has authoritative definition metadata `window_id`, `train_rows`, `test_rows`, `train_start_timestamp`, `train_last_timestamp`, `test_start_timestamp`, `test_last_timestamp`, followed by all 14 `train_` metrics and then all 14 `test_` metrics. Metadata/counts are int64, other metrics float64, and timestamp dtypes/timezones are preserved. `window_comparison` has 13 rows per window in definition order; columns are `window_id`, `metric`, `train_value`, `test_value`, `test_minus_train`.

`test_metric_summary` describes distributions across independent test windows, with 13 comparable metric rows and columns `metric`, `finite_count`, `mean`, `median`, `minimum`, `maximum`. `finite_count` is int64; descriptive fields are float64. Only finite values enter these four statistics. Zero finite values gives four NaNs; one finite value gives that value in all four fields. Raw window metrics/comparisons retain NaN and signed infinities with normal IEEE subtraction. Independent +10% test windows describe a +10% mean/median, never a +21% compounded portfolio. There is no capital continuity, stitched equity, robustness score, pass/fail classification, parameter ranking, or recommendation. Stage 8.3 sensitivity and Stage 8.4 local stability tables remain separate, ready for later visualization.

The hash-checked local BTC integration uses unchanged EMA20/50, warm-up 50, capital 10,000, fee 0.001, slippage 0.0005, fraction 1.0, one-hour candles, 8,760 periods/year, and zero per-period risk-free return/MAR. These remain research assumptions. Single split: **6,132 IS / 2,628 OOS**, boundary **2026-06-13 12:00 UTC**, diagnostic table **2 × 15**, comparison **13 × 4**. Walk-forward: **4,380 initial train / 1,460-row tests**, **three windows**, **zero tail**, window metrics **3 × 35**, comparisons **39 × 5**, test statistics **13 × 6**. Every train/test initial equity remains **10,000**. All segment metrics match direct public analytics; counts, exposure, equity, drawdown, and endpoint returns satisfy canonical sanity checks. No download or strategy-quality verdict occurs.

All **62 new methods** pass: **24** train/test, **29** walk-forward, **5** architecture/delegation, and **4** BTC integration cases. Coverage includes exact schemas/dtypes/parity, neutral comparisons, raw non-finite preservation, finite-only statistics, non-compounding, input preservation, determinism, structural errors, and the hard no-rerun gate. Unchanged compatibility suites pass: walk-forward **42**, stability **39**, sensitivity **36**, OOS **56**, Stage 7 analytics regression **37**, frozen EMA regression **16**. The full suite passed once: **982 tests (920 existing + 62 new), zero failures, errors, or skips**; `git diff --check` passes. Existing robustness evaluation/sensitivity/stability/walk-forward, analytics/backtest/strategy modules, existing tests, decisions, notebooks, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.7 — Strategy Robustness Notebook is complete as recorded below.

## Strategy robustness notebook

Stage 8.7 — Strategy Robustness Notebook is **COMPLETE**. `notebooks/06_strategy_robustness.ipynb` calls the accepted Stage 8.2–8.6 public APIs, computing each canonical research object once and reusing it for tables and figures. Notebook helpers only format supplied values, pivot parameter tables, and plot; no production financial formulas, neighborhood algorithms, ranking, parameter selection, optimizer, robustness score, or stitched capital are added.

The notebook executed top-to-bottom from a clean kernel in the existing `.venv`: **34 cells (17 code / 17 Markdown)**, all **17** code cells executed with sequential counts **1–17**, valid notebook JSON, **zero saved errors**, and **six embedded Matplotlib figures**. All figures were visually inspected, including readable heatmap annotations/colorbars and visible baseline outlines. The groups are the 2×2 IS/OOS panel; three sensitivity heatmaps; two Sharpe local-variation maps; walk-forward train/test return bars; independent test NET equity indexed to each own start at 100; and three test-diagnostic panels. No external result files are created in the repository.

Data is only the local **8,760-row** `data/raw/BTCUSDT_1h.csv`, period `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. SHA256 **`0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`** is verified before loading and after analysis; loaded candles and raw data are unchanged. Missing/different data stops execution without a replacement download. No network/API calls or package installations occurred.

Canonical settings remain EMA20/50, warm-up 50 inside every segment, capital 10,000, fee 0.001, adverse slippage 0.0005, fixed fraction 1.0, one-hour candles, 8,760 periods/year, and zero per-period risk-free return/MAR. Fees/slippage are frozen research assumptions. The single cold-start split verifies **6,132 IS / 2,628 OOS**, first OOS **2026-06-13 12:00 UTC**. The predefined fast `[10, 15, 20, 25, 30]` × slow `[40, 50, 60, 70, 80]` grid has **25** rows in supplied order; EMA20/50 appears once and has **eight** stability neighbors. Three stability objects cover OOS NET equity, Sharpe, and portfolio drawdown. Walk-forward verifies **three** independent tests, train sizes **4,380 / 5,840 / 7,300**, test sizes **1,460** each, and **zero** unused tail rows; no capital continues between windows.

Markdown distinguishes robustness from profitability and explains chronological testing, local similarity versus isolated variation, and limits of already-seen single-asset/hourly/EMA research. It makes no strategy-quality verdict or live/demo/production claim. All six targeted modules pass: diagnostics **62**, walk-forward **42**, stability **39**, sensitivity **36**, OOS **56**, frozen EMA regression **16**. The full suite passed once: **982 tests, zero failures, errors, or skips**; `git diff --check` passes. No tests were added. Source, tests, decisions, notebooks 01–05, `.py` placeholders, dependencies, data/results, and frozen references/tolerances are unchanged. Stage 7 remains COMPLETE; Stage 8 is COMPLETE after the final audit below. Stage 8.8 — Final Stage 8 Audit + Docs is complete as recorded below.

## Final Stage 8 audit

Stage 8.8 — Final Stage 8 Audit + Docs is **COMPLETE**. Stage 8 — Strategy Robustness is **COMPLETE** under Accepted, unchanged [Decision 012](decisions/012_strategy_robustness.md). All milestones 8.1–8.8 are accepted: contract; chronological split / OOS core; deterministic parameter sensitivity; descriptive local stability; fixed-configuration expanding walk-forward; downstream summary / diagnostics; research notebook; and final audit.

The audit confirms chronological-only splitting without sorting, shuffling, random splitting, overlap, or gaps. Every independent segment generates strategy output from its own candles, cold-starts FLAT with its own configured capital and internal warm-up, and reuses the existing generic backtest, accounting, reserve-aware equity, and analytics. No pre-window indicators, state, capital, trades, cross-boundary fills, or terminal liquidation are introduced. Sensitivity preserves caller-supplied Cartesian order; two-dimensional radius-one Moore stability clips at edges (3/5/8 neighbors) and preserves raw NaN/infinities. Walk-forward holds parameters fixed across expanding trains and independent full tests, with explicit unused tails. Diagnostics consume precomputed results only, retain neutral comparisons and finite-only descriptive statistics, and never compound independent windows. No optimizer, ranking, winner selection, automatic deployment, classification threshold, robustness score, stitched equity, or second financial engine exists.

All **nine** accepted public APIs are explicitly importable from `trading_lab.robustness`. The historical wildcard contract remains exactly `chronological_split`, `evaluate_strategy_segment`, and `evaluate_train_test_split`. The seven implementation commits from `6928991` through `09112fc` added only six robustness modules, five test modules, Decision 012, and notebook 06, plus documentation. Every pre-Stage-8 non-documentation file stayed unchanged in every commit; no later-stage exchange/runtime/database/dashboard/deployment implementation or dependencies were added.

Canonical research remains the frozen **Bybit spot BTCUSDT 1-hour** snapshot: **8,760 rows**, `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`, SHA256 **`0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`** unchanged. EMA20/50 and 50-candle warm-up remain the baseline/defaults, not an optimal configuration. Initial capital 10,000, fee 0.001, adverse slippage 0.0005, fraction 1.0, 8,760 periods/year, and zero per-period risk-free return/MAR stay fixed; costs are research assumptions, not current exchange pricing. The 70/30 split is **6,132 / 2,628**, first OOS **2026-06-13 12:00 UTC**. The ordered 25-cell grid includes EMA20/50 once, with eight neighbors. Three walk-forward tests have **1,460 rows each**, train sizes **4,380 / 5,840 / 7,300**, starts **2026-04-01 12:00**, **2026-06-01 08:00**, and **2026-08-01 04:00 UTC**, and **zero** unused tail. Diagnostics retain shapes **2 × 15**, **13 × 4**, **3 × 35**, **39 × 5**, and **13 × 6**.

Committed notebook 06 validates as JSON with **34 cells (17 code / 17 Markdown)**, saved sequential execution **1–17**, **zero errors**, and **six embedded figures** covering all required groups. Its source/output/claims audit confirms public API reuse, presentation-only helpers, independent own-start equity indexing, no obvious secrets/credentials, no network/download output, and no external result-file dependency. Notebook 06 was **not edited or re-executed** during this audit; its milestone-time status note remains preserved.

Each required targeted suite ran once, as did the full suite:

| Test group | Passing methods |
| --- | ---: |
| Stage 8.2 OOS core | 56 |
| Stage 8.3 sensitivity | 36 |
| Stage 8.4 stability | 39 |
| Stage 8.5 walk-forward | 42 |
| Stage 8.6 diagnostics | 62 |
| Stage 8 additions total | 235 |
| Stage 7 analytics regression | 37 |
| Frozen EMA regression | 16 |
| Full suite: 747 + 235 | 982 |

All gates passed with **zero failures, errors, or skips**; `git diff --check` passes. Stages 8.1, 8.7, and 8.8 add no tests. Stage 7 references and Decisions 010/011/012 are unchanged. Frozen EMA remains **78 ENTRY / 77 EXIT**, **77 CLOSED / one OPEN**, last CLOSED GROSS/NET capital **9,641.111388344 / 7,652.530163437**, and final GROSS/NET MTM equity **9,451.485313939314 / 7,490.776562851941**, with original tolerances. All source, tests, decisions, `.ipynb` files, placeholders, dependencies, data/results, and frozen references are preserved during 8.8; only the four allowed documentation files change, with no new repository files.

Completion means the research tools satisfy the accepted contract, not that the strategy has a proven edge. The BTC sample is already seen; evidence covers one asset, one hourly timeframe, one primary strategy family, and three canonical OOS windows. Cold-start research differs from continuous live state, and transaction costs are frozen assumptions. Historical robustness does not prove future profitability; there is no demo/live trading evidence yet. Stage 7 remains COMPLETE. Stage 9.1–9.7 and Stage 9 are complete; Stage 10 is next and NOT STARTED, awaiting explicit owner approval.

## Risk and position-sizing contract

[Decision 011](decisions/011_risk_and_position_sizing.md) is Accepted. Stage 7's implemented policy is a scalar fixed `position_fraction` in `0 < position_fraction <= 1`, default `1.0`, constant for one backtest run. Reject zero, negatives, values above 1, Python/NumPy bools, non-finite values, strings, None, complex values, and non-scalars without coercion or clamping. No leverage, borrowing, or zero-allocation trade veto is introduced.

Strategy continues to decide Decision-010 intent. Risk determines the allowed budget from CURRENT portfolio capital at each actual executed entry: `position_budget = capital_before * position_fraction`; reserve is `capital_before - position_budget`. Accounting converts that budget into quantity using raw price for GROSS and the existing effective-price/entry-fee self-financing rules for NET. Risk does not calculate quantity, costs, or PnL. Execution timing, prices, signals, and ledger pairing remain unchanged.

Reserve belongs to the same portfolio. Stage 7.5 MTM equity now includes reserve cash plus marked position value: 10,000 capital, fraction 0.50, entry 100, and mark 110 gives quantity 50, reserve 5,000, and equity 10,500 without costs. Next-entry budgets compound from current capital, so 10,500 at fraction 0.50 permits 5,250. OPEN trades retain known entry/budget/reserve information with missing realized exit results; final unexecuted entries allocate nothing, and final unexecuted exits leave positions OPEN. Allocation fraction is distinct from time exposure and is not a fixed loss-at-risk percentage.

Default fraction 1.0 must reproduce Stage 6 exactly, including quantities, independent GROSS/NET accounting, equity, and downstream analytics, without loosening existing tolerances. Frozen BTC reference values are recorded in Decision 011. Prefer existing accounting schemas and derive reserve safely from canonical entry accounting; any necessary new field requires an explicit reviewed decision.

The unchanged Stage 7.2 helper `calculate_position_budget(capital_before, position_fraction=1.0) -> float` supplies budgets to both GROSS and NET accounting. NET budgets include the entry fee and both paths independently compound total portfolio capital. Stage 7.5 equity derives reserve from canonical entry spend without rerunning risk policy. Stage 7.6 `run_backtest_pipeline(...)` forwards the same fraction unchanged to both accounting paths, defaulting to full allocation. Stage 7.7 verifies downstream analytics compatibility at fractions 1.0/0.50/0.25; Stage 7.8 now presents these comparisons in executed notebook 05. Stage 7 code/tests, decisions, notebooks, and data are preserved; the current full suite passes with 2,510 tests.

## Position sizing core

`src/trading_lab/risk/position_sizing.py` exposes `calculate_position_budget(capital_before, position_fraction=1.0) -> float`. The pure helper returns only `capital_before * position_fraction`, using the caller's current total portfolio capital: 10,000 at 0.50 gives 5,000, while 10,500 at 0.50 gives 5,250. It calculates no quantity, costs, reserve cash, PnL, or equity and imports only standard-library `math` and `numbers`.

Capital must be a positive finite real scalar; the fraction must satisfy `0 < position_fraction <= 1` and defaults to 1.0. Python/NumPy integer and floating scalars are accepted and the result is always a positive finite Python float. Python/NumPy bools, non-scalars, strings, None, complex values, and non-finite/nonpositive values raise ValueError. Fractions above 1 are rejected using the original numeric value, even if float conversion rounds them to 1.0. Unsafe conversion overflow/underflow and multiplication underflow to zero are rejected; there is no parsing, clamping, epsilon, minimum allocation, leverage, or veto.

All 35 methods in `tests/test_position_sizing.py` remain unchanged and pass. Stage 7.2's full suite passed once with 597 tests (562 unchanged baseline + 35 new), zero failures, errors, or skips. Tests cover current-capital examples, Python/NumPy scalar types, invalid inputs, exact boundaries, finite float limits, conversion/product underflow, output type, and repeatability. A valid finite float capital multiplied by a fraction at most 1 cannot overflow; conversion overflow is rejected and the final budget still has an explicit finite/positive check.

Stages 7.3 and 7.4 delegate GROSS and NET budgeting to this unchanged helper. Stage 7.5 adds reserve-aware equity downstream; Stage 7.6 forwards the fraction through the generic pipeline without importing risk or calculating budgets. The risk module/package, decisions 001–011, existing notebooks 01–04, requirements, and raw data are unchanged; no notebook was executed during Stage 7.2–7.7. Stage 6 remains COMPLETE. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## GROSS position-sizing integration

`calculate_trade_results(trades: pd.DataFrame, initial_capital: float = 10_000.0, position_fraction=1.0) -> pd.DataFrame` now accepts the allocation fraction as its final positional-or-keyword parameter. The default is 1.0. Each actual ledger entry delegates `calculate_position_budget(capital_before, position_fraction)` to the unchanged Stage 7.2 helper, then calculates `quantity = position_budget / entry_price`. Empty valid ledgers also validate the public fraction through that helper. Existing ledger/schema checks and financial safety checks are preserved; no sorting or repair is introduced.

`capital_before` remains TOTAL portfolio capital. CLOSED `gross_pnl = quantity * (exit_price - entry_price)` and `capital_after = capital_before + gross_pnl` compound that total into the next entry. `trade_return` stays the raw position return `exit_price / entry_price - 1`, independent of fraction. For 1,000 capital and fraction 0.50, a 100 → 110 trade has quantity 5, position return 10%, PnL 50, and total capital 1,050; a next entry at 50 has budget 525 and quantity 10.5.

The exact eleven-column schema is unchanged: six ledger fields plus `capital_before`, `quantity`, `trade_return`, `gross_pnl`, and `capital_after`. No budget/fraction/reserve columns are added. Reserve is derived as `capital_before - quantity * entry_price`; CLOSED capital reconciles to reserve plus `quantity * exit_price` within existing numerical tolerance. OPEN rows have partial-sized quantity and total capital before entry, with missing realized return/PnL/capital-after and exit fields. No mark-to-market or terminal close is introduced. Input values, dtypes, timezone, and index are preserved.

All 25 methods in `tests/test_gross_position_sizing.py`, all 27 unchanged GROSS methods, and all 35 unchanged budget-core methods pass. The full suite passed once with 622 tests (597 existing + 25 new), zero failures, errors, or skips. Default versus explicit 1.0 outputs match exactly; the existing Stage 6 EMA regression remains unchanged and green, with no reference/tolerance changes.

Stages 7.3 and 7.4 added GROSS/NET partial sizing; Stage 7.5 values those canonical results with reserve-aware MTM. Stage 7.6 forwards `position_fraction` through the generic pipeline with default 1.0. Accounting, risk, execution, ledger, decisions 001–011, existing notebooks 01–04, dependencies, and data remain unchanged. The Stage 7.7 partial-allocation analytics audit is complete; Stage 7.8 notebook now demonstrates the verified comparisons. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## NET position-sizing integration

`calculate_trade_results_with_costs(trades: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0) -> pd.DataFrame` adds the fraction as its final positional-or-keyword parameter, default 1.0. Each NET entry delegates its CURRENT independently compounded total `capital_before` to `calculate_position_budget(...)`; empty valid ledgers also validate the fraction through that helper. Fee/slippage validation, then the existing GROSS ledger/numerical validation, precede NET sizing. GROSS output amounts never supply NET budgets or compounding.

`quantity = position_budget / (effective_entry_price * (1 + fee_rate))` keeps entry self-financing: `entry_notional + entry_fee = position_budget`. Reserve stays outside the position and is derived as `capital_before - (entry_notional + entry_fee)`, never stored or charged the entry fee again. Effective-price slippage, notional fees, recorded-price `gross_pnl`, effective-price PnL, and `net_pnl` formulas remain unchanged. CLOSED total `net_capital_after = capital_before + net_pnl` reconciles to `reserve + exit_notional - exit_fee` within existing tolerance and funds the next NET entry.

`net_trade_return = net_pnl / capital_before` remains a portfolio-capital return, while GROSS `trade_return` remains raw position price return. With 1,000 capital, fraction 0.50, zero costs, and 100 → 110, quantity is 5, NET PnL is 50, NET return is 5%, GROSS position return is 10%, and total capital is 1,050. Zero-cost GROSS/NET quantities, PnL, and total capital reconcile at the same fraction; their partial return fields intentionally differ.

The exact twenty-column order is preserved: six ledger columns plus the fourteen existing NET financial fields, which remain float64. No fraction, budget, or reserve columns are added. OPEN rows populate only known entry-side accounting using current NET capital, with all exit/round-trip/realized fields missing. No valuation or forced close is introduced. Input values, column order, dtypes, timezone, index, and optional source fields are preserved.

All 33 methods in `tests/test_net_position_sizing.py`, 21 unchanged transaction-cost methods, 25 unchanged GROSS sizing methods, and 35 unchanged sizing-core methods pass. The full suite passed once with 655 tests (622 existing + 33 new), zero failures, errors, or skips. Default versus explicit 1.0 DataFrames match exactly. Frozen Stage 6 EMA regression remains unchanged and green: last CLOSED NET capital 7,652.530163437 USDT and final NET MTM 7,490.776562851941 USDT; no references or tolerances changed.

GROSS and NET partial accounting from the generic pipeline can feed reserve-aware MTM downstream. Accounting remains unchanged in Stage 7.6; each path uses its own current capital. Stage 7.7 verifies partial-allocation analytics compatibility; Stage 7.8 now demonstrates partial allocation in executed notebook 05. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reserve-aware candle-level MTM

Stage 7.5 keeps the public APIs unchanged: `calculate_gross_mark_to_market_equity(candles: pd.DataFrame, gross_results: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame` and `calculate_net_mark_to_market_equity(candles: pd.DataFrame, net_results: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame`. Equity receives no `position_fraction`, imports no risk helper, and never resizes canonical accounting quantity or rebalances.

GROSS reserve is `capital_before - quantity * entry_price`. NET reserve is `capital_before - (quantity * effective_entry_price + entry_fee)`, so the entry fee is already paid and never deducted again. Canonical entry spend must be finite, positive, and no greater than total capital beyond the existing reconciliation tolerance. Spend close to capital at `rel_tol=1e-12, abs_tol=0.0` produces exact `cash = 0.0`; material overspend raises ValueError without clamping or changing quantity. Each entry's total capital still reconciles with initial capital or the preceding canonical realized exit.

While LONG, cash stays constant at the derived reserve and `position_value = quantity * raw_close`; `equity = cash + position_value`. GROSS unrealized PnL remains `quantity * (raw_close - entry_price)`, giving `equity = capital_before + unrealized_pnl` within tolerance. NET retains its effective-entry basis, giving `equity = capital_before - entry_fee + unrealized_pnl`. A 1,000-capital half allocation at entry 100 has reserve 500 and quantity 5 without costs: CLOSE 110 gives equity 1,050 and CLOSE 90 gives 950. No hypothetical exit fees/slippage or final liquidation are introduced.

Actual EXIT sets cash to canonical `capital_after` / `net_capital_after` and clears the position. A replacement ENTRY at the same OPEN then installs its own reserve and quantity from current independently compounded accounting. The preceding CLOSE observation still occurs before those OPEN events. Initial/flat/no-trade states, the exact eleven-column schema, RangeIndex, int64/nullable-Int64/float64 dtypes, and timestamp/timezone behavior are unchanged. Both inputs are preserved on success and validation failure.

All 31 methods in `tests/test_partial_mark_to_market_equity.py`, 47 unchanged equity methods, 25 unchanged GROSS sizing methods, and 33 unchanged NET sizing methods pass. The full suite passed once with 686 tests (655 existing + 31 new), zero failures, errors, or skips. Explicit full allocation matches default paths exactly. Frozen Stage 6 EMA regression remains unchanged and green: final GROSS MTM 9,451.485313939314 USDT and final NET MTM 7,490.776562851941 USDT; no reference or tolerance changes.

Partial GROSS/NET accounting-to-equity composition is ready through the generic pipeline. Equity remains optional downstream, with unchanged APIs and no allocation parameter. The Stage 7.7 partial-allocation analytics audit is complete; Stage 7.8 notebook is complete and Stage 7 is COMPLETE after the final audit. Accounting, sizing, equity/other analytics, execution, ledger, strategies, decisions 001–011, existing notebooks 01–04, dependencies, and data are unchanged. No notebook was executed during Stage 7.5. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic position-sizing integration

Stage 7.6 adds final positional-or-keyword `position_fraction=1.0` to `run_backtest_pipeline(...)`. The pipeline always forwards the same value unchanged to GROSS and NET accounting, including the default and empty/all-HOLD cases. It owns call order only: no risk import, fraction validation, budgeting, sizing, reserve, equity, or financial formulas. Lower layers retain validation ownership.

Changing the fraction affects accounting quantities and realized results without affecting strategy intent, execution, or ledger pairing. GROSS and NET compound their own current total capital independently. Zero-cost amounts agree at the same fraction; GROSS raw position return and NET portfolio return keep their distinct meanings. The exact four return keys are `execution`, `trades`, `gross_results`, and `net_results`; helper schemas are unchanged and no equity output is added. Omitted versus explicit 1.0 outputs match exactly.

All 24 new synthetic methods in `tests/test_generic_position_sizing_pipeline.py`, all 15 retained generic pipeline methods, 25 GROSS sizing methods, 33 NET sizing methods, and 31 partial-equity methods pass. The full suite passed once with 710 tests (686 existing + 24 new), zero failures, errors, or skips. The frozen Stage 6 EMA regression passes without reference or tolerance changes. Stage 7.7 — Exact Regression + Analytics Compatibility is complete; Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE; the analytics regression and educational notebook are complete; the final Stage 7 audit passed.

## Position-sizing analytics regression

Stage 7.7 uses the unchanged hash-checked `data/raw/BTCUSDT_1h.csv`, 8,760 hourly candles over `[2025-10-01, 2026-10-01)`, EMA20/50 with 50 warm-up candles, and initial capital 10,000. NET fee 0.001 and adverse slippage 0.0005 are fixed research assumptions, not current exchange fees. No download or notebook execution occurred.

Omitted versus explicit fraction 1.0 pipeline/equity DataFrames match exactly and preserve the complete frozen Stage 5/6 regression, including all trade, realized-drawdown, time/exposure, portfolio-drawdown, benchmark, hourly-return, and Sharpe/Sortino references. Fractions 1.0/0.50/0.25 share identical strategy intent, execution, and ledger: 78 ENTRY / 77 EXIT fills, 77 CLOSED / one OPEN trade. GROSS raw trade returns and ledger duration/exposure are invariant; NET portfolio trade returns scale with the fraction and win/loss classification is unchanged in this snapshot. Aggregate PnL-based ratios are not assumed invariant.

Partial accounting feeds reserve-aware equity and all existing downstream analytics with unchanged schemas, signatures, and formulas. Each equity path has 8,761 aligned observations, retains reserve while LONG, and marks final OPEN trade 78 without liquidation. Realized and portfolio drawdown accept the canonical inputs; hourly returns retain all 8,760 periods, cash zeros, and final OPEN changes. Sharpe/Sortino use 8,760 periods/year and zero per-period risk-free return/MAR. Buy-and-Hold remains independently full-allocated and exactly unchanged. No analytics API receives `position_fraction` or imports the risk helper. Input/raw preservation and repeated pipeline/equity runs pass exact checks.

The reviewed one-off production-API capture established these full-precision literal references in `tests/test_position_sizing_analytics_regression.py`. Capital/equity uses USDT; drawdowns are negative decimal fractions and ratios are dimensionless. Tests retain the corresponding established capital, equity, drawdown, and risk-adjusted tolerances.

| Canonical BTC measurement | Fraction 0.50 | Fraction 0.25 |
| --- | ---: | ---: |
| Last CLOSED GROSS capital | 9918.391236748259 | 9985.739621448789 |
| Last CLOSED NET capital | 8837.511197655364 | 9426.098541539295 |
| Final GROSS MTM equity | 9820.851361993184 | 9936.638523863317 |
| Final NET MTM equity | 8744.110764994484 | 9376.288042723892 |
| Maximum realized GROSS drawdown | -0.14248540505494767 | -0.07357702428688317 |
| Maximum realized NET drawdown | -0.20423832781018214 | -0.1070450228128268 |
| Maximum portfolio GROSS drawdown | -0.14809055437971497 | -0.07660787284120885 |
| Maximum portfolio NET drawdown | -0.20920070404661006 | -0.10983103209615619 |
| GROSS Sharpe | -0.058161849146260235 | -0.054056339584623025 |
| GROSS Sortino | -0.08507501805626921 | -0.07914256241587235 |
| NET Sharpe | -0.8824772122392462 | -0.8712069545635516 |
| NET Sortino | -1.2814314707945054 | -1.2663722258083463 |

Smaller allocations leave ending capital/equity closer to 10,000 and produce shallower drawdowns in this frozen losing BTC sample. These tested orderings are dataset-specific, not a general claim about strategy quality. All 37 new methods and all 747 suite tests pass with zero failures, errors, or skips. No production analytics change was required; Stage 7 is COMPLETE. Stage 7.8 — Position Sizing Notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Position-sizing notebook

[Notebook 05](notebooks/05_risk_position_sizing.ipynb) is the Stage 7.8 educational comparison of fractions 1.0/0.50/0.25 using one shared EMA20/50 strategy output and the existing generic pipeline. It explains capital allocation versus signal timing/time exposure, current-capital budgets and compounding, independent GROSS/NET quantity, self-financing entry costs, and reserve-aware equity. Compact views present first-entry budget/spend/reserve, four CLOSED trades, final OPEN holdings, a 12-measurement comparison, and ledger time exposure. Separate GROSS and NET charts show all three total-portfolio equity paths.

It reads only the hash-checked local BTCUSDT 1-hour snapshot: 8,760 candles over `[2025-10-01, 2026-10-01)`, first raw OPEN 114,051.1, SHA-256 `0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975`. Configuration is EMA20/50, 50 warm-up candles, initial capital 10,000 USDT, fee 0.001 and adverse slippage 0.0005 per side (research assumptions, not current exchange fees). Missing data stops execution; no network call, download, dataset export, or production financial formula duplication occurs.

All 32 cells (17 Markdown / 15 code) executed top to bottom using the existing parent-workspace `.venv/`. Saved execution counts are 1–15, error outputs are zero, and both embedded plots were visually inspected. Each equity path has 8,761 observations; trade 78 remains OPEN and marked without liquidation. The four fraction-1.0 capital/equity headlines and both 12-field partial Stage 7.7 snapshots match at established tolerances. Execution, ledger, and time exposure remain fraction-independent: 77 CLOSED / one OPEN, 4,089 invested hours over 8,760 hours, exposure 0.46678082191780823. Realized/portfolio drawdown and Sharpe/Sortino come from unchanged helpers, with 8,760 periods/year and zero hourly risk-free return/MAR.

Input and raw-hash preservation checks pass. The 37-method Stage 7.7 regression, 16-method frozen EMA regression, and full suite (run once: 747 tests) pass with zero failures, errors, or skips; `git diff --check` passes. No production module, test, decision, data, dependency, earlier notebook, or existing `.py` placeholder changed. Smaller-allocation outcomes are explicitly dataset-specific, not recommendations or general strategy improvements. Stage 7.8 is complete; Stage 7.9 — Final Stage 7 Audit + Docs is complete. Stage 7 is COMPLETE.

## Accepted Stage 7 roadmap

| Milestone | Status |
| --- | --- |
| 7.1 — Risk & Position Sizing Contract | Completed; documentation/architecture only. |
| 7.2 — Position Sizing Core | Completed; standalone budget helper only. |
| 7.3 — GROSS Accounting Integration | Completed; direct GROSS accounting only. |
| 7.4 — NET Accounting Integration | Completed; direct NET accounting only. |
| 7.5 — MTM Equity / Reserve Cash | Completed; direct reserve-aware GROSS/NET equity. |
| 7.6 — Generic Backtest Integration | Completed; unchanged fraction forwarding to both accounting paths. |
| 7.7 — Exact Regression + Analytics Compatibility | Completed; frozen full allocation and 50%/25% downstream regression. |
| 7.8 — Position Sizing Notebook | Completed; executed educational 100%/50%/25% comparison. |
| 7.9 — Final Stage 7 Audit + Docs | Completed; architecture, scope, regression, notebook, and documentation gates passed. |

## Final Stage 7 audit

Stage 7 — Risk Manager + Position Sizing is **COMPLETE**. Milestones 7.1–7.9 in the accepted roadmap are complete. Decision 011 is implemented without a new policy or framework: a fixed scalar `position_fraction` in `0 < f <= 1`, default 1.0, permits a budget from current total capital. GROSS and NET independently convert it into quantity and compound total capital; NET's entry budget includes its fee. Equity retains reserve cash alongside the raw-CLOSE marked canonical holding. The generic pipeline only forwards the fraction and retains its four accounting/execution outputs; analytics receives no sizing-policy parameter.

The eight 7.1–7.8 commits form the expected direct-child chain after Stage 6 baseline `df72973de837ecbd4ee81f4bdaf77efd74730a56`, ending at `fc7965fe7d8af1e107b1204e6007feccc2f7fffb`. Production changes are limited to risk budgeting, GROSS/NET accounting, reserve-aware equity, and generic fraction forwarding. Strategy, execution, ledger, other analytics formulas, dependencies, data/results, decisions 001–010, and notebooks 01–04 retain their baseline contents. No hidden production commit, new committed dataset/result, credential, exchange runtime, database, or Stage 8 implementation was introduced.

Default/explicit 1.0 exact-frame compatibility and all frozen Stage 5/6 references pass at unchanged tolerances. The hash-checked local 8,760-candle BTC snapshot preserves 78 ENTRY / 77 EXIT fills, 77 CLOSED / one OPEN trade, last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 USDT, and final GROSS/NET MTM 9,451.485313939314 / 7,490.776562851941 USDT. Both canonical 0.50/0.25 analytics snapshots pass. Intent, execution, ledger, and time exposure remain fraction-independent: 4,089 invested hours / 8,760 hours, exposure 0.46678082191780823. Final trade 78 remains OPEN without liquidation.

| Audit test module | Passed methods |
| --- | ---: |
| Position sizing core | 35 |
| GROSS sizing | 25 |
| NET sizing | 33 |
| Partial MTM equity | 31 |
| Generic sizing pipeline | 24 |
| Position-sizing analytics regression | 37 |
| Stage 7 additions total | 185 |
| Frozen EMA regression | 16 |
| Full suite, run once | 747 |

Every required targeted module and the full suite passed with zero failures, errors, or skips. No tests were added in Stage 7.9. Committed notebook 05 validates as JSON with 32 cells (15 code / 17 Markdown), sequential counts 1–15, zero saved errors, and two embedded plots; its accepted Stage 7.8 execution was inspected without re-execution or modification. It demonstrates local-only fixed-allocation budgeting, compounding, reserve-aware GROSS/NET equity, drawdown, Sharpe/Sortino, and unchanged time exposure through production APIs. Source/test/decision/notebook/dependency bytes and all data/result files were preserved during this audit; `git diff --check` passes. Closure changes only the allowed documentation.

The completed scope remains single-asset LONG/FLAT fixed allocation: no leverage, shorts, dynamic sizing, stop-based sizing, multi-asset or multi-bot allocation. Stage 8 is COMPLETE under Decision 012 after its final audit; Stage 9.1's Demo adapter contract is Accepted and Stage 9.2–9.7 and Stage 9 are complete. Stage 10 is next and NOT STARTED, awaiting explicit owner approval.

## Final Stage 6 audit

Decision 010 remains Accepted. Its four canonical fields (`timestamp`, `signal_time`, `signal`, `desired_position`), strict alignment, one-hour availability, integer LONG/FLAT state machine, final-row no-fill rules, and strategy-owned causality match the implementation.

The final architecture is strategy producer → canonical intent → `validate_strategy_output(...)` → `run_execution_pipeline(...)` → ledger → independent GROSS/NET accounting via `run_backtest_pipeline(...)`. The backtest returns exactly `execution`, `trades`, `gross_results`, and `net_results`. Candle OPEN values remain authoritative; diagnostics cannot control fills. Equity and analytics remain reusable downstream components. EMA20/50 is the only reusable production strategy currently implemented.

The six Stage 6 commits are consecutive direct children after frozen Stage 5 commit `a3fde091be234fd78d216f6338752a810fa117f0`, ending at `c004df851862bc68bf2f6937ca7e94a4b1e3a738`. The committed Stage 6 diff contains exactly the 12 expected files, with no unexpected scope.

| Stage 6 test module | Methods |
| --- | ---: |
| Strategy validation (6.2) | 48 |
| Generic execution (6.3) | 25 |
| Generic backtest (6.4) | 15 |
| EMA exact regression (6.5) | 16 |
| Total Stage 6 additions | 104 |

All 104 targeted methods passed with zero failures, errors, or skips, including the real frozen BTC regression. The full suite passed once: 562 tests (458 Stage 5 + 104 Stage 6), zero failures, errors, or skips. Stage 6.6/6.7 add no tests; `git diff --check` passes.

Frozen Stage 5 execution, ledger, accounting, EMA, analytics, decisions 003–009, notebook 03, market-data code, and dependencies have identical Git blobs/trees. The legacy `run_ema_execution_pipeline(...)` source is unchanged. Exact frame parity and existing scalar tolerances preserve BTC execution/accounting, MTM, trade, drawdown, duration/exposure, risk-adjusted, and benchmark references.

Committed notebook 04 has 23 cells (11 code / 12 Markdown), execution counts 1–11, zero saved errors, and one embedded image. Its saved demonstration covers local frozen data, EMA intent, generic execution/ledger/accounting, downstream equity, a synthetic non-EMA contract example, a conceptual future strategy interface, and preservation checks. Neither notebook 03 nor notebook 04 was re-executed during this audit.

Stage 6.7 changes documentation only. No production code, tests, notebooks, decisions, dependencies, raw data, or financial formulas changed. Stage 7.1 has accepted the sizing contract; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic backtest notebook

[Notebook 04](notebooks/04_generic_backtest_engine.ipynb) demonstrates candles → strategy-specific intent → the Decision-010 contract → `run_backtest_pipeline(...)` → `execution`, `trades`, `gross_results`, and `net_results`. Existing EMA20/50 is one intent producer; a five-candle manually supplied contract example reaches the same shared engine without EMA calculations or a new production strategy. Small views explain availability, desired versus executed state, next-OPEN fills, trade pairing, and independent GROSS/NET sizing/compounding.

The notebook loads only the existing frozen local 8,760-candle BTC snapshot through `load_ohlcv_csv(...)`, checking its canonical window, first raw OPEN, and accepted SHA-256. It has no downloader or external API calls and fails clearly when the file is absent. Frozen sanity checks preserve 78 ENTRY / 77 EXIT signals, 78 trades (77 CLOSED / one OPEN), first fill at `2025-10-13 03:00 UTC` for 115,332.3, and last CLOSED GROSS/NET capital 9,641.111388344 / 7,652.530163437 USDT.

Existing equity helpers compose downstream; the generic engine still stops at accounting. Each path has 8,761 observations, ending at GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT. The final OPEN holding is marked without liquidation. Modeled fee/slippage rates remain frozen research assumptions, not current exchange fees. The notebook copies no production financial formulas; Stage 6.5 remains the authoritative exact compatibility regression.

Executed top to bottom using the existing parent-workspace `.venv/`: 23 total cells, 11 code, 12 Markdown, sequential execution counts 1–11, zero saved errors, and one rendered plot. All intended outputs are saved; the plot was visually inspected. Candles, strategy output, and raw bytes are preserved. The full unchanged suite passed once with 562 tests; no new tests, dependencies, or production modules were added or changed. Notebooks 01–03 and all existing `.py` placeholders are unchanged; notebook 03 was not executed. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## EMA exact regression / compatibility

Stage 6.5 is a regression gate only. The canonical local `data/raw/BTCUSDT_1h.csv` loads through `load_ohlcv_csv(...)` with the explicit hourly window `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`. Before EMA calculations, the new regression module checks the existing frozen SHA-256 from notebook 03, 8,760 rows, first/last timestamps, and first raw OPEN 114,051.1. No download, network call, or raw-file modification occurs. Established local-snapshot test policy permits skipping only when the file is absent on another clone; this environment ran all 16 methods with zero skips.

Using unchanged EMA20/EMA50 and 50 initialization candles, separately generated strategy output exactly matches the legacy combined frame's strategy subset. `run_execution_pipeline(...)` and `run_backtest_pipeline(...)["execution"]` exactly match its six execution columns; generic ledger and independent GROSS/NET accounting exactly match the direct legacy helper path. Frame checks use `check_exact=True`; frozen scalar checks retain notebook 03's established tolerances. Full outputs are cached once per test class.

Bullish/bearish crossovers remain 78/78; ENTRY/EXIT signals and fills remain 78/77; final desired position remains 1. First ENTRY intent is `2025-10-13 02:00 UTC`, filled at the next OPEN `2025-10-13 03:00 UTC` for 115,332.3. The ledger remains 78 trades: 77 CLOSED and one final OPEN with missing exit fields and entry-only accounting. No terminal liquidation is introduced.

Last CLOSED realized capital remains GROSS 9,641.111388344 / NET 7,652.530163437 USDT. Existing equity helpers produce 8,761 observations and final OPEN marks of GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT, exactly matching legacy equity paths. Existing CLOSED-trade summaries, realized/portfolio drawdown, duration/exposure, hourly returns, Sharpe/Sortino, and Buy-and-Hold comparison pass frozen Stage 5 references. NET rates 0.001 fee / 0.0005 adverse slippage remain research assumptions, not current exchange fees.

All 16 Stage 6.5 methods and all 562 tests pass. Candles, strategy output, accounting/equity sources, and raw bytes are preserved. All production Python modules, the existing EMA compatibility function, old tests, decisions 001–010, earlier notebooks, and dependencies are unchanged. Stage 6.6 adds the separate notebook 04 demonstration above. Stage 5 remains COMPLETE and frozen. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic end-to-end backtest pipeline

`run_backtest_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0, position_fraction=1.0) -> dict`

Any valid Decision-010 strategy output can pass through validation/execution, the trade ledger, and independent GROSS/NET accounting. The function owns call order only: `run_execution_pipeline(...)` → `build_trade_ledger(...)` → `calculate_trade_results(...)` → `calculate_trade_results_with_costs(...)`. Both accounting functions receive the same ledger and unchanged `position_fraction`; NET is not derived from the returned GROSS results. Existing helpers own validation, timing, trade pairing, financial mathematics, and output schemas. The pipeline performs no fraction validation or sizing and imports no risk helper.

The new dictionary contains exactly four separate DataFrames: `execution`, `trades`, `gross_results`, and `net_results`, each the corresponding helper's exact output. Strategy diagnostics are ignored; inputs remain unchanged. No strategy generation, analytics summary, equity path, or mark-to-market valuation is included.

An executed entry may remain OPEN with entry-only accounting and missing exit/realized fields. A final unexecuted ENTRY creates no trade; a final unexecuted EXIT leaves the existing trade OPEN. No terminal fill or close is forced. All-HOLD and typed empty inputs retain helper-defined schemas and dtypes.

All 15 new Stage 6.4 methods pass; that milestone's full suite passed with 546 tests. These tests use only synthetic data, including a non-EMA CLOSED trade at recorded prices 100 → 110, multiple trades with independent compounding, zero/nonzero cost parameters, exact four-frame parity, call order, error propagation, preservation, and index/timezone checks. The existing EMA pipeline remains internally unchanged. Stage 6.5 now proves exact EMA compatibility on the frozen BTC snapshot; notebooks 01–03 were neither modified nor executed. Stage 5 remains COMPLETE and frozen. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic execution pipeline

`src/trading_lab/backtest/pipeline.py` now exposes:

`run_execution_pipeline(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

The function calls `validate_strategy_output(...)` before `apply_next_open_execution(...)`. The validator owns intent/alignment/availability; execution owns continuous hourly spacing, valid fill OPEN prices, next-OPEN timing, executed state, and final-row no-fill rules. No indicator logic, warm-up rule, close requirement, or duplicated execution algorithm is added.

Candles supply `timestamp` and authoritative market `open`. Only validated `signal` is transferred into a deep candle copy, replacing any unrelated candle signal locally. Arbitrary strategy diagnostics, including `open` or execution-like names, are ignored and not merged into execution output. Both source DataFrames remain unchanged; ordinary scalar edits to the result do not affect them.

The return is the existing execution helper's exact schema/order/dtypes/index: `timestamp`, `open`, `signal`, `execution_time`, `execution_price`, `executed_position`. Reused alignment checks verify row count, index, and timestamps; additional postconditions verify unchanged validated signals and market OPEN values. Direct-helper parity, non-RangeIndex/duplicate-label alignment, typed empty output, and naive/aware clock checks pass. Valid final entries/exits remain unfilled without forced closing; a newly appended next candle may populate former-final fill metadata without changing earlier rows or state during that candle.

All 25 Stage 6.3 test methods pass; that milestone's full suite passed once with 531 tests (506 earlier + 25 new). `run_ema_execution_pipeline(...)` is not refactored into a wrapper and its source is unchanged. This execution-only API stops before the ledger; Stage 6.4 adds the separate ledger/accounting composition API above. Analytics remain separate downstream components. Stage 5 remains COMPLETE and frozen; notebooks 01–03 were neither modified nor executed. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Generic strategy output validation

Decision 010 is implemented by `src/trading_lab/backtest/strategy_validation.py`:

`validate_strategy_output(candles: pd.DataFrame, strategy_output: pd.DataFrame) -> pd.DataFrame`

Candles need only `timestamp`; strategy output requires `timestamp`, `signal_time`, `signal`, and `desired_position`. Both DataFrames need unique column names. Row counts, indexes (`Index.equals`), and timestamp Series (`Series.equals`) must match exactly. Timestamps must already be non-missing, unique, chronological pandas datetimes; compatible datetime/timezone representation is preserved. Non-RangeIndex and duplicate index labels are valid when aligned. No parsing, sorting, repair, OHLCV checks, candle-spacing enforcement, or warm-up rules are added.

Every signal_time equals its timestamp plus one elapsed hour, including HOLD/final rows and DST transitions. Start desired state FLAT (0); LONG_ENTRY changes 0 → 1, LONG_EXIT changes 1 → 0, and HOLD preserves state. Require Python/NumPy integer 0/1; reject bools, floats, strings, missing values, invalid signals, and inconsistent transitions with ValueError. Valid final-row events and aligned empty typed frames remain valid intent. Causality stays the strategy's responsibility.

The return value is a new full DataFrame copy: canonical and diagnostic columns, values, dtypes, index, and column order are unchanged. Both inputs are preserved; ordinary scalar output edits do not mutate the source. Synthetic EMA output passes without modifying EMA logic. No execution helper is called and no fills or financial fields are added. `run_execution_pipeline(...)` now delegates to this validator; the existing EMA pipeline remains unchanged.

All 48 Stage 6.2 test methods pass; that milestone's full suite passed once with 506 tests (458 earlier + 48 new). Stage 5 remains COMPLETE and frozen, including notebook 03 (104 cells, 51 code / 53 Markdown, seven plots), which was neither modified nor executed. Stage 6.4 now composes execution, ledger, and independent accounting. Stage 6.5 exact EMA regression is complete. Stage 6.6 notebook 04 is complete. Stage 6 is COMPLETE after the final audit; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Final Stage 5 analytics report

Notebook 03 brings together CLOSED-trade performance, realized-capital drawdown, duration/exposure, candle-level MTM equity, candle-close portfolio drawdown, Buy-and-Hold comparison, time-based returns, volatility, and Sharpe/Sortino. Its final report reads existing outputs for setup, a seven-row/four-portfolio comparison, EMA behavior, costs, benchmark opportunity cost, drawdown, time, and risk-adjusted interpretation. Explicit limitations cover this single BTC sample, fixed modeled costs, hourly marks, final OPEN positions, and absent out-of-sample validation.

The final audit checks the 8,760-candle snapshot, 78 executed entries / 77 exits, 77 CLOSED / one final OPEN trade, all four 8,761-observation equity paths and 8,760-return clocks, financial/risk/time references, raw CSV hash, and preservation of 31 report-source DataFrames. All seven existing plot sources/images and earlier calculations are preserved. The notebook has 104 cells (51 code / 53 Markdown), sequential execution, and no saved errors. All 458 existing tests pass; Stage 5.18 adds no tests or metric logic. Production code/tests, decisions, notebooks 01/02, raw data, and dependencies are unchanged.

Stage 5 — Analytics remains complete and frozen at the committed Stage 5.18 baseline. Stage 6.5 proves exact EMA compatibility through generic execution, ledger, accounting, and existing analytics; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable time-based returns and risk-adjusted metrics

[Decision 009](decisions/009_time_based_returns_and_risk_adjusted_metrics.md) is implemented by `src/trading_lab/analytics/risk_adjusted.py`:

- `calculate_time_based_returns(equity_path: pd.DataFrame) -> pd.DataFrame`
- `summarize_risk_adjusted_performance(equity_path: pd.DataFrame, periods_per_year: float, risk_free_return_per_period: float = 0.0, minimum_acceptable_return_per_period: float = 0.0, label: str = "PORTFOLIO") -> pd.DataFrame`

Consume only existing marked portfolio equity, independently for EMA GROSS/NET and Buy-and-Hold GROSS/NET. Time-based returns describe portfolio value through time; completed-trade metrics describe completed trades. No candles, raw asset returns, CLOSED-trade returns/PnL, realized-capital paths, sizing, or fee formulas are substituted.

For ending observation i, simple return is `E_i / E_(i-1) - 1`, timed from previous valuation to current valuation. No log returns, fake observation-0 return, first-return omission, or filtering of flat hours. Exact six-column path: `observation`, `period_start_time`, `period_end_time`, `starting_equity`, `ending_equity`, `period_return`, on a new RangeIndex. Ending ordinals are int64 1..N, datetimes preserve the coherent clock, and financial fields are float64. The summary reuses that helper and returns one row indexed by label: `period_count` (int64), then float64 `mean_period_return`, `period_return_std`, `annualized_volatility`, `downside_deviation`, `annualized_downside_deviation`, `sharpe_ratio`, `sortino_ratio`.

Validation requires unique/required columns, at least two equity observations, canonical integer ordinals 0..N, valid coherent strictly increasing datetimes, equal elapsed spacing including same-zone DST, and finite real numeric equity with bools rejected. First equity is positive and later equity non-negative; every starting equity is positive. A final positive-to-zero loss returns -1; zero before another observation fails. Do not parse, sort, repair, interpolate, or replace zero denominators. Annualization must be explicit positive finite real numeric; rf/MAR must be finite real numeric, all rejecting bools/strings. Labels are nonempty strings. Outputs are independent and sources unchanged; unsafe non-finite arithmetic fails clearly.

Sharpe is `mean(r - rf) / std(r - rf, ddof=1) * sqrt(periods_per_year)`. Hourly standard deviation is sample std; annualized volatility is that std times the same square-root factor. Sortino is `(mean(r) - MAR) / sqrt(mean(min(r - MAR, 0)**2)) * sqrt(periods_per_year)`, with the downside mean over ALL periods, not a negative-return subset. Annualized downside deviation uses the same factor. Current hourly 24/7 crypto convention is `365 * 24 = 8760`, independent of sample row count; rf and MAR are zero because no cash yield is modeled. No external rate is retrieved or converted.

Exact zero standard deviation gives Sharpe +inf / -inf / NaN according to positive / negative / zero mean excess. Exact zero downside gives Sortino +inf for positive numerator or NaN for zero. A single actual return has NaN sample std, annualized volatility, and Sharpe; Sortino still follows its downside rule. No epsilon, infinity clamping, or invented observations. These are documented undefined/degenerate results, not normal BTC results.

The unchanged BTC paths provide 8,760 equally spaced periods: first `2025-10-01 00:00 → 01:00 UTC`, final end `2026-10-01 00:00 UTC`. All four ordinal arrays and both return clocks align exactly. Each independently uses `periods_per_year=8760`, `rf=0`, `MAR=0`:

| Measurement | EMA GROSS | Buy & Hold GROSS | EMA NET | Buy & Hold NET |
| --- | ---: | ---: | ---: | ---: |
| Hourly return periods | 8,760 | 8,760 | 8,760 | 8,760 |
| Mean hourly return | -0.00020683% | -0.00244285% | -0.00285941% | -0.00245998% |
| Hourly sample standard deviation | 0.29590511% | 0.46910330% | 0.29638903% | 0.46909987% |
| Annualized volatility | 27.69520093% | 43.90566292% | 27.74049327% | 43.90534186% |
| Hourly all-period downside deviation | 0.20263178% | 0.33458454% | 0.20449375% | 0.33458454% |
| Annualized downside deviation | 18.96529558% | 31.31539704% | 19.13956636% | 31.31539704% |
| Sharpe ratio | -0.06542095 | -0.48739453 | -0.90295525 | -0.49081624 |
| Sortino ratio | -0.09553483 | -0.68335011 | -1.30872474 | -0.68814247 |

Percentages label return/variability fields; Sharpe/Sortino are dimensionless raw ratios. All results above are finite. EMA GROSS/NET retain 4,647 / 4,595 exact zero-return hours; benchmark GROSS/NET each has three. Unchanged cash periods are included, not filtered. Final EMA trade 78 remains OPEN and its marked-equity change naturally enters the final return. No forced sale, liquidation costs, or realized OPEN result is added.

Sharpe measures reward relative to total variability; Sortino measures reward relative to deviations below MAR. Signs here are relative to zero hourly return. EMA NET finishes with slightly more equity than NET Buy-and-Hold but has more negative ratios; compounded final wealth and arithmetic return relative to variability answer different questions. Results depend on interval, annualization, costs, exposure, and sample window, and establish neither general superiority nor statistical significance.

Notebook 03 snapshots all four equity sources before calling the reusable helpers, displays one compact eight-row comparison and representative first/flat/invested/final return previews, and retains one transparent NET hourly-return scatter plot. Its final Stage 5.18 report brings the notebook to 104 cells (51 code / 53 Markdown), executed sequentially without errors, with seven plots and all seven prior plot sources/images unchanged. Assertions check all 8,760 periods, full clocks, spot formulas, cash zeros, final OPEN marks, actual summary references, all four equity sources, candles, and raw CSV hash. The 61 Stage 5.17 tests cover these contracts, synthetic conventions/degenerate cases, strict validation/DST/preservation/causal prefixes, and actual EMA/benchmark integration. All 458 tests pass. Stage 5.18 preserves production code/tests, decisions, notebooks 01/02, raw data, and dependencies; Stage 5 remains complete; Stage 6.5 proves exact EMA regression through the generic path; Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable Buy-and-Hold benchmark comparison

[Decision 008](decisions/008_buy_and_hold_benchmark.md) is implemented by `src/trading_lab/analytics/benchmark.py` with exactly two public APIs:

- `calculate_gross_buy_and_hold_benchmark(candles: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0) -> pd.DataFrame`
- `calculate_net_buy_and_hold_benchmark(candles: pd.DataFrame, candle_interval, initial_capital: float = 10_000.0, fee_rate: float = 0.0, slippage_rate: float = 0.0) -> pd.DataFrame`

Buy at the first raw OPEN, independent of EMA signals/execution: one canonical trade ID 1, status OPEN, with missing exit time/price. GROSS delegates to Stage 4.6; NET independently delegates to Stage 4.7 with self-financing entry sizing and one actual entry fee/adverse slippage. Both delegate to Stage 5.11 equity and return its exact 11-column schema. The initial flat point is immediately before purchase; N candles produce N + 1 observations, then remain long with ID 1 at each raw CLOSE timed at OPEN + interval. No forced exit or hypothetical exit fee/sell slippage is added; final marked equity is not liquidation proceeds. Zero-cost NET equals GROSS exactly.

Entry guards check DataFrame, unique/required `timestamp`/`open`/`close` columns, nonempty input, usable positive real first OPEN, and an existing first datetime without parsing. Existing accounting/equity validators handle the remaining financial, interval, timestamp, and CLOSE rules. Inputs are unchanged; no sorting, repair, interpolation, framework, class, or new dependency is introduced. Benchmark drawdown reuses the Stage 5.14 calculate/summary helpers.

The unchanged BTC snapshot starts at `2025-10-01 00:00 UTC`, first OPEN 114,051.1 USDT, and finishes at `2026-10-01 00:00 UTC`, marking the final CLOSE 83,616.2 USDT. Each path has initial equity 10,000 USDT and exactly 8,761 aligned observations. NET research assumptions remain `fee_rate=0.001`, `slippage_rate=0.0005`; the benchmark pays one entry, while EMA pays its actual turnover costs. These are modeled assumptions, not current exchange fees.

| Measurement | EMA GROSS | Buy & Hold GROSS | EMA NET | Buy & Hold NET |
| --- | ---: | ---: | ---: | ---: |
| Initial equity (USDT) | 10,000 | 10,000 | 10,000 | 10,000 |
| Final marked equity (USDT) | 9,451.485313939314 | 7,331.468087550229 | 7,490.776562851941 | 7,320.483701755746 |
| Total marked return | -5.4851468606% | -26.6853191245% | -25.0922343715% | -26.7951629824% |
| Maximum candle-close drawdown | -27.6794381422% | -53.7338388920% | -37.9679609807% | -53.7338388920% |
| Observations | 8,761 | 8,761 | 8,761 | 8,761 |

EMA minus benchmark final equity is GROSS +2,120.017226389085 USDT / NET +170.292861096195 USDT; total marked return differences are +21.2001722639 / +1.7029286110 percentage points. Whole-window return means `final equity / initial equity - 1`, not hourly returns or annualization. All four paths lose capital in this declining-BTC sample: EMA's relative advantage does not prove general superiority. Both benchmark paths finish OPEN; no liquidation is fabricated.

Notebook 03 uses helper outputs for the tables and existing equity-comparison plot, with reference assertions for rows, full valuation-time alignment, first-OPEN timing, final OPEN marks, benchmark drawdowns, unchanged EMA/candle inputs, and raw CSV hash. The final Stage 5.18 report preserves the benchmark and time-based analytics sections: 104 cells (51 code / 53 Markdown), seven plots, sequential execution, no saved errors, and all seven prior plot sources/images unchanged. The 38 benchmark tests include exact schemas, delegated sizing/costs, paid-once/no-exit behavior, zero-cost equality, validation, input/output independence, causal prefixes, existing drawdown integration, and actual BTC alignment. All 458 tests pass, including these unchanged 38 benchmark tests. Decision 009 supplies time-based returns and Sharpe/Sortino; Stage 6.4 provides generic execution/ledger/accounting composition; analytics remain separate, Stage 6.5 exact EMA regression is complete, and Stage 6.6 notebook 04 is complete; Stage 6 is COMPLETE; Stage 7.1 contract is complete; Stage 7.2 budget core is complete; Stage 7.3 direct GROSS integration is complete; Stage 7.4 direct NET integration is complete; Stage 7.5 reserve-aware equity is complete; Stage 7.6 generic fraction forwarding is complete; Stage 7.7 analytics regression is complete; Stage 7.8 notebook is complete; Stage 7.9 final audit is complete; Stage 7 is COMPLETE.

## Reusable candle-close portfolio drawdown

[Decision 007](decisions/007_candle_close_portfolio_drawdown.md) is implemented by `src/trading_lab/analytics/portfolio_drawdown.py`. Its sole input is a Stage 5.11 GROSS or NET equity path, requiring `observation`, `valuation_time`, and `equity`. Extra columns are ignored. It never consumes candles/accounting again or reconstructs equity. Both source schemas are identical: the GROSS/NET wrappers express caller intent and summary labels, not detectable provenance or different formulas.

For each observation, `running_peak = max(equity observed so far)`, `drawdown = equity / running_peak - 1`, and `drawdown_amount = equity - running_peak`. Drawdown is a negative decimal; amount is non-positive quote currency. Keep the supplied positive initial observation 0 with zero drawdown/amount; accept later zero equity as `-1.0` drawdown. No new initial-capital parameter, synthetic row, sorting, repair, or lookahead is allowed.

Exact path columns: `observation`, `valuation_time`, `equity`, `running_peak`, `drawdown`, `drawdown_amount`, on a new RangeIndex with unchanged row order/count. Exact summary fields: `max_portfolio_drawdown`, `max_portfolio_drawdown_amount`, `peak_observation`, `trough_observation`, `peak_valuation_time`, `trough_valuation_time`, `peak_equity`, `trough_equity`, in one row indexed GROSS or NET. Financial fields are float64, ordinals int64, and timestamps preserve a coherent source clock. Inputs remain unchanged.

Select the earliest exact minimum percentage-drawdown trough, then the latest exact matching running-peak occurrence at or before it. The summary currency amount belongs to that trough, not an independent minimum amount. Flat/increasing and initial-only paths select initial observation 0 as both peak and trough. Final OPEN marks are naturally included through supplied equity, without status handling or forced closure.

Public APIs: `calculate_gross_portfolio_drawdown(gross_equity_path)`, `calculate_net_portfolio_drawdown(net_equity_path)`, `summarize_gross_portfolio_drawdown(gross_equity_path)`, and `summarize_net_portfolio_drawdown(net_equity_path)`. Each takes only its equity path and returns a new DataFrame. Validation covers unique/required columns, nonempty input, canonical integer ordinals, safely representable strictly increasing coherent datetimes, positive initial/non-negative later finite real equity, and finite float64 arithmetic. No interval/equal-spacing requirement, bool acceptance, parsing, sorting, repair, or timezone conversion is introduced.

The 55 Stage 5.14 tests cover schemas/dtypes, initial-only/flat/increasing/full-loss/recovery paths, worked examples, exact trough/peak ties, associated currency amount, causal prefixes, malformed values/schema/order/clocks, DST, unequal time spacing, optional columns, duplicate indexes, deep-copy/output independence, actual Stage 5.11 integration, and final OPEN marks. All 458 tests pass, including these unchanged 55 tests; Stage 5.15 added no unit tests. Decision 004 retains initial-plus-post-CLOSED observations and excludes/unvalues OPEN; decision 007 observes initial-plus-every-CLOSE equity. Neither candle-CLOSE observations nor HIGH/LOW reveal the full intrabar path. Duration, recovery, and further risk/return metrics remain deferred. Decisions 008/009 now supply aligned Buy-and-Hold comparison, time-based returns, and Sharpe/Sortino.

Stage 5.15 introduced these unchanged helpers in notebook 03 using existing equity paths, compact ten-result summaries, realized-versus-portfolio comparison, selected-episode previews, and one drawdown plot. The current flow is performance → realized-capital drawdown → MTM equity → candle-close portfolio drawdown → benchmark comparison → time-based returns and Sharpe/Sortino → TIME → costs → final OPEN → final integrated report → audit and limitations. Stage 5.18 preserves the earlier sections and all seven plot sources/images. All 51 code cells executed sequentially without errors: 104 total cells, 53 Markdown, seven plots. All tables/plot coordinates come from helper outputs; fixed BTC values are regression assertions only.

## BTC candle-close portfolio drawdown check

The unchanged local loader → EMA20/EMA50 execution pipeline → ledger → independent accounting → Stage 5.11 equity pipeline uses 8,760 hourly candles, 77 CLOSED trades, and one final OPEN trade. Initial capital is 10,000 USDT; NET uses test assumptions only: fee rate 0.001 per side and adverse slippage rate 0.0005 per side. Each equity path feeds its new calculate/summary helpers directly, producing 8,761 drawdown rows including initial observation 0.

| Field | GROSS | NET |
| --- | ---: | ---: |
| `max_portfolio_drawdown` | -0.2767943814221776 | -0.37967960980713844 |
| `max_portfolio_drawdown_amount` (USDT) | -2,779.158887053809 | -3,806.4682385473616 |
| `peak_observation` | 308 | 308 |
| `trough_observation` | 3,687 | 7,369 |
| `peak_valuation_time` (UTC) | 2025-10-13 20:00 | 2025-10-13 20:00 |
| `trough_valuation_time` (UTC) | 2026-03-03 15:00 | 2026-08-04 01:00 |
| `peak_equity` (USDT) | 10,040.517704060354 | 10,025.474479603712 |
| `trough_equity` (USDT) | 7,261.358817006545 | 6,219.0062410563505 |
| Final drawdown | -0.07677164110576007 | -0.25282573128169417 |
| Final running peak (USDT) | 10,237.429583791658 | 10,025.474479603712 |

This sample's 78-point realized-capital paths have maximum drawdowns GROSS -26.7234254550% / NET -37.1855332627%; the 8,761-point candle-close portfolio paths show -27.6794381422% / -37.9679609807%. Here the observed portfolio declines are deeper by 0.9560126872 / 0.7824277180 percentage points. These results come from independently checked paths, not a required universal ordering of the two metrics.

Final observation 8,760 at `2026-10-01 00:00 UTC` retains trade 78's OPEN marked equity: GROSS 9,451.485313939314 / NET 7,490.776562851941 USDT. The final drawdowns are -7.6771641106% / -25.2825731282%. Every source observation is present; no status logic, closing fill, hypothetical exit costs, duration, or recovery calculation is added. Deep-copy checks preserved candles, pipeline/ledger/accounting/equity inputs and the raw CSV hash. Stage 5.15 now presents these results in notebook 03 and verifies the complete peak/trough episode above against helper outputs. This remains candle-CLOSE risk, potentially missing intrabar/tick lows; the notebook explains the conceptual 10,000 → intrabar 7,000 → CLOSE 9,500 limitation without calculating a BTC intrabar metric.

## Reusable candle-level portfolio equity

[Decision 006](decisions/006_candle_level_mark_to_market_equity.md) is implemented by `src/trading_lab/analytics/equity.py`. Consume validated market candles with at least `timestamp` (OPEN time) and `close`, plus independent canonical GROSS results from Stage 4.6 `calculate_trade_results(...)` or NET results from Stage 4.7 `calculate_trade_results_with_costs(...)`. Reuse each path's quantity and realized capital without resizing, reconstructing PnL/capital, or rerunning cost formulas; Stage 4.7 `gross_pnl` is not the independent GROSS simulation. Stage 7.5 implements Decision 011 reserve-cash semantics for both full and partial canonical accounting results while preserving Decision 006 valuation timing and schema.

Public functions: `calculate_gross_mark_to_market_equity(candles, gross_results, candle_interval, initial_capital=10_000.0)` and `calculate_net_mark_to_market_equity(candles, net_results, candle_interval, initial_capital=10_000.0)`. Both return new independent path DataFrames. GROSS requires `trade_id`, `status`, `entry_time`, `entry_price`, `exit_time`, `capital_before`, `quantity`, `capital_after`; NET requires `trade_id`, `status`, `entry_time`, `exit_time`, `capital_before`, `quantity`, `effective_entry_price`, `entry_fee`, `net_capital_after`, even for empty input. Wrong accounting sources fail clearly. Initial capital is an independent positive finite real parameter, never inferred; use the same value as accounting.

The required explicit positive fixed `candle_interval` defines `observation_start = first timestamp` and `observation_end = last timestamp + interval`. N contiguous candles give N + 1 observations. Initial observation 0 is immediately before any first-OPEN fill. For each candle: carry state → actual EXIT at its OPEN → actual ENTRY at its OPEN → observe completed CLOSE → mark remaining quantity → record at OPEN timestamp + interval. A preceding CLOSE observation occurs before the next OPEN's fills at the same boundary timestamp. If a future valid ledger shares exit/entry time, EXIT precedes ENTRY; current upstream validation stays unchanged. Fills must match supplied candle OPENs; the exclusive window end is not an extra OPEN.

Both paths mark at the same raw market CLOSE. Current scope is one asset, long-only spot, one position, no leverage, canonical full or partial entry allocation, fixed NET cost assumptions, and fixed-interval candle-CLOSE marking. After entry, cash is derived reserve and quantity is canonical; `position_value = quantity * close` and `equity = cash + position_value`. GROSS price-based `unrealized_pnl = quantity * (close - entry_price)`; NET uses `effective_entry_price` instead and excludes the already-paid entry fee. NET entry slippage/fee already affect canonical basis/quantity; do not charge entry fee again. Conceptually `equity = capital_before - entry_fee + unrealized_pnl`; at the effective-entry basis mark, NET unrealized PnL is zero while total equity is lower than capital before by the paid fee.

At an actual exit, set cash directly to GROSS `capital_after` / NET `net_capital_after`, clear position/active ID, and set quantity/value/unrealized PnL to zero. NET realized cash already includes actual exit costs. Do not re-sell quantity or subtract costs again. If the portfolio stays flat, that candle's CLOSE equity reconciles to canonical realized cash. With a replacement entry at the same OPEN, reconcile immediately after exit and then mark the new position; do not force its CLOSE equity to the old realized value.

The final OPEN position is marked on every remaining CLOSE, including the last, without inventing exit time, realized PnL, or capital-after values. Marking creates no trade and charges no hypothetical exit fee/slippage, spread, or bid/ask adjustment. Final NET equity reflects only costs actually incurred, not hypothetical liquidation proceeds. Existing accounting/realized analytics retain their separate OPEN semantics; Stage 5.12 now presents the independent equity paths and final OPEN valuation in notebook 03.

Exact columns, in order: `observation`, `candle_timestamp`, `valuation_time`, `mark_price`, `position`, `active_trade_id`, `cash`, `quantity`, `position_value`, `unrealized_pnl`, `equity`. Output has a RangeIndex; observation/position are int64, active ID nullable Int64, all six price/financial fields float64, and timestamps retain coherent datetime/timezone semantics. Initial row: `0`, `NaT`, `observation_start`, `NaN`, `0`, missing ID, `initial_capital`, `0.0`, `0.0`, `0.0`, `initial_capital` respectively. Each subsequent mark belongs to its source candle and is timed at its completion.

Decision 006 specifies strict candle spacing/positive CLOSE validation, event-to-OPEN alignment, canonical source/status/order/non-overlap checks, capital/allocation reconciliation, finite arithmetic, coherent all-naive or matching-zone-aware timestamps, and input preservation without sorting, repair, parsing, or timezone conversion. UTC remains recommended. No future exit or next-candle price may influence a current mark. Zero trades still give N + 1 flat constant-equity observations with recorded candle marks. OPEN-only input is marked from entry onward; a final-OPEN entry gets a final CLOSE mark, while a final-OPEN exit leaves realized cash if flat. An unexecuted final-candle signal is not a fill.

Decision 004 remains separate and unchanged: initial plus post-CLOSED realized-capital drawdown omits within-trade losses. Decision 007 is now implemented from the initial-plus-every-CLOSE equity series. This still cannot observe intrabar/tick losses. A fall from prior-close equity 10,000 to an intrabar 7,000 followed by a 9,500 CLOSE records only 9,500. HIGH/LOW does not reconstruct that path; excursion/stress analytics and further portfolio-metric implementations remain deferred. Decision 006's worked GROSS example passes as a synthetic test: 1,000 → 1,100 → 900 → 1,200 versus realized 1,000 → 1,200.

## BTC candle-level equity check

Used the existing local BTCUSDT snapshot through the unchanged loader, default EMA20/EMA50 pipeline with 50-candle warm-up, ledger, and independent Stage 4 accounting. Initial capital is 10,000 USDT and interval is one hour. NET uses the established research assumptions `fee_rate=0.001`, `slippage_rate=0.0005` (0.10% fee / 0.05% adverse slippage per side), not current exchange fees.

| Measurement | GROSS | NET |
| --- | ---: | ---: |
| Equity path rows (8,760 candles) | 8761 | 8761 |
| Initial equity, USDT | 10000 | 10000 |
| Final position / active trade ID | 1 / 78 | 1 / 78 |
| Final quantity, BTC | 0.1130341406801471 | 0.08958523064731405 |
| Final price-based unrealized PnL, USDT | -189.62607440501543 | -154.10871530682684 |
| Final position value, USDT | 9451.485313939314 | 7490.776562851941 |
| Final marked equity, USDT | 9451.485313939314 | 7490.776562851941 |
| CLOSED exit observations reconciled | 77 / 77 | 77 / 77 |

The ledger has 77 CLOSED trades and one final OPEN trade. Final candle OPEN is `2026-09-30 23:00 UTC`, raw CLOSE is 83,616.2 USDT, and final valuation time is `2026-10-01 00:00 UTC`. Both paths end long with zero cash; trade 78 remains OPEN with missing exit/capital-after values. Its marked equity is not realized capital or hypothetical liquidation proceeds. Stage 5.12 presents these values in notebook 03 alongside a realized-versus-marked table, compact previews, and one time-axis equity plot. Input/path deep-copy and raw-hash checks pass; no dataset/report is exported. Stage 5.15 now also presents portfolio drawdown from these same unchanged MTM paths, including their final OPEN observations naturally.

## Reusable trade duration and exposure

[Decision 005](decisions/005_trade_duration_and_exposure.md) is implemented by `src/trading_lab/analytics/trade_time.py`. Its helpers consume `trades`, the canonical executed ledger from `build_trade_ledger(...)`, requiring `trade_id`, `status`, `entry_time`, and `exit_time` even when empty. Price economics and optional accounting fields do not affect time analytics. Current fees/slippage change quantity/PnL/capital but not fill timestamps, so calculate once from the ledger. Any strategy/model producing that ledger can share these helpers.

For CLOSED trades, `closed_trade_duration = exit_time - entry_time > 0` over `[entry_time, exit_time)`. Hours express elapsed seconds divided by 3,600, preserving fractional and sub-microsecond precision without counting candles or rounding. OPEN completed duration is NaN and excluded from all CLOSED descriptive statistics/totals. Its observed interval through `observation_end` still contributes to exposure, without changing its missing ledger exit or creating a valuation.

The caller supplies an explicit positive `[observation_start, observation_end)` window; boundaries are never inferred from trading activity. For candle research, start is the first candle OPEN and end is the final candle OPEN plus its interval. The BTC check uses `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`, including the final hour, warm-up, and flat periods. No dataset-specific dates or values are hardcoded into analytics.

```text
observation_window_duration = observation_end - observation_start
total_time_in_market = sum(CLOSED exit_time - entry_time)
                       + (observation_end - final OPEN entry_time, if present)
exposure_ratio = total_time_in_market / observation_window_duration
```

Exposure is a decimal `[0, 1]`, without annualization or internal percentage conversion. Summing intervals relies on the current non-overlapping, single-position ledger. A ten-hour window with one three-hour CLOSED interval and one three-hour observed OPEN interval gives six hours / ten hours = 60% exposure; CLOSED descriptive durations contain only the completed trade. Using the first entry to shorten that window to nine hours would incorrectly report 66.67%.

Public APIs: `calculate_trade_time_breakdown(trades: pd.DataFrame, observation_start, observation_end) -> pd.DataFrame` and `summarize_trade_time_metrics(trades: pd.DataFrame, observation_start, observation_end) -> pd.DataFrame`. Both boundaries are required, with no defaults. The summary reuses the validated per-trade calculation. Exact per-trade columns, in order: `trade_id`, `status`, `entry_time`, `exit_time`, `closed_duration_hours`, `observed_time_in_market_hours`. The new table preserves source order/index, IDs/status, timestamps/dtypes/timezones, and the original missing OPEN exit; duration fields use float64 even when empty. No price, PnL, or capital fields are added.

Exact separate summary columns, in order: `closed_trade_count`, `open_trade_count`, `average_closed_duration_hours`, `median_closed_duration_hours`, `minimum_closed_duration_hours`, `maximum_closed_duration_hours`, `total_closed_duration_hours`, `open_observed_duration_hours`, `total_time_in_market_hours`, `observation_window_hours`, `exposure_ratio`. One row is indexed `TIME`; counts are int64 and the other nine fields float64. The existing 16-metric summaries and drawdown component remain unchanged.

With no trades, counts, aggregate holding times, and exposure are zero; the four CLOSED descriptive duration statistics are NaN and the explicit window remains positive. OPEN-only input also has NaN CLOSED descriptive statistics, but its observed time produces positive exposure. An entry at window start still OPEN through its end gives exposure `1.0`, without a completed duration.

Validation requires unique DataFrame columns, the schema even when empty, exact CLOSED/OPEN statuses, valid non-missing datetime scalars, safely representable positive elapsed durations, entries within `[start, end)`, and CLOSED exits after entry and no later than end. Strings/numeric epochs are rejected rather than parsed. OPEN exits must be missing; OPEN entry at end is invalid. At most one OPEN is allowed, as the final row. Entries must be chronological and each next entry must be at or after the previous CLOSED exit; touching half-open boundaries are allowed. Malformed order/overlap is rejected without sorting, clipping, or repair. Both APIs preserve their input; full ledger validation stays upstream. UTC-aware timestamps are recommended; accept all-naive inputs or all-aware inputs with matching timezone implementation/zone, including DST offset changes within that zone. Reject mixing/different zones without localization, conversion, or stripping; aware subtraction measures actual elapsed time.

## BTC trade duration and exposure check

The unchanged local loader → EMA20/EMA50 pipeline (50-candle warm-up) → canonical trade ledger feeds both time APIs directly. No gross/net accounting is called. The explicit window is `[2025-10-01 00:00 UTC, 2026-10-01 00:00 UTC)`: first candle timestamp through last candle timestamp plus one hour. Inputs and the raw-file hash were preserved.

| TIME summary field | BTC result |
| --- | ---: |
| `closed_trade_count` | 77 |
| `open_trade_count` | 1 |
| `average_closed_duration_hours` | 52.96103896103896 |
| `median_closed_duration_hours` | 34.0 |
| `minimum_closed_duration_hours` | 1.0 |
| `maximum_closed_duration_hours` | 226.0 |
| `total_closed_duration_hours` | 4078.0 |
| `open_observed_duration_hours` | 11.0 |
| `total_time_in_market_hours` | 4089.0 |
| `observation_window_hours` | 8760.0 |
| `exposure_ratio` | 0.46678082191780823 |

The first CLOSED trade lasted 27 hours; the longest was trade 68 at 226 hours. Final OPEN trade 78 entered at `2026-09-30 13:00 UTC` and contributes 11 observed hours. Its exit remains missing and its completed duration remains NaN; it is not valued. Exposure is about 46.678082% for this sample, with no general strategy-quality conclusion. Stage 5.9 presents these same helper outputs in notebook 03 with a separate TIME table, six-row preview, longest-CLOSED inspection, and regression assertions.

## Reusable realized-capital drawdown

Module: `src/trading_lab/analytics/drawdown.py`. All four functions take `(results: pd.DataFrame, initial_capital: float = 10_000.0)` and return a new `pd.DataFrame`:

| Path function | Summary function | Required source columns | Canonical CLOSED capital |
| --- | --- | --- | --- |
| `calculate_gross_realized_drawdown` | `summarize_gross_realized_drawdown` | `status`, `capital_before`, `capital_after` | Stage 4.6 `capital_after` |
| `calculate_net_realized_drawdown` | `summarize_net_realized_drawdown` | `status`, `capital_before`, `net_capital_after` | Stage 4.7 `net_capital_after` |

Exact path columns, in order: `observation`, `closed_trade_number`, `capital`, `running_peak`, `drawdown`, `drawdown_amount`. The first two use int64; the other four use float64. Output has a RangeIndex. Observation 0 has both ordinals 0, capital/peak equal to explicit initial capital, and both drawdown fields `0.0`. Each CLOSED row adds one point in existing input order, so `N` CLOSED trades produce `N + 1` rows. `capital_before` is a schema guard, never the inferred initial value; callers supply the same initial capital as accounting.

Exact summary columns, in order: `max_realized_drawdown`, `max_realized_drawdown_amount`, both float64. There is one row indexed `GROSS` or `NET`. Running peak is the maximum capital through the current observation; drawdown is `capital / running_peak - 1`, and amount is `capital - running_peak`. Maximum drawdown is the minimum negative decimal drawdown. Exact tied minima select the earliest observation; the reported amount belongs to that same point, which can differ from the minimum currency decline. No rounding, tolerance, or clamping changes the calculation.

Validation requires a DataFrame, unique columns, the source-specific schema even for empty input, and statuses exactly CLOSED/OPEN. Initial capital is independently finite real numeric and strictly positive. CLOSED capital is finite real numeric and non-negative; missing values, bool/np.bool_, strings, complex, and non-finite values are rejected. Negative CLOSED capital is invalid; zero is valid and gives drawdown `-1.0` from a positive peak. Full ledger/capital consistency validation stays upstream. Optional columns do not affect results; no input rows, values, dtypes, columns, or index are modified, sorted, reset, or repaired.

OPEN rows, their missing capital-after values, and entry costs add no point and do not alter realized capital. Empty/OPEN-only inputs contain exactly the initial point and have zero summaries, with no NaN. Flat/increasing capital has zero drawdown; recovery to an earlier peak does not remove historical declines. This is REALIZED-CAPITAL drawdown only: it omits intratrade/unrealized losses and can understate full mark-to-market portfolio drawdown. Notebook 03 now presents these existing helper outputs through the Stage 5.6 integration.

## BTC realized-capital drawdown check

The existing local 8,760-row BTCUSDT hourly snapshot ran through the unchanged EMA20/EMA50 pipeline (50 warm-up candles), ledger, and independent gross/net accounting, then the new drawdown paths/summaries. Initial capital was 10,000 USDT; NET used `fee_rate=0.001` and `slippage_rate=0.0005` as research assumptions only, not current Bybit fees. Drawdowns are negative decimal fractions; amounts/capital use USDT. Values below are rounded for display only.

| Result | GROSS | NET |
| --- | ---: | ---: |
| CLOSED trades | 77 | 77 |
| Path rows including initial capital | 78 | 78 |
| `max_realized_drawdown` | -0.267234254550 | -0.371855332627 |
| `max_realized_drawdown_amount` | -2,672.342545499 | -3,718.553326267 |
| Minimum-drawdown observation | 33 | 66 |
| Minimum-drawdown `closed_trade_number` | 33 | 66 |
| Capital at that observation | 7,327.657454501 | 6,281.446673733 |
| Running peak at that observation | 10,000.000000000 | 10,000.000000000 |
| Final realized capital | 9,641.111388344 | 7,652.530163437 |

The maxima are -26.723425% GROSS and -37.185533% NET on these realized-capital observations. Both final path capitals equal the known final CLOSED accounting values. Removing the final OPEN row leaves each full path and summary identical; that position remains unvalued. Inputs and the raw CSV hash were preserved. Stage 5.6 notebook assertions verified the same references, OPEN exclusion, and preservation; its table and plot read from the existing helpers. These sample-specific results do not establish general strategy quality or full portfolio drawdown.

## BTC CLOSED-trade performance summary

Existing 8,760-row BTCUSDT hourly snapshot; EMA20/EMA50 with 50 warm-up candles and initial capital 10,000 USDT. NET rates are research assumptions only: 0.10% fee and 0.05% adverse slippage per side, not current Bybit fees. Return/rate values below are decimal fractions; PnL/expectancy use USDT. Values are rounded for display; implementation uses unrounded inputs.

| Metric (exact output order) | GROSS | NET |
| --- | ---: | ---: |
| `closed_trade_count` | 77 | 77 |
| `winning_trade_count` | 20 | 20 |
| `losing_trade_count` | 57 | 57 |
| `breakeven_trade_count` | 0 | 0 |
| `win_rate` | 0.259740259740 | 0.259740259740 |
| `loss_rate` | 0.740259740260 | 0.740259740260 |
| `breakeven_rate` | 0.000000000000 | 0.000000000000 |
| `average_trade_return` | 0.000070588288 | -0.002925128404 |
| `median_trade_return` | -0.008735290732 | -0.011704629367 |
| `average_win_return` | 0.038651616726 | 0.035540330361 |
| `average_loss_return` | -0.013466614673 | -0.016421780603 |
| `best_trade_return` | 0.224171061391 | 0.220504050556 |
| `worst_trade_return` | -0.043755772679 | -0.046620207277 |
| `total_realized_pnl` | -358.888611656 | -2,347.469836563 |
| `expectancy_pnl` | -4.660891060 | -30.486621254 |
| `profit_factor` | 0.945165760246 | 0.675088667158 |

The final OPEN trade is excluded and unvalued. The positive gross arithmetic average return does not imply a positive compounded result; total PnL follows actual compounded capital. These metrics describe this sample and do not establish general strategy quality or future profit.

## Environment status

- The existing parent workspace `.venv/` uses Python 3.11.17, verified before Stage 9.2 implementation. pandas 2.3.3, NumPy 2.0.2, Matplotlib 3.9.4, requests 2.32.5, and JupyterLab 4.6.4 are preserved. Stage 9.2 installed only pybit 5.17.0 and its new pycryptodome 3.24.0 dependency, with no virtualenv recreation or unrelated upgrades.
- Notebooks retain their previously validated saved executions; none was edited/re-executed and no editor kernel was changed in Stage 9.2.
- The earlier Python 3.9.6/LibreSSL environment emitted an urllib3 compatibility warning during public historical data work. Stage 9.2 performed no exchange API calls or interpreter migration.
- Git repository root: `/Users/romankondratenko/trading-lab/Trading Lab`.
- Branch: `main`, tracking `origin/main`. Initial commit: `ff57150` (`Initialize Trading Lab project`), pushed successfully to GitHub.
- Remote repository: [puckmandestroyer/trading-lab](https://github.com/puckmandestroyer/trading-lab).

## Current focus

Owner review/freeze of Stage 12.1a — Observability Event / Logging Contract / Decision 023, COMPLETE / owner review pending. Stage 12.0 is COMPLETE / FROZEN at `0b275c91abe53068dc4b0b05ade7be710d13cef6`; Stage 11 remains FROZEN at `b79d511`. Stages 12 and 12.1 are STARTED / INCOMPLETE; 12.1b–e and 12.2–12.4 are NOT STARTED; v1.0.0 NOT RELEASED.

Stage 12.1a changes only Decision 023 and three current documents. All production, tests, previous Decisions, schema, dependencies, Stage 5 EMA/next-OPEN behavior, notebooks and data/results are preserved. No observability implementation, credentials/token use, authenticated Demo/Live activity, real user migration/activation/rearm or real Telegram message.

## Not implemented yet

- Transformed datasets and reusable preprocessing workflows.
- Portfolio/multi-asset allocation, shorts, leverage, and risk-based sizing beyond the generic LONG/FLAT fixed-fraction single-position model.
- Exchange-specific or variable transaction-cost models.
- Drawdown duration/recovery and subsequent portfolio metrics.
- Additional reusable strategies beyond the EMA crossover strategy.
- Performance analytics beyond the 16 CLOSED-trade summary metrics, separate realized-capital drawdown, ledger-based duration/exposure, candle-level equity, candle-close portfolio drawdown, the aligned Buy-and-Hold comparison, and time-based returns/Sharpe/Sortino with support volatility/downside metrics; broader multi-strategy comparison.
- Order modification, operator-cancellation orchestration and actual long-running Demo activation/launch layer.
- Multiple autonomous bot instances and order management.
- Manual risk pause/kill, risk configuration editing and operational controls UI.
- PostgreSQL.
- Dashboards.
- Docker/deployment.

## Next milestone

Stage 12.1b — Structured Logs + Health Snapshot is next / NOT STARTED, requiring separate authorization after contract review/freeze. Stage 12.1a is COMPLETE / owner review pending; 12.1c–e and 12.2–12.4 remain NOT STARTED. Do not begin automatically. Stages 12 and 12.1 remain INCOMPLETE; v1.0.0 NOT RELEASED.

Real user runtime DB migration/risk activation and authenticated Demo read/order/cancellation remain NOT RUN. No approval to perform those operations follows from offline implementation or tests.

## Backtesting execution contract

- The default EMA strategy uses 50 initialization-only candles, with eligibility from candle 51. Warm-up belongs to each strategy; the generic engine has no warm-up requirement.
- Signals use only completed candle data. `signal_time` is the candle opening timestamp plus one hour.
- `desired_position` is research intent: 0 wants flat and 1 wants long. Entries require previous state 0; exits require previous state 1; HOLD preserves state.
- The first model executes a valid event from candle N at candle N+1's OPEN: `execution_time = timestamp[N+1]`, `execution_price = open[N+1]`. Same-candle-close fills are forbidden.
- `signal_time` marks information availability; `execution_time` marks the simulated action. For continuous hourly data they share the same boundary timestamp, while completion and signal availability precede execution conceptually.
- Initial simulated `executed_position = 0`. An executable LONG_ENTRY requires flat state and changes 0 → 1; LONG_EXIT requires long state and changes 1 → 0. HOLD creates no execution and leaves state unchanged. Invalid executed-state transitions must be rejected.
- A final-candle signal can change desired state but cannot execute without a next candle. Do not invent a price or force a terminal entry/exit.
- `executed_position` is now calculated in memory by the backtest helper, independently of `desired_position`. Row N records the state after any prior signal fills at N's OPEN; N's own signal cannot change that row's executed state.
- `execution_time` and `execution_price` are stored on the source signal row, not the receiving candle row. A final row can receive the prior row's fill while its own event remains unexecuted. HOLD has no execution metadata, even when a preceding event changes state at that candle's OPEN.
- The reusable generic LONG/FLAT single-position backtest pipeline composes canonical validation, next-OPEN execution, the trade ledger, and independent GROSS/NET accounting. Cost adjustments preserve recorded ledger prices and execution. Existing equity/analytics helpers compose downstream, including OPEN-position marks; persistence and broader portfolio allocation remain unimplemented.
- See `decisions/002_backtest_execution_contract.md` for definitions, causal ordering, and acceptance cases A–G, now covered by synthetic tests.

## Current limitations

The loader supports fixed minute-based Bybit intervals, not daily/weekly/monthly candles. It rejects incomplete periods instead of filling gaps. Requests have a timeout and report failures clearly, but do not retry automatically. Snapshot saving refuses to overwrite existing files. The notebook uses the fixed first-year period and restores CSV dtypes explicitly; no indicators or strategy features are stored in raw data.

Stage 2 volatility uses sample standard deviation (`ddof=1`) of hourly returns over trailing 24/168-observation windows and is not annualized. First-return and rolling-window NaNs are expected warm-up values. Drawdown uses candle closes and excludes intrahour lows; the index is BTC buy-and-hold price analysis, not a bot backtest.

Stage 3.1 keeps `ewm(span=20/50, adjust=False)` with the first close as the seed. The 50-candle warm-up is a research convention, not an EWM mathematical requirement or a guarantee that seed effects have disappeared. No entry is synthesized merely because warm-up ends in a bullish regime; the flat strategy waits for a new bullish crossover. `desired_position` is not an executed position.

The reusable EMA strategy expects hourly candle-opening timestamps and returns signal availability one hour later. It validates datetime order/uniqueness, finite positive numeric closes, and positive integer parameters with `fast_span < slow_span`. Full OHLCV and hourly continuity validation remain upstream. Default parameters preserve Stage 3.1; custom spans and warm-up are supported but have not been optimized. All derived columns remain in memory; no processed dataset or persistence is introduced.

The execution helper requires pandas datetime timestamps with continuous one-hour spacing; it preserves timezone semantics and does not sort or fill gaps. It validates allowed signals, state transitions, and finite positive OPEN prices used for fills. Full OHLCV validation remains upstream. It does not enforce a strategy warm-up or read optional `desired_position`/`signal_time` columns; it executes only supplied events.

The generic pipeline delegates canonical validation, execution, ledger construction, and independent GROSS/NET accounting to existing components, adds alignment checks, and returns in-memory results only. It supports one LONG/FLAT position with fixed-fraction allocation, defaulting to full allocation; portfolio/multi-asset allocation, shorts, leverage, risk-based sizing, live/demo exchange runtime, and multiple autonomous bots remain unimplemented. `desired_position` is intent after a completed candle; `executed_position` is the state held during that candle after any previous signal fills at its OPEN. They legitimately differ on entry/exit signal rows. Prefix stability excludes execution metadata for a former final-row event that gains a next candle; all earlier rows and shared-prefix strategy/position values remain unchanged.

The ledger consumes the full candle state table starting flat and validates its recorded fills; it does not sort malformed input, calculate fills, or value an open trade. It preserves datetime timezone semantics and returns an empty typed ledger when no entry actually executes. The candle pipeline table and trade ledger remain separate in-memory outputs. The review notebook saves displayed excerpts and plots, but exports no dataset or separate report.

Accounting assumes consecutive trade IDs from 1, chronological non-overlapping trades, and at most one final OPEN trade. It never repairs or sorts invalid ledgers. CLOSED exit prices must be strictly positive; calculated results must remain finite with non-negative capital, and impossible quantity overflow/underflow raises an error. Floating-point tolerance is used for arithmetic checks. `trade_return` is a decimal return for one CLOSED trade; `gross_pnl` is realized PnL before costs. Compounded capital after closed trades is not a mark-to-market equity curve, and OPEN trades have no realized result or valuation.

Cost-aware accounting reuses the unchanged gross helper's ledger/capital validation, including its numerical limits, then independently sizes and compounds net results. Rates must be finite real numbers in `[0, 1)`; bools are rejected. Effective prices, entry sizing, and calculated amounts must be representable as finite floats; depleted capital cannot finance another trade. Rates are fixed research assumptions, with no exchange-specific fee tiers, minimum order sizes, or rounding. Cost-aware `gross_pnl` uses recorded prices with the cost-sized quantity, so it is not the separate Stage 4.6 simulation. OPEN `total_fees` stays missing because the round trip is incomplete; its known entry fee is reported separately.

The backtest review notebook observes the fixed EMA20/EMA50, 50-candle-warm-up sample without parameter optimization, out-of-sample testing, or walk-forward validation. Its realized-capital and realized-drawdown plots use completed trade number; the separate Stage 5.12 MTM plot uses valuation time and observes within-trade CLOSE movements, including final OPEN value. TIME remains ledger-based holding-time/exposure. No general conclusion about strategy quality follows from this single sample.

Decision 003 is implemented by the Stage 5.2 summary helpers. Arithmetic average trade return is distinct from compounded strategy return. Quote-currency expectancy describes this sample, not future profit. NaN and +infinity are intentional for documented undefined/unbounded cases. These summaries aggregate existing accounting outputs; full ledger/capital consistency validation stays upstream. Decision 004 is implemented separately by the Stage 5.5 drawdown helpers, using only explicit initial capital and CLOSED capital-after observations, and presented in notebook 03 by Stage 5.6. They can miss losses while trades are open and understate full mark-to-market drawdown. Candle-close portfolio drawdown, Buy-and-Hold comparison, and decision 009 time-based returns/Sharpe/Sortino with explicit support volatility/annualization are now available separately. Decision-010 strategy-output validation is implemented; Stage 8.2 provides independent IS/OOS composition, Stage 8.3 descriptive grids, Stage 8.4 local parameter variation, and Stage 8.5 independent expanding walk-forward research. Stage 8.6 adds neutral segment/window diagnostic tables and finite-only descriptive test-window statistics. Statistical robustness conclusions remain unestablished.

Decision 005 is implemented by the Stage 5.8 ledger-based time helpers, independently of accounting, and presented in notebook 03 by Stage 5.9. OPEN exclusion from realized PnL/drawdown does not imply exclusion from observed time in market. Exposure is binary holding time for the current single-position, non-overlapping ledger. Overlapping/multi-position, leverage/size-weighted, gross/net, and short exposure remain outside this contract; no market-value risk metric is introduced.

Decision 006 is implemented by `analytics/equity.py` and presented in notebook 03 by Stage 5.12. Stage 7 extends its original all-in model with fixed partial allocation and reserve cash. The long-only single-asset model still excludes shorts, multi-asset/multi-position allocation, leverage, funding/borrow interest, dynamic fees, liquidation value, and position-size-weighted exposure. Decision 007 is implemented by `analytics/portfolio_drawdown.py` and presented in notebook 03 by Stage 5.15. Decision 009 now supplies time-based equity returns, Sharpe/Sortino, and their support volatility/downside measures. Drawdown duration/recovery, further equity-return metrics, CAGR/Calmar, alpha/beta, intrabar MAE/MFE, and further robustness diagnostics remain deferred. Independent IS/OOS composition is available through Stage 8.2, with independent expanding walk-forward research through Stage 8.5 and downstream descriptive diagnostics through Stage 8.6. The CLOSE path can still miss intrabar risk; no continuous-time or tick-level drawdown claim is supported.

## Existing files preserved

The existing five Python files in `notebooks/` and four Python files in the top-level `strategies/` are empty placeholders and remain unchanged. The existing misspelled `data/proceseed/` directory is preserved. Use `data/processed/` for new transformed datasets and `src/trading_lab/strategies/` for new reusable strategy code.
