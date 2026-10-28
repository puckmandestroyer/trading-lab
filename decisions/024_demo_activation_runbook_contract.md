# 024 — Demo Activation / Runbook Contract

- Date: 2026-10-26
- Status: **Accepted / Stage 12.2a COMPLETE / FROZEN after independent remote owner audit.**
- Scope: Contract/runbook only. Every operational step below is a future requirement, not an instruction to execute now.
- Reviewed substantive publication baseline: `aa479968f58bd9e1cd22864ace94176c2cf7044c` — `Define Stage 12.2a Demo activation runbook`; parent `d66aa7b8175992fbd2779f56fbd720ae308b5295` — `Complete Stage 12.1 final audit`.
- Frozen Stage 12.1 production baseline: `e4c88c4408d85386c7081c94a2871952f03bf41f` — `Capture accepted reconciliation transitions`; COMPLETE / FROZEN.
- Governing frozen contracts: [016](016_manual_demo_smoke.md), [017](017_demo_trading_runtime_contract.md), [018](018_runtime_risk_management.md), [019](019_runtime_risk_journal_schema.md), [020](020_runtime_risk_gate_authorization.md), [021](021_runtime_risk_rearm_operator_controls.md), [022](022_trading_lab_v1_production_live_readiness.md), [023](023_observability_event_logging_contract.md), unchanged.

## Authority and explicit non-actions

Stage 12.2 is STARTED / INCOMPLETE through this accepted contract only. Stage 12.2a is **COMPLETE / FROZEN** after publication and independent remote owner audit. Stages 12.2b, 12.2c, 12.2d, 12.3 and 12.4 remain NOT STARTED. Stage 12 overall remains INCOMPLETE; v1.0.0 remains NOT RELEASED.

Credentials being configured, authenticated read success and Telegram success do **not** authorize trading. Only a later explicit owner authorization for **Stage 12.2b controlled Demo run**, with concrete configuration, risk values, permitted operations, start/stop window and stop conditions, permits the observed runtime to place Demo orders under frozen strategy/risk logic. Do not automatically advance between steps or durations. Contract review/freeze and operational authorization are separate decisions.

This milestone creates no launcher, operator CLI, daemon, launchd job, Docker setup, dependency, schema or production change. It does not construct clients, authenticate, make public/network/DNS preflights, load or discover credentials, open a real runtime DB, migrate/activate/rearm a real journal, start runtime/Streamlit or send Telegram. No secret file is created, inside or outside the repository. No home-directory search, Keychain, shell-history, existing-environment, browser-storage, Telegram or Bybit-account inspection is permitted here. Tests use existing local synthetic fixtures/fake transports and temporary databases only.

The substantive contract was published by normal fast-forward push at the reviewed baseline above. Its acceptance authorizes no operation by itself. A subsequent documentation-only closure records the independent remote audit and corrects stale pre-publication status bookkeeping without altering the accepted contract or production/trading baseline.

## Secret custody and process boundary

Real credentials must **NEVER** be pasted into ChatGPT, Codex prompts, GitHub issues/PRs, commits/messages/tags/releases, README, Decisions, PROJECT_STATE, CHANGELOG, tests, fixtures, terminal commands as literal arguments, shared debugging screenshots, logs, JSONL, health.json, Streamlit or Telegram receipts. Never ask the owner to paste a secret into chat. Never put credential values or API-key identifiers in Git. Only these variable names and empty template assignments belong in the repository:

