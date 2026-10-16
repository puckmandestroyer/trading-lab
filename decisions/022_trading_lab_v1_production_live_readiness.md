# 022 — Trading Lab V1 Production & Live Readiness Contract

- Date: 2026-10-17
- Status: Accepted contract; Stage 12.0 COMPLETE / owner review pending.
- Scope: Architecture/documentation only; no implementation or operational activation.
- Owner-reviewed baseline: `b79d511b94fa6e5dd07f59d95e7c51f175f3f756` — `Complete Stage 11 final audit`; Stage 11 COMPLETE / FROZEN.
- Governing frozen decisions: [013](013_bybit_demo_exchange_adapter.md), [014](014_read_only_account_and_order_state.md), [015](015_spot_market_order_lifecycle.md), [016](016_manual_demo_smoke.md), [017](017_demo_trading_runtime_contract.md), [018](018_runtime_risk_management.md), [019](019_runtime_risk_journal_schema.md), [020](020_runtime_risk_gate_authorization.md), [021](021_runtime_risk_rearm_operator_controls.md), unchanged.

## Authority, release boundary and current status

Stage 12 — Production & Live Readiness is the final top-level stage for the first release, **Trading Lab v1.0.0**. Completing Stage 12 is the release gate. The repository is currently **pre-v1 / Stage 12 in progress**, not a released v1.0 product.

| Stage / release | Status after 12.0 |
| --- | --- |
| Stage 11 — Runtime Risk Management | COMPLETE / independently owner-reviewed / FROZEN at `b79d511b94fa6e5dd07f59d95e7c51f175f3f756` |
| Stage 12 — Production & Live Readiness | STARTED / INCOMPLETE |
| 12.0 — V1 Production & Live Readiness Contract | COMPLETE / owner review pending |
| 12.1 — Observability & Operator Visibility | NOT STARTED |
| 12.2 — Long-Running Bybit Demo Validation | NOT STARTED |
| 12.3 — Local V1 Hardening | NOT STARTED |
| 12.4 — Controlled Live Validation | NOT STARTED |
| v1.0.0 | NOT RELEASED |

This decision governs future Stage 12 work only. It does not implement observability, Telegram, Streamlit, Demo activation, deployment or Live trading. It authorizes no credential access, authenticated broker operation, real database operation or release tag. Each implementation milestone needs its own narrow reviewed scope; operational authorization is separate. Do not start 12.1 automatically.

Historical Stage numbers, prior Decisions and completion-time records remain unchanged. Earlier roadmap labels are superseded only for future Stage 12 planning by the roadmap below; no feature is backdated into Stage 11.

## Trading Lab v1 product profile

The initial v1 operational target is:

| Dimension | V1 boundary |
| --- | --- |
| Host | Local macOS execution |
| Instances / identity | One runtime instance, one Bybit account binding, one bot |
| Strategy | Only the existing EMA strategy, EMA20/50 with its frozen warm-up/timing contracts |
| Instrument / interval | One symbol: BTCUSDT; hourly timeframe `60` |
| Trading | Spot, LONG / FLAT, MARKET only |
| Storage | SQLite RuntimeStore |
| Visibility | Telegram outbound alerts; local read-only Streamlit dashboard |
| Risk | Existing fixed-budget Stage 11 runtime policy |

Cloud deployment, Docker and PostgreSQL are not v1 requirements and may be post-v1 work. The current implementation remains Demo-only. The Live target below requires a separately reviewed 12.4a exchange/safety contract and subsequent approvals; it is not permission to bypass frozen Demo routing, add a live switch or repurpose Demo credentials now.

### Frozen implementation boundaries

Build around Stage 11 rather than redefining planner semantics, execution timing, risk accounting, trip/rearm semantics, RuntimeStore schema v2, exactly-once logical authorization/action lifecycle or reconciliation ownership. Exactly-once logical decisions do not promise exactly-once exchange delivery; an unknown broker outcome remains uncertain, with no blind resend.

Keep strategy intent, planner proposal, durable risk authorization, broker acknowledgement, executions and reconciled ownership distinct. Existing Stage 9 APIs, Stage 10 safety/recovery and Stage 5 EMA/backtest/next-OPEN regressions remain frozen. Any necessary future production correction needs its own narrow reviewed milestone, not an implicit exception in this contract.

### Fixed risk policy

V1 retains fixed operator-authorized `risk_capital_quote`, fixed planner `buy_quote_budget`, and risk vetoes without resizing. Existing exact Decimal invariants, bot-owned cash/inventory accounting, authoritative hourly closed-candle marks, daily-loss/drawdown trips, daily ENTRY counts and explicit independent rearm controls remain authoritative under Decisions 018–021.