```text
BYBIT_DEMO_API_KEY=
BYBIT_DEMO_API_SECRET=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

The owner eventually obtains a key specifically for the Bybit **Demo Trading** account/mode and a Telegram bot token directly through Telegram/BotFather. Telegram chat ID is private local configuration even though it is not equivalent to the bot token. Do not invent usable-looking example credentials. Demo and Live secrets are separate: Stage 12.2 accepts only Demo credentials, with **no missing-Demo → Live fallback**. Live credentials belong solely to separately reviewed Stage 12.4.

Prefer an owner-only secret file **outside the repository**, conceptually `~/.config/trading-lab/demo.env`. Resolve its actual home location locally; never commit the owner's concrete absolute home path. Require parent mode **0700**, file mode **0600**, ownership by the current user, a regular unaliased file and no symlink components. Provision new private storage only during separately approved preparation. Unsafe existing ownership/permissions/symlinks FAIL activation; startup must not silently chmod, replace or repair them.

The tracked `.env.example` contains only four empty values. `.gitignore` already ignores `.env` and `.env.*` with `!.env.example`; keep those protections. An ignored project-root `.env` is defense in depth, **not the primary custody mechanism**; real Stage 12.2 secrets should remain outside the Git tree entirely. Do not create one in this milestone.

During future approved secret loading, require **`set +x` first**. Never enable `set -x` while secrets are present. Enter values with a local editor or another non-history mechanism; never type literal-value `export` assignments into shell history or pass credentials as CLI arguments. Do not use `env`, `printenv`, bare `set`, `ps e` or equivalent environment dumps, debugger/local-variable captures or process-environment serialization. Do not display the secret file with `cat demo.env`, `head demo.env`, `tail demo.env` or secret-matching grep commands.

Future verification checks only: file exists; owner is current user; private parent/directories; file mode 0600; exactly the approved required names are present and non-empty; Demo profile is deliberately selected. Output is PASS or FAIL plus affected path, never values or matching lines. Treat the file as assignment data, not arbitrary executable shell code; do not eval/source unreviewed content. The later reviewed activation caller must specify its explicit non-history loading mechanism before operation. No loader or secret-verification tool is implemented here; stronger tooling belongs to 12.3b.

The frozen Stage 9 `load_bybit_demo_credentials()` consumes only `BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` from the explicit mapping/process environment; there is no automatic `.env` discovery. Preserve that API. No python-dotenv/dependency or implicit repository loading is added. A future approved caller places only necessary values into the runtime process, supplies Telegram token/chat ID explicitly to its transport, and closes resources/ends the secret-bearing process after use. No credential is copied into RuntimeConfiguration, SQLite, instance identity/digests, observability, dashboard state or notification content.

## Demo routing, permissions and Telegram boundary

The authenticated/order session must come from `create_bybit_demo_session(...)` with frozen safety settings:

```text
testnet=False
demo=True
REST origin = https://api-demo.bybit.com
force_retry=False
max_retries=1
retry_delay=0
log_requests=False
```

Keep the client-local disabled SDK logger. No live `api.bybit.com` trading, `api-testnet.bybit.com`, Demo-on-Testnet, route override or credential fallback. Grant only permissions required for approved Demo reads/Spot trading, no unrelated permissions or withdrawal/transfer capability. The exact current Bybit permission UI must be rechecked by the owner at credential-creation time; this contract guesses no checkbox names and verifies no current external UI. No production/live trading key is acceptable.

Keep the separate frozen `BybitPublicMarketReader` for unauthenticated market time/Kline reads. Its fixed public `https://api.bybit.com/v5/market/time` and `/v5/market/kline` GET endpoints do not permit live-money routing: no authenticated session or credentials enter that reader. They are future authorized public reads only; **no public request is executed in 12.2a**.

The caller explicitly constructs a dedicated Telegram HTTP session and `TelegramHttpTransport` with token/chat ID; Telegram code discovers no environment. The origin stays `https://api.telegram.org`, with only its fixed sendMessage boundary. Transport repr/str omit token/chat ID; events contain neither, and receipt state stores a target hash rather than raw chat ID/token. Never log the token-bearing Bot API URL, auth/signature/request headers, raw environment, SDK/client repr, response dump or arbitrary traceback/exception context. Use only frozen sanitized operation/code/type diagnostics. No Telegram component changes here.

A future connectivity smoke authorizes **at most one non-trading test notification/application dispatch**, never a fabricated OPEN/CLOSE or trading event. Do not mutate RuntimeStore to manufacture an alert. Exact smoke implementation/execution needs later review and explicit authorization. Keep frozen bounded HTTP delivery behavior; best-effort notification delivery is not exactly-once. An ambiguous notification outcome stops for review, not repeated manual sends or an extra retry loop. Telegram failure never resends a broker action or changes trading truth.

## Private local state and canonical account lock

Before any future activation, choose explicit absolute owner-only local paths outside the Git repository for RuntimeStore SQLite, the account registry/lock, observability root, Telegram receipt state and operator logs. No actual owner's path is committed here. Require private 0700 directories and 0600 state/log files, current-user ownership, safe regular files and no symlink aliases; do not silently fix existing paths during startup. Use local durable storage, not a shared/network/cloud-sync registry. Keep the Mac awake and time-synchronized during declared windows; sleep is recorded downtime.

All cooperating operational runtime processes use **one canonical registry root and stable bybit-demo/account_binding identity**. `RuntimeAccountLock` derives its account lock and database path; DB/bot choices cannot select a second lock to evade it. For every actual runtime activation, restart or operational preflight that opens RuntimeStore or constructs authenticated runtime resources, acquire the canonical OS account lock first. No authenticated operational runtime client may be constructed before that lock. A competing lock fails before runtime broker calls. Hold the same descriptor until every store closes; never unlink/recreate the lock, rely on its existence/PID as authority or bypass it with another registry/account label. The separately authorized standalone Stage 9 read-only diagnostic below opens no RuntimeStore and does not claim to acquire or satisfy this runtime lock.

`ObservabilityStorage` uses its explicit private root and hashed instance directory; `TelegramDeliveryStore` remains bound to that instance and destination hash. Receipt storage lives beneath that observability instance, not in a new trading database. No state/log files belong in source, notebooks, datasets/results or staging. These derived artifacts never authorize orders or recover ownership.

## Exact runtime and risk preflight

The later owner-approved non-secret manifest must bind broker `bybit-demo`, strategy `ema_trend`, BTCUSDT/BTC/USDT, timeframe `60`, interval 3,600,000 ms, Spot LONG/FLAT MARKET, no borrowing/leverage/shorts. Verify stable account_binding, bot_id, optional genuinely verified broker-account binding, strategy implementation/configuration digests, exact EMA20/50 parameters and 50-candle warm-up, history anchor, schema v2/runtime contract v1. A caller-provided Stage 9 account_id is **not** an independently verified broker UID; confirm the correct Demo profile without pretending that label verifies it.

Explicitly review every Stage 10 time/read field: decision_max_age_ms, observation_max_age_ms, reconciliation_timeout_ms, reconciliation_round_limit, read_attempt_limit, request_timeout_ms and max_clock_skew_ms. No guessed deployment values, automatic relaxation or changing the historical/bootstrap/replay cutoffs on restart. Validate the RuntimeConfiguration before passing it to `RuntimeStore.open`; afterward validate its exact equality with loaded durable configuration.

Owner approval must supply every Stage 11 value, with no operational defaults:

```text
risk_capital_quote
buy_quote_budget
max_entry_notional_quote
max_position_notional_quote
max_daily_loss_fraction
max_drawdown_fraction
max_entries_per_utc_day
```

Use exact Decimal values, a positive integer ENTRY limit and exact runtime/risk BUY-budget/currency binding. Preserve `0 < buy_quote_budget <= max_entry_notional_quote <= max_position_notional_quote <= risk_capital_quote`, `0 < max_daily_loss_fraction <= 1` and `0 < max_drawdown_fraction <= 1`. First Demo exposure should be deliberately small relative to available virtual capital; **this contract chooses no amount**. No wallet-derived sizing, percentage-of-wallet allocation, Kelly, compounding, 0.5%-risk sizing or Stage 7 position_fraction. USD wallet aggregates are not spendable USDT or bot-owned risk capital.

Risk uses the durable owned execution book and authoritative accepted hourly closed CLOSE, never ACK/requested amounts, wallet totals or invented PnL. An active coherent risk journal is mandatory before LIVE decisions. Empty tables mean RISK_NOT_READY, not risk-off permission; migration is not activation. If either a runtime HALT latch or risk trip is present at activation, STOP and require a separate explicitly owner-reviewed rearm procedure under Decision 021. Never automatically invoke either rearm operation. This activation gate does not change the frozen running policy: a risk trip blocks ENTRY but may permit a genuine exact owned-base strategy EXIT under all operational guards; it never generates liquidation or clears HALT.

## PASS/FAIL activation gates

Every gate requires an explicit recorded PASS before dependent work; UNKNOWN/missing evidence is FAIL, not an invitation to guess. Record only safe non-secret identifiers, approved configuration/digests, times, test totals, outcomes/reasons and artifact references in a private operator audit record.