Wallet size, deposits or profits cannot automatically enlarge allocation or BUY budget. Stage 7 `position_fraction` remains historical/research only. V1 does not introduce 0.5% risk-per-trade sizing, Kelly sizing, ATR sizing, stop-distance sizing, portfolio-volatility sizing or dynamic compounding. Risk-per-trade sizing is post-v1 and requires a reviewed stop-distance/exit-risk model first.

### Future strategies and risk domains

Additional strategies may be researched/backtested independently, but new runtime strategies are POST-v1 and cannot enter the v1 execution runtime merely as Stage 12 work. Future bots may reuse the same risk-engine code, while each bot/strategy retains its own RiskState, RiskBook, epoch history, PnL, drawdown and daily ENTRY count:

```text
Strategy A bot → same risk-engine code → independent state/book/epochs
Strategy B bot → same risk-engine code → independent state/book/epochs
Strategy C bot → same risk-engine code → independent state/book/epochs
                                      ↓
                         future global portfolio risk layer
```

Independent strategies must not share one strategy-level RiskState or silently offset each other's profit/loss. Portfolio allocation and global risk above those independent domains remain POST-v1.

## Non-authoritative observability

Telegram is outbound notification delivery. Streamlit is a read-only operational/statistical dashboard, local-only by default. Neither is an execution-control surface. No Telegram command or Streamlit button may place/cancel an order, rearm runtime/risk, change configuration, force liquidation or start Live trading in v1. Operator mutation remains separately reviewed explicit local runtime/CLI controls.

Existing RuntimeStore and broker reconciliation remain trading truth. Logs, structured events, derived snapshots, JSONL or read-only SQLite views are derived observability, never a second authority for authorization or ownership recovery. Stage 12.1 defines exact artifact formats, delivery/restart behavior and access patterns; this decision chooses no new schema, API, sidecar authority or event framework.

### Telegram outbound events

Required v1 event classes:

- Runtime started; runtime stopped normally.
- Position confirmed OPEN; position confirmed CLOSED.
- RISK_TRIPPED; Runtime HALTED.
- UNCERTAIN / ambiguous action requiring attention.
- Successful explicit rearm; critical runtime failure.

Avoid HOLD/hourly-no-op spam. Trade alerts describe durable confirmed truth. A signal, proposal, risk ALLOW or order ACK is insufficient to claim a position opened. OPEN requires durable reconciled owned exposure; CLOSED requires durable reconciliation confirming bot-owned exposure is flat. Optional lower-priority partial-fill alerts must not be mislabeled completed OPEN/CLOSED finality.

A confirmed trade alert should be capable of showing, when durably known: bot, symbol, event type, side, owned quantity, execution price/exact reconciled fill summary, fee, timestamp, runtime state and risk state. A close alert may include derived realized trade PnL only if exactly reconstructable from owned durable execution history. Never invent PnL from ACK/requested amounts or wallet totals; unavailable facts remain explicitly unavailable.

Telegram is non-authoritative. An outage must never authorize/duplicate an order, alter policy, clear HALT/TRIP or change durable ownership. Delivery failure cannot retroactively invalidate an already safe durable trading transaction. Observability failures must remain visible locally. No RuntimeStore SQLite transaction may span Telegram/network I/O.

### Streamlit read-only dashboard

Required top-level views: **Overview; Position / Orders; Risk; Trades; Runtime Health; Event / Error History**. Show durable/derived facts and explicit unavailable/stale information rather than fabricating current success. No control button changes trading state.

| View | Required information |
| --- | --- |
| Overview | Bot, symbol, runtime state, risk trip status, current owned position, latest mark, risk equity, daily PnL, drawdown from active epoch peak, entries used/daily limit, last processed candle, last reconciliation, pending-action status, uptime/current process health where available. Wallet assets are not bot risk equity. |
| Position / Orders | Durable owned exposure and known order/action status, including pending/partial/unknown outcomes; acknowledgements remain distinct from fills and terminal evidence. |
| Trades | Durable bot-owned execution history and reconstructed completed LONG trade cycles: entry/exit times, entry/exit fills, quantity, fees and realized result where exactly derivable. No synthetic trades from signals. |
| Risk | risk_capital_quote, buy_quote_budget, max entry/position caps, daily-loss/drawdown thresholds, daily ENTRY limit; risk equity, epoch peak, daily baseline/PnL, current drawdown/count, trip reason/time and current epoch. Historical trip/rearm lineage remains inspectable when child epochs exist. |
| Runtime Health | Runtime state, last scheduler/cycle activity, last processed candle/reconciliation, pending action, last broker observation, HALTED reason, UNCERTAIN if present, latest critical observability/error event. |
| Event / Error History | Derived event/error history with locally visible observability failures; it never replaces durable trading history. |