| Gate | PASS requirements / authority |
| --- | --- |
| A — Repository | Owner-reviewed expected published revision/baseline verified; worktree understood; no unexpected code changes. This accepted contract is not a released activation entrypoint. |
| B — Secrets | Approved external private file, 0700 parent, 0600 regular owned file, required names present/non-empty, no value displayed, correct Demo-only profile and no Live-key fallback. |
| C — Local state | Safe private absolute directories, canonical lock obtainable, exact runtime/risk configuration consistent with durable identity. Inspect path metadata before opening; SQL access requires the lock. |
| D — Offline software | Relevant/full frozen regressions and pip check pass; no unreviewed production drift from e4c88c4. No credentials or external requests to prove this gate. |
| E — Telegram connectivity | A later separately owner-authorized one-notification non-trading smoke; no RuntimeStore/trade fabrication. NOT RUN in 12.2a. |
| F — Authenticated Bybit read | A later separately owner-authorized standalone read-only smoke provides diagnostic connectivity/normalized-read evidence only, not runtime startup, identity, reconciliation or risk readiness. Operational authenticated reads/reconciliation must occur under the canonical runtime account lock with the exact RuntimeStore/configuration checks. Standalone smoke success cannot satisfy those gates or grant Gate G. Neither boundary is executed in 12.2a. |
| G — Demo mutation/runtime | Separate explicit Stage 12.2b authorization, exact approved risk/configuration, coherent durable initialization/restart, bounded run window and stop policy. E/F success or configured secrets cannot grant G. NOT RUN in 12.2a. |

Gate letters are identifiers, not permission to execute in table order: the planned sequence is **separately authorized standalone read-only connectivity diagnostic → review → separately authorized Telegram smoke → review → operational activation preflight under the canonical account lock → exact RuntimeStore/configuration/risk/reconciliation checks → separate explicit Stage 12.2b mutation/runtime authorization (Gate G)**. The standalone smoke is not part of the lock-held runtime process, and Gate F success alone never grants Gate G. Failure stops progression. Recheck timing/freshness at actual use; an earlier PASS cannot replace frozen final send-time checks.

## Canonical future activation ordering

This sequence specifies a future reviewed operational runtime caller, separate from the earlier standalone Stage 9 connectivity diagnostic. It is not a new launcher or an executable command provided by 12.2a. Connectivity smokes are separately authorized, bounded operations, not a way to start runtime early or satisfy its lock/identity/reconciliation/risk gates.

1. Verify the reviewed repository revision and unchanged frozen production baseline (Gate A/D).
2. Verify explicit private runtime directories and canonical registry path without creating/repairing unsafe existing state.
3. Verify secret custody/permissions/non-empty approved names without printing values; disable tracing before approved explicit process loading (Gate B).
4. Acquire the canonical account lock before any store/client construction.
5. Open/initialize RuntimeStore only in the explicitly approved fresh/existing mode, using the already validated RuntimeConfiguration; never auto-initialize on open failure.
6. Validate the loaded exact RuntimeConfiguration and schema/identity/configuration digests against the approved manifest.
7. Validate exact Stage 11 risk configuration and existing journal status; no default limits or automatic risk activation/rearm (Gate C).
8. For an existing process restart, call `prepare_process_restart(store)` once before external resources. It preserves action/fill/epoch history and inherited HALT, and restores LAST_KNOWN/UNKNOWN rather than claiming confirmed exposure.
9. Construct the frozen Bybit Demo session through its central credentials/session boundary with the approved Demo profile only.
10. Construct `BybitDemoReadOnlyAdapter` for normalized bounded account/order/execution reads.
11. Construct `BybitDemoOrderAdapter` only for the separately approved runtime scope; construction is not permission to call a mutation.
12. Construct the separate credential-free `BybitPublicMarketReader`.
13. Construct `ObservabilityStorage` at the explicit private root.
14. If Telegram is approved/enabled, construct a dedicated HTTP session, `TelegramHttpTransport` and matching `TelegramDeliveryStore` explicitly. Supply both transport and receipts or neither. A disabled/missing pair cannot count as successful Telegram validation.
15. Perform approved operational preflight under the already-held canonical account lock: the operational client's first authenticated operation is READ ONLY; verify exact RuntimeStore identity, account binding and reconciliation, accepted closed history/freshness/clock, and the fresh-vs-restart risk prerequisites below. Earlier standalone diagnostic evidence cannot replace these runtime checks. Operational read/preflight requests need their own prior approval; Gate G must be approved before the trading invocation. No network/file sink belongs inside a RuntimeStore transaction or the durable send boundary.
16. Invoke **`run_observed_hourly_scheduler(...)`**, supplying store, market reader, read-only broker, Demo order adapter, stop signal, explicit UTC/monotonic clocks, a separate observability UTC-millisecond clock, storage and any approved Telegram pair. Do not use raw `run_hourly_scheduler(...)` for operational runs; it remains for tests/internal components.
17. If desired and separately approved, launch Streamlit in a **separate credential-free process**, bound only to **127.0.0.1**. It reads derived health/JSONL artifacts, never RuntimeStore/SQLite or broker APIs. Runtime must not spawn Streamlit. Do not inherit secret-bearing runtime environment into the dashboard; no credentials or trading controls enter it.
18. At the approved bound or stop condition, request graceful scheduler stop through the supplied stop signal; do not add a timer daemon/CLI here.
19. Close caller-owned external resources, then RuntimeStore, then release the canonical lock last. Respect the observability worker lifetime described below.
20. Preserve the DB/journal, consumed IDs, fills, latches, logs and derived artifacts for private audit and next restart; never clean state to make a run look successful.

## Fresh activation versus restart

| Mode | Required future procedure |
| --- | --- |
| Fresh | Explicitly approved new state/namespace with no missing earlier bot history. `RuntimeStore.open(..., initialize=True)` refuses every existing database file; failure never selects another empty fallback. Establish safe confirmed FLAT/LONG through frozen reconciliation and persist accepted authoritative bootstrap candles without historical sends. A new bot owns no arbitrary pre-existing BTC. |
| First risk activation | With explicit approved risk values, complete durable owned history, an existing accepted candle/close, safe confirmed FLAT/LONG and no unresolved work, invoke the once-only `initialize_risk_journal(...)` at the approved boundary. Its exact book must match current confirmed ownership and cannot hide later retained fills. This is a separate approved local write, not migration, rearm or an automatic scheduler feature. |
| Restart | Acquire the same lock, open the existing store with `initialize=False`, validate exact binding/epochs, call `prepare_process_restart(...)`, then reconcile original action IDs and catch up required history/risk accounting before future LIVE decisions. Preserve deadlines/budgets, entry counts, book/peak/baselines and all latches. No new epoch or fresh bootstrap extension. |
| Legacy schema / broken history | STOP. Schema-v1 migration is a separately owner-reviewed offline operation under Decision 019; it leaves empty risk tables and grants no trading permission. Unknown/malformed/missing history is not migrated/repaired/reset here. |

The future activation caller must demonstrate its bounded **read-only reconciliation / historical bootstrap → explicit risk initialization → observed scheduler** setup before trading. Do not start the mutation-capable scheduler to guess setup, inject private SQL, manufacture checkpoints/candles or bypass RISK_NOT_READY. These setup/activation tools are not implemented by this document. If frozen public APIs cannot prove a prerequisite, stop for a separate narrow review rather than improvise a workaround.

Never delete/recreate a DB, reset a checkpoint/frontier, clear actions/fills/risk latch, change account namespace or reset deadlines to “fix” restart. Lost ACK/unknown order outcome remains uncertain; recover only the original durable IDs through accepted broker observations, never blind resend. Partial fills preserve exact owned quantity; cancel ACK is not terminal cancellation, and order ACK is not fill. Graceful shutdown/restart never adopts wallet assets or queues historical signals. Historical next-OPEN backtests and Stage 5 EMA values remain frozen.

## First read smoke and controlled progression

### A — Standalone Stage 9 read-only connectivity diagnostic

After separate explicit owner authorization and safe process-environment loading, the existing bounded standalone diagnostic's **read mode only** is suitable for the first authenticated connectivity check, from the project root, only while the trading runtime is fully stopped and no other process is operating this bot/account runtime:

```sh
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py read --symbol BTCUSDT
```