## Stage 12 roadmap and phase gates

All implementation milestones below are NOT STARTED at Stage 12.0 completion. Review each phase's evidence before advancing; the contract itself grants no operational permission.

### 12.1 — Observability & Operator Visibility

| Milestone | Scope | Status |
| --- | --- | --- |
| 12.1a | Observability Event / Logging Contract | NOT STARTED |
| 12.1b | Structured Logs + Health Snapshot | NOT STARTED |
| 12.1c | Telegram Outbound Alerts | NOT STARTED |
| 12.1d | Streamlit Dashboard | NOT STARTED |
| 12.1e | Observability Offline Regression + Audit | NOT STARTED |

Implementation/testing uses local/synthetic data and is expected to require no authenticated Bybit account or API credentials. No real Telegram token/message is authorized by offline implementation. Stage 12.1 chooses exact observability implementation without weakening frozen trading contracts.

### 12.2 — Long-Running Bybit Demo Validation

| Milestone | Scope | Status |
| --- | --- | --- |
| 12.2a | Demo Activation / Runbook Contract | NOT STARTED |
| 12.2b | Controlled 24h → 72h Demo Run | NOT STARTED |
| 12.2c | Restart / Network / Failure Validation | NOT STARTED |
| 12.2d | 7-day Demo Soak + Report | NOT STARTED |

This is the first Stage 12 phase requiring real authenticated Bybit Demo credentials, only for separately authorized execution. No authenticated Demo action precedes explicit owner authorization at the appropriate milestone. Credentials alone do not authorize operation.

Required progression is **short authenticated smoke → 24 hours → 72 hours → 7 days**. Start each later duration only after preceding evidence is reviewed. A few minutes is not a soak. Keep the Mac awake and time-synchronized during declared windows; suspended/asleep periods are reported as downtime, never counted silently as successful continuous operation.

Inspect scheduler cadence, market freshness, Bybit read reliability, broker reconciliation, order lifecycle, partial fills where encountered, restart, HALT/TRIP, Telegram alerts, Streamlit visibility, database growth/integrity, log growth and memory/process stability. An unencountered partial-fill case is not observed external evidence.

Hard execution invariants remain:

```text
duplicate automatic send = 0
blind resend = 0
unauthorized action = 0
automatic forced liquidation = 0
automatic rearm = 0
```

External outages may legitimately HALT or require intervention. Record them and their consequences rather than hiding failures to meet a zero-error target. Offline tests alone do not establish real-exchange or continuous-runtime reliability.

### Credentials and Demo boundary

Introduce Demo credentials only for authorized 12.2 execution. Never commit API keys, secrets, .env, credentials or tokens. The repository may contain only non-secret templates/examples. A local ignored environment file or later hardened local secret mechanism may supply v1 secrets; exact hardening is defined in 12.3. Do not print/log secrets or raw credential-bearing payloads.

Use minimum necessary Demo API permissions, no withdrawal permission and no transfer permission unless separately proven necessary and authorized. Retain fail-closed Demo routing and existing no-blind-retry semantics. This milestone does not load credentials or create an authenticated session.

### 12.3 — Local V1 Hardening

| Milestone | Scope | Status |
| --- | --- | --- |
| 12.3a | Local Operator CLI | NOT STARTED |
| 12.3b | Configuration + Secret Hardening | NOT STARTED |
| 12.3c | Local Process Supervision / Startup | NOT STARTED |
| 12.3d | Backup + Log Rotation + Recovery | NOT STARTED |
| 12.3e | Local Deployment Audit | NOT STARTED |

Target local macOS and SQLite; no required cloud, Docker or PostgreSQL migration. Define database location, filesystem permissions, backup procedure, tested restore, log rotation, disk-space expectations and single-instance startup. Backup/restore cannot erase sent-intent/ownership evidence or bypass frozen reconciliation; review recovery before enabling actions.

The future local CLI should expose safe existing capabilities: status, start Demo runtime, request graceful stop, reconciliation/diagnostic read where permitted, explicit Runtime HALT rearm, explicit risk rearm and health. Exact commands and safeguards are reviewed later. No generic arbitrary SQL/config mutation or force-liquidate command is part of v1.

Graceful stop remains conservative: stop scheduling, preserve exposure/pending work and exit. **Stopping the application does not SELL, cancel all, clear trip or rearm.** Controls retain independent HALT/TRIP semantics and all frozen freshness/ownership/persistence checks. For controlled Live, emergency manual exchange intervention remains an explicit out-of-band operator action unless a separately reviewed in-app emergency-close contract is later approved; this decision invents no such capability.

### 12.4 — Controlled Live Validation

| Milestone | Scope | Status |
| --- | --- | --- |
| 12.4a | Live Exchange / Safety Contract | NOT STARTED |
| 12.4b | Live Read-Only Validation | NOT STARTED |
| 12.4c | Exact Live Dry-Run / Preflight | NOT STARTED |
| 12.4d | First Explicit Tiny Live Order | NOT STARTED |
| 12.4e | Tiny-Capital Live Runtime Validation | NOT STARTED |
| 12.4f | Final Stage 12 / V1 Audit + Release | NOT STARTED |

No Live operation is authorized by Decision 022. Every mutation milestone requires separate explicit owner authorization. Future Live capability requires its own reviewed environment/exchange boundary; frozen Demo APIs cannot be silently rerouted.

Live credentials must be separate from Demo, minimally privileged and without withdrawal permission. Prefer a dedicated bot key over a broadly privileged personal key. Stage 12.3 secret handling must be satisfied before the first Live mutation.

Required ordering:

```text
Live public/read-only
→ authenticated account/order read-only
→ reconciliation validation
→ exact dry-run/preflight
→ explicit owner authorization
→ one tiny real order
→ reconcile/verify
→ only then tiny-capital autonomous validation
```

Never jump from offline tests to autonomous Live trading. No arbitrary dollar amount is hardcoded here: the first Live runtime needs deliberately small, separately reviewed risk_capital_quote and buy_quote_budget compatible with exchange minimums and frozen risk invariants. This is not 0.5%-of-wallet sizing; wallet size cannot automatically increase allocation.

## V1 release criteria and final audit

Tag `v1.0.0` only after **12.1, 12.2, 12.3 and 12.4a–e are COMPLETE / FROZEN**, **12.4f final V1 audit is PASS**, and no unresolved safety blocker remains. Do not create a release/tag in 12.0.

The independent 12.4f audit must inspect frozen Stages 1–11 research/runtime history, Stage 12 observability, Demo soak evidence, local deployment/runbook, secret handling, Live read-only evidence, tiny Live mutation evidence, risk/execution invariants, golden regressions and current limitations. Only then may documentation call the project **Trading Lab v1.0.0**. Until then use **Trading Lab v1** for this product boundary and **pre-v1 / Stage 12 in progress** for repository status.

## Deliberately POST-v1

Unless separately promoted through review, v1 excludes multiple live strategies, multiple autonomous bots, portfolio/global risk management, multi-symbol portfolio risk, dynamic 0.5% risk-per-trade sizing, stop-distance/Kelly/ATR/portfolio-volatility sizing, dynamic compounding, short selling, leverage, margin, futures, options and FX.

PostgreSQL, cloud deployment and Kubernetes are POST-v1; Docker is not required for v1 and may be post-v1. Automatic liquidation, risk-generated stop loss/take profit, trailing stop, Telegram trading commands, Streamlit trading controls and a full operator web UI are excluded. Additional strategy research remains independent and does not expand the v1 runtime/release requirement.

## Stage 12.0 preservation, verification and operations

Exactly four Markdown files change: this Decision 022, PROJECT_STATE.md, README.md and CHANGELOG.md. Production, tests, schema, dependencies and previous Decisions have zero changes; notebooks, historical data/results, financial/next-OPEN behavior and frozen runtime/risk contracts are preserved. No code/tests, framework installation, real database operation or implementation of 12.1 is included.

The unchanged full local suite must pass **2,943 tests**, zero failures/errors/skips, with `pip check`, `git diff --check` and `git diff --staged --check`. These are local regression results, not external operational evidence. Commit/push is authorized after validation, normally to main without force push or history rewrite.

```text
Demo API credentials: NOT USED
Live API credentials: NOT USED
Authenticated Bybit Demo read/order/cancel: NOT RUN
Authenticated Bybit Live read/order/cancel: NOT RUN
Real user DB migration/activation/rearm: NOT RUN
Real Telegram bot message: NOT SENT
```

Stage 12.0 is COMPLETE / owner review pending; Stage 12 remains INCOMPLETE and v1.0.0 NOT RELEASED. Stage 12.1 — Observability & Operator Visibility is next and must not start automatically.