This command is documented, **NOT EXECUTED** here. The frozen Stage 9 script has no RuntimeAccountLock integration: this standalone diagnostic does **not** claim to hold or satisfy the runtime account lock and is not part of the lock-held operational runtime process. It performs bounded metadata/account/open-order reads, closes its client and exits. It opens no RuntimeStore, creates no trading journal, constructs no action adapter in read mode and requests no placement/cancel. No `place`, `cancel` or `--confirm-demo-action` may be present; no amount/link is invented. Optional execution-history reads require explicit scope approval and retain bounded-window limits; an empty read is not proof of no historical fill. Do not modify the smoke script to add locking in this milestone.

Successful standalone output proves only bounded authenticated Demo connectivity / normalized read behavior. It is **NOT RuntimeStore activation, NOT runtime reconciliation, NOT a scheduler invocation and NOT trading authority**. It does not satisfy the runtime startup lock gate, RuntimeStore identity gate, reconciliation gate, risk readiness or trading authorization. Verify the correct Demo profile, review only sanitized normalized output privately, then stop for review; do not infer operational readiness from it.

### B — Lock-held operational runtime activation / restart

For every actual runtime activation, restart or operational preflight that opens RuntimeStore or constructs authenticated resources for the operational runtime, the canonical **RuntimeAccountLock MUST be acquired first**. Then and only then: open RuntimeStore → validate exact configuration/risk state → prepare_process_restart when applicable → construct authenticated runtime broker/adapters → reconcile → invoke run_observed_hourly_scheduler only after its separate authorization and all gates pass. No operational runtime client may be constructed before the canonical lock. This preserves frozen Decision 017 semantics; the standalone diagnostic neither holds nor replaces that lock.

The planned 12.2b progression is:

```text
separately authorized standalone read-only connectivity diagnostic
→ review
→ separately authorized Telegram smoke
→ review
→ operational activation preflight under canonical account lock
→ exact RuntimeStore/config/risk/reconciliation checks
→ separate explicit Stage 12.2b mutation/runtime authorization
→ explicitly authorized short bounded observed-runtime smoke
→ review preserved artifacts
→ explicitly authorized controlled 24h run
→ review
→ explicitly authorized controlled 72h run
```

Each mutation-bearing step requires its own explicit owner authorization; no automatic duration escalation. Record actual start/end UTC, stop reason, sleep/downtime/outages, placement/ACK/fill distinctions, owned inventory, risk state and missing observations. Do not invent success, fills or profitable results. Stage 12.2c reserves restart/network/Telegram/market-data/ambiguous-action/process-restart validation; Stage 12.2d reserves the separately approved **7-day Demo soak**. Neither is implemented or started here.

## Shutdown, failures and audit evidence

Graceful stop stops scheduling/new actions, preserves durable STOPPING with exposure/pending work and exits. It does **not** SELL, cancel all, force FLAT, clear HALT/TRIP, rearm or make a broker order terminal. Frozen strategy EXIT remains distinct from a stop command. Runtime HALT or risk trip requires review, never automatic latch clearing. Rearm is a separate explicit operation under Decision 021 and cannot be hidden in activation.

An exception/indeterminate attempt commit is not a normal stop result: preserve the original failure and frozen prohibition on further trading reads/writes, abandonment or resend in that failed invocation. Do not attempt a compensating shutdown write or infer whether the broker received an order. Close resources according to frozen ownership rules; only a later approved lock-held reopen/reconciliation determines durable truth. No auto-restart/recovery loop is added by the runbook.

The observed wrapper has a 64-batch non-blocking queue and bounded two-second daemon drain. The caller must retain sink/Telegram resources until any timed-out worker actually finishes; a join timeout is not proof the worker stopped. Do not race session closure against it or expand this into indefinite automatic retry. Preserve evidence and require review if clean resource shutdown cannot be established. Store/lock authority is never handed to the worker.

Use safe diagnostics and derived JSONL/health artifacts, not raw environment/SDK dumps. Observability remains non-authoritative: multi-version gaps fail closed; a crash before an ephemeral adjacent transition may leave unrecoverable OPEN/CLOSE history; best-effort Telegram may duplicate; risk-equity history remains sparse. Missing trade PnL stays None/unavailable. RuntimeStore plus accepted broker reconciliation, not Telegram/dashboard/logs, remains trading truth. Deleting derived artifacts cannot change authorizations.

Preserve the frozen offline golden **54 decisions / 2 placements / 2 fills / 0 cancellations / 1 risk epoch**, exact financial/next-OPEN behavior and accepted Stage 12.1 event/trade visibility. These regression counts are not a target or promise for real market conditions, which may produce different signals/fills or none.

## Secret incidents and future Git gate

Any reasonable possibility of exposure through Git/GitHub, chat, shared screenshot, terminal output, logs, traceback or clipboard-sharing error means: **STOP activation; treat the secret as compromised; revoke/rotate it; require a replacement before continuing**. Do not print the suspected value during investigation. A deletion/revert or history “clean-up” does not make the old credential safe. Do not rewrite Git history and keep using it. History remediation, if needed, is a separate owner-reviewed operation after revocation, not permission to resume.

Before any future commit/push while real credentials exist locally, require a secret-sanity gate: approved secret files outside the repository/ignored; only explicit reviewed paths in staging; no credential values or API-key identifiers in tracked/staged content; no generated runtime/SQLite/observability/receipt state staged. A future approved scanner must keep values in private memory, never CLI arguments, and emit only **PASS** or **FAIL + affected path**, never matches, snippets or secret-bearing diff lines. Stronger scanner/tooling belongs to 12.3b, not this milestone. A FAIL blocks Git publication and invokes the exposure policy where applicable.

Prohibit broad staging `git add .`, `git add -A` and `git commit -a` during credential work; later authorized commits stage reviewed paths explicitly only after this gate. GitHub PRs/issues, commit messages, tags and release notes may contain no secret. Contract acceptance grants no Git or operational authorization. Do not inspect existing owner credentials to audit this documentation.

## Stage 12.2a acceptance, publication and closure verification

The independent remote owner audit of `aa479968f58bd9e1cd22864ace94176c2cf7044c` passed the substantive contract, standalone diagnostic versus lock-held operational runtime distinction, credential custody, Demo/Live separation and separate Stage 12.2b authorization boundary. It confirmed remote main at that commit, exact parent `d66aa7b8175992fbd2779f56fbd720ae308b5295`, one commit beyond that parent and exactly six expected documentation/template paths. Production, tests, frozen Decisions 001–023, dependencies and schema had zero changes; `.env.example` contained only four empty credential assignments. The audit found only stale pre-publication status wording, addressed by this documentation-state closure.

Completion-time local validation remains **3,368 passed**, zero failures/errors/skips; pip check, diff checks and secret review passed, as recorded in PROJECT_STATE.md and CHANGELOG.md. This is local evidence only. The independent remote owner audit observed GitHub combined statuses `[]` and workflow runs `[]`: no CI execution evidence. Publication used a normal fast-forward push. No operational validation is implied.

The documentation-only closure changes only this Decision, README.md, PROJECT_STATE.md, CHANGELOG.md and scripts/README.md; `.env.example` and all production/test/frozen-Decision/dependency/schema files remain unchanged. It records the independent remote audit and corrects stale status wording without altering the accepted contract or establishing a new production/trading baseline. Closure verification uses diff checks and repository-only secret review; the full suite was not rerun for this documentation-only correction. No credential creation/loading or inspection outside the repository is part of the closure.

Completion-time operational non-actions for Stage 12.2a and its documentation-only closure:

```text
Real credential files created: NO
Real credentials loaded: NO
Real credentials displayed: NO
Real credentials written to repository: NO

Telegram API request: NOT RUN
Bybit public request: NOT RUN
Bybit authenticated request: NOT RUN
Bybit Demo mutation: NOT RUN
Bybit Live request: NOT RUN
Real runtime: NOT RUN
Streamlit runtime monitoring: NOT RUN
Real DB migration/activation/rearm: NOT RUN

```

Stage 12.2a is COMPLETE / FROZEN at its reviewed substantive publication baseline. Stage 12.2 remains STARTED / INCOMPLETE; Stage 12 overall remains INCOMPLETE. Stage 12.2b requires separate explicit owner authorization and must not begin automatically. Stage 12.1 remains COMPLETE / FROZEN; Stages 12.2b–d, 12.3 and 12.4 NOT STARTED; v1.0.0 NOT RELEASED.
