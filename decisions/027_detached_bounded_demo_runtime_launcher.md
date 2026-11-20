# 027 — Detached Bounded Demo Runtime Launcher

- Date: 2026-11-20
- Status: **ACCEPTED / COMPLETE / FROZEN** after owner implementation review PASS / ACCEPTED FOR FREEZE: YES.
- Launcher implementation: **COMPLETE / OWNER-REVIEWED / FROZEN** at substantive implementation baseline `72076768d66deaffd5bb457da810f163d947566d` — `Implement detached bounded Demo runtime launcher`.
- Software capability: **IMPLEMENTED / NOT DEPLOYED.** Real LaunchAgent: **NOT INSTALLED**. Real detached runtime: **NOT STARTED**. 24h detached run: **NOT STARTED**.
- Pre-implementation baseline: `e8a2cbeaa45f8673f90cb99a702367dddd51d4cc`.
- Decisions 001–026 and frozen runtime, risk, exchange, strategy, observability, schema and dependencies remain unchanged. Decision 027 adds only the detached operator/launchd boundary.
- Stage 12.2b: **STARTED / INCOMPLETE**. The 24h run is **NOT COMPLETED**; 72h is **NOT STARTED**. Stage 12 remains INCOMPLETE; v1.0.0 NOT RELEASED.

## Owner acceptance and documentation freeze closure

The owner verdict is **DECISION 027 IMPLEMENTATION OWNER REVIEW: PASS / ACCEPTED FOR FREEZE: YES** for `72076768d66deaffd5bb457da810f163d947566d`, parent `e8a2cbeaa45f8673f90cb99a702367dddd51d4cc`. This subsequent four-file documentation-only closure records that acceptance; it does not replace the substantive implementation baseline or change any accepted API, architecture or behavior.

The accepted chain remains **macOS LaunchAgent → thin runtime script → trading_lab.operator.demo_runtime → canonical RuntimeAccountLock → existing frozen RuntimeStore/recovery/reconciliation → run_observed_hourly_scheduler**. KeepAlive=false / RunAtLoad=false; no periodic trigger, automatic crash restart, automatic risk rearm, migration, HALT clearing, ambiguous-action repair or Live trading. launchd supplies process supervision only, never trading authority. Closing Codex/terminal or exhausting usage limits does not intentionally terminate a launchd-started runtime process.

Accepted risk-trip semantics remain distinct:

| Condition | Frozen behavior |
| --- | --- |
| Pre-existing trip at a new process activation | OWNER REVIEW; launcher refuses automatic activation. |
| Trip during an already-running scheduler | Does not automatically HALT the scheduler; latch remains. |
| New ENTRY with active latch | Blocked according to frozen policy. |
| Valid exact strategy EXIT from confirmed LONG | May remain authorized under Decisions 018/020 and every operational guard. |
| Automatic emergency SELL / automatic rearm | NONE / NONE. |

This closure installs no LaunchAgent, invokes no launchctl, acquires no real lock, opens no real RuntimeStore, accesses no credentials and performs no broker/Telegram, runtime or order operation. The earlier operator-session 24h attempt remains NOT COMPLETED; a **detached** 24h run has NOT STARTED. Installation and any bounded real run require separate explicit owner authorization after review. Acceptance is software freeze, not deployment or operational validation.

## Problem and chosen boundary

Earlier Stage 12.2 operator runs were launched from a Codex/tool process. Their lifetime could depend on the terminal or tool session. The preceding 24h attempt did not establish a completed 24h validation: captured progress and stop timing were insufficient. This task does not reopen its store, diagnose its physical downtime or resume it.

Use this process boundary:

```text
macOS per-user launchd LaunchAgent
  → scripts/trading_lab_demo_runtime.py
  → trading_lab.operator.demo_runtime
  → canonical RuntimeAccountLock
  → existing RuntimeStore / prepare_process_restart / reconcile_startup
  → existing run_observed_hourly_scheduler
```

Once launchd starts the process, Codex/ChatGPT is not its parent authority. Closing Codex, a terminal or reaching usage limits does not intentionally stop it. launchd provides process supervision only. Trading authority still comes from the frozen runtime contract and an explicitly owner-authorized bounded run. A logged-in GUI user session is required; a LaunchAgent does not survive logout, reboot or host shutdown as a continuing trading run.

Implemented capability ≠ installed service ≠ authorized trading run. Review/freeze, installation, credential access, permission re-audit, Gate G and run authorization are separate decisions. This implementation authorizes none of those real operations.

## Non-goals

No Live trading, Docker, cloud deployment, Linux systemd, Kubernetes, permanent autonomous daemon, wallet-sized sizing, new strategy/risk/exchange logic, automatic rearm/reset, HALT clearing, ambiguous-order repair, migration, automatic crash restart or periodic trading activation. No KeepAlive trading or perpetual RunAtLoad trading. No dashboard auto-launch.

## Public operator surface

`trading_lab.operator.demo_runtime` exposes frozen `DemoRuntimeConfiguration`, `StartBoundary.NEXT_HOUR`, `DemoRuntimeResult`, `OperatorError`, `load_demo_secret_file(path)`, `run_demo_runtime(configuration, *, utc_now, monotonic, stop_event)` and `runtime_main(argv)`.

Configuration contains non-secret absolute `Path` objects for `registry_root`, `observability_root`, `secret_file`, a whole integer `duration_hours` in **1–72** (bool rejected), NEXT_HOUR policy and fixed identity labels. Relative paths, parent traversal, control characters, repository private-storage paths, overlapping storage and alternate identities are rejected. The upper bound is software capability, not authorization for a 72h run. Current reviewed use remains 24 hours; each invocation needs fresh concrete owner authority. Paths are explicit, never inferred from an environment dump or discovered `.env`.

`trading_lab.operator.launchd` exposes `LaunchAgentConfiguration`, `generate_plist`, `write_launchagent`, `LaunchAgentManager`, `LaunchAgentStatus`, `LaunchctlResult`, `launchctl` and `launchagent_main`. Scripts only make the repository's `src` importable and call these reusable CLI functions. Importing a module or requesting help never starts a runtime or installs a job.

## Frozen deployment profile and durable identity

Only `bybit-demo / demo-main / bot1 / ema_trend`, BTCUSDT / BTC / USDT, timeframe `60`, interval 3600000 ms is supported. Exact expected profile: EMA20/50, warmup50, quote budget Decimal10, decision/observation freshness60000, max skew6000, request timeout10000, reconciliation timeout600000, rounds5, reads3, schema2/runtime contract1, no broker account ID override.

The operator supplies the same approved canonical registry root used by all cooperating runtimes, conceptually `~/.trading-lab-state/runtime-registry`; no fallback/alternate root is selected. Identity labels cannot select another account or bot. Canonical locking remains the authority, with no unlinking, stealing, killing another runtime or alternate binding on contention.

`RuntimeStore.open(..., initialize=False)` requires the exact configuration in advance. Under the already-held canonical lock, the new wrapper reads only the singleton identity row through SQLite `mode=ro`, using the canonical `lock.database_path` and the existing frozen decoder. The read is bounded, closes immediately, checks file custody/identity before and after, and refuses SQLite sidecars for owner-reviewed recovery. It does not issue mutation PRAGMAs or custom UPDATE/INSERT/DELETE. This deliberately narrow dependency on the frozen private identity decoder avoids a second Decimal/JSON decoder or frozen API change.

Both opaque durable digests and the existing history anchor are recovered unchanged. No runtime-manifest encoding or digest derivation is invented; risk-content hashing remains the separate frozen risk contract. All named profile fields must match before a normal existing-store open/full validation and exact configuration read comparison. Missing, corrupt, mismatched or legacy stores fail; no database creation, initialization, repair or migration occurs.

Require existing frozen risk records for capital100 USDT, budget10, maximum entry10, maximum position10, daily loss0.05, drawdown0.10, three entries per UTC day and BTC/USDT. Epoch/configuration/valuation identity must agree. Missing risk state, changed envelope, existing trip/pending trip report, HALTED/UNCERTAIN/ORDER_PENDING, retained unsafe stopped-from state, pending action, unknown ownership or nonterminal durable action refuses activation for owner review. No latch is cleared. This launcher intentionally does not automate ambiguous-action recovery.

## Secret custody

The supplied `secret_file` may point to the approved external `~/.config/trading-lab/demo.env`, resolved explicitly by the future operator without committing a username. Require current-user-owned parent0700/file0600, regular single-hard-link file, no symlink component, outside the repository. Unsafe existing storage is refused without chmod/repair. Bounded descriptor reading verifies stable file identity and contents; errors are fixed diagnostics without source lines/values.

Parse only BYBIT_DEMO_API_KEY, BYBIT_DEMO_API_SECRET, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Each appears exactly once with a non-empty value. Blank lines/full comments and unambiguous quoted values are accepted; unknown/duplicate/malformed/missing/whitespace-ambiguous assignments, interpolation and command substitution are rejected. This is assignment data, never sourced/evaluated. No dotenv or implicit discovery; no process-environment loading/fallback. An explicit mapping goes to the frozen credential loader. The mapping's repr omits values; Python memory is not claimed securely erased.

No secret values enter config repr, CLI arguments, plist, environment, result JSON, SQLite or log messages. SDK diagnostic suppression and the frozen Telegram private diagnostics remain intact. Dedicated clients disable environment proxy/netrc use; subprocesses receive only PATH/LC_ALL. Do not enable shell tracing, dump environments, display secret files or capture exception locals. Secret creation/loading is forbidden in this implementation task. Suspected exposure requires revoke/rotate, not merely Git cleanup. Demo/Live separation and Decision 025 permission restrictions remain unchanged.

## One-process lifecycle

1. Install SIGTERM/SIGINT handlers whose only action is `stop_event.set()`. Select the next UTC-hour boundary H using an explicit aware UTC clock, then set the absolute deadline **H + duration hours + 90 seconds**.
2. Start only this process's `caffeinate -i -w <own-pid>` child. Require it alive, its idle-sleep assertion registered, AC power, lid open and the current active console user. Foreground Event waiting targets H+8 seconds for publication settling. No lock, store, credentials or authenticated resources before H. Stop during waiting exits without operational activation.
3. Recheck host conditions and the first-minute activation window. Start a non-daemon absolute-UTC deadline controller, acquire the canonical lock, validate private directories and the existing identity/store/risk/state. Lock contention exits before credential/client construction.
4. Call `prepare_process_restart(store)` exactly once. A persistence exception is indeterminate: no retry, follow-up trading read/write, abandonment, repair or resource re-open.
5. Load the explicit external secret mapping; construct the frozen Demo session, read/order adapters, public reader, ObservabilityStorage and Telegram transport/receipt store. Telegram receipts remain beneath the frozen observability instance. No separate receipt root.
6. Call one startup `reconcile_startup`. Only FLAT/CONFIRMED or LONG/CONFIRMED without pending action/reason permits continuation. No scheduler on HALT, uncertainty or conflict. Reconciliation itself remains frozen and bounded.
7. Perform one public clock gate: server minus local request midpoint has absolute skew ≤6000, server lies within the expanded request interval, UTC and monotonic request durations agree within that bound. No retry-until-pass or clock correction. Then obtain one complete closed-history prefix through the frozen reader (which takes its own authoritative server-time sample and bounded pages). Enforce context/coverage/continuity, freshness ≤60000, exact durable OHLCV overlap and sufficient frozen candle capacity for the run. Fresh reconciliation, latest close and local activation must still fit the first minute. No timing bound is relaxed.
8. The scheduler immediately processes startup history using frozen classifications. A single unseen startup candle unprotected by durable bootstrap/replay cutoff is refused: the frozen cycle otherwise could classify it LIVE. Zero backlog, multiple unseen candles or an already protected singleton follow frozen behavior; the wrapper never edits cutoffs or reserves historical candles as new LIVE authority. This fail-closed edge case requires later owner-reviewed activation, not retry-until-pass.
9. Invoke **only `run_observed_hourly_scheduler`**, exactly once, with the same stop Event and explicit resources/clocks. No custom strategy/planner/risk/order loop. A risk trip during this running scheduler remains latched: ENTRY blocked; valid exact owned-base strategy EXIT may remain legal; trip alone does not stop the scheduler. No emergency SELL, liquidation, cancellation or rearm.
10. At deadline the non-daemon controller sets stop once. Invalid controller clock fails closed by setting stop. SIGTERM/SIGINT request the same frozen graceful shutdown; no DB/broker work in handlers. Exceptions/indeterminate scheduler outcomes cause no compensating trading action, follow-up state read/write, reopen, retry or resend.
11. Cancel/join the controller; retain all sink/session/store/lock resources until a frozen observability worker actually exits, including after its normal two-second drain times out. Close Telegram then Demo HTTP clients, close the store, release the lock last among operational resources, terminate/reap only this process's caffeinate, and restore signal handlers. Cleanup can exceed the trading deadline while sinks finish; that grants no new trading authority. A hung worker can delay exit and requires owner review. Do not force bootout a running job to rush cleanup. Cleanup errors return failure without secret-bearing exception text.

Normal STOP_REQUESTED returns exit0; other scheduler exits/refusals/errors/cleanup failures return nonzero. Safe JSON reports control outcome, window, checkpoint sequence and counts, never broker payloads. Exit0 is process-control evidence, not proof of complete operational validation. Physical sleep, scheduling latency or unexpected timing still require owner audit.

## LaunchAgent management contract

One per-user label: `com.tradinglab.demo-runtime`, domain `gui/<current uid>`. Pure plist generation returns bytes; explicit `generate` writes a reviewable private local plist/log files. No machine-specific plist is committed.

Required plist: Label, ProgramArguments array, WorkingDirectory, StandardOutPath, StandardErrorPath, **RunAtLoad=false**, **KeepAlive=false**, ProcessType=Background; Umask077 protects newly created process files. No EnvironmentVariables, shell, credentials, StartInterval/Calendar, restart/SuccessfulExit/ThrottleInterval rules or other activation trigger.

Use an explicitly supplied absolute virtual-environment Python path and the repository's thin script. Program arguments include only non-secret roots/path, duration and explicit runtime confirmation. Do not replace the reviewed configuration casually between runs. The non-secret secret-file *path* is allowed in the plist; its content is never copied there.

Operator root is explicit, outside repository and separate from runtime/observability/secret storage. Existing parent must be private0700; root0700, stdout/stderr and generated plist0600, current-user owned, no symlinks/hardlink aliases. Existing unsafe paths fail without repair; existing generated/installed plists are not overwritten. Logs are private and may grow during a bounded run; no new log-rotation daemon is introduced.

Local launchctl help/man documentation was inspected. All calls use argument sequences, `shell=False`, fixed verbs/current GUI target, minimal subprocess environment, timeout and sanitized failure. Boundary is injectable for offline tests:

- `generate`: private files only, no launchctl mutation.
- `install`: verify exact generated plist, require confirmed-unloaded job, write its user Library/LaunchAgents plist and `bootstrap gui/<uid> <plist>`. RunAtLoad=false means registration only. Failed bootstrap leaves the local artifact for owner review, no repair/retry.
- `status`: `print gui/<uid>/<label>`; report only loaded/running/PID/last exit and log existence, never open logs, credentials, RuntimeStore or network or infer broker truth. Unsupported/error output yields UNKNOWN, not fabricated stopped/success.
- `start`: require confirmed loaded/stopped job and exact installed plist, then `kickstart <target>` with **no -k**. New start is new bounded run authority, never routine automatic restart.
- `stop`: require confirmed running job; `kill SIGTERM <target>` only. Do not use bootout to stop a trading process or send SIGKILL. The signal does not promise immediate cleanup completion.
- `uninstall`: refuse running/unknown status; verify exact installed plist, `bootout <target>` only when stopped, then remove only that plist. Keep generated review copy/logs. No lock unlink or DB operation.

Management has no retry/restart loop. The canonical lock arbitrates simultaneous starts even if process-status observation races. This is cooperative single-user supervision, not protection against a hostile user replacing trusted files or issuing independent launchctl commands. Status's human-readable launchctl parsing is conservative and macOS-version-dependent; UNKNOWN requires owner review.

## Sleep and crash limitations

LaunchAgent and caffeinate do **not** guarantee operation with the Mac lid closed. Clamshell sleep remains downtime. Current Stage 12.2 runs require lid open, AC power, host awake and user session available for the whole bounded run and cleanup; startup checks do not continuously prove these physical conditions. Do not treat launchd as a sleep remedy or as 24h completion evidence.

On crash, launchd does **not** restart. OS process exit releases the canonical descriptor lock; durable state remains for later owner-reviewed recovery. Never automatically rearm, recover ambiguous orders, resume the prior window or start a replacement run. Logout/OS termination may prevent graceful shutdown; frozen persistence/recovery still governs the next separately authorized process.

## Validation and deployment boundary

At the substantive implementation baseline, offline tests used temporary directories, synthetic values, temporary SQLite fixtures, fake resources/clocks/events, mocked SDK/network and an injected launchctl runner. No owner RuntimeStore, secret file, real launchd mutation or external request was used. Frozen production, schemas, dependencies and Decisions 001–026 remained byte-for-byte unchanged. The existing preservation test selected its documented frozen 001–026 range, retaining the same aggregate hash. Decision 027's freeze is the explicit owner acceptance above; no test or preservation hash changes in this closure.

Accepted prior **local-only** evidence at `72076768d66deaffd5bb457da810f163d947566d`: **99 focused operator tests / 3,521 full-suite tests passed**, failures/errors/skips **0/0/0**, full-suite duration **548.553 seconds**. Frozen-boundary audits, both CLI help checks, pip check, git diff --check and secret/scope review PASS. **CI evidence: NONE CLAIMED.** No tests or pip check are rerun for this documentation-only closure; its validation is exact diff/scope, whitespace, secret and status-consistency review. Publication is not service installation or trading authorization. Decision 027 is ACCEPTED / COMPLETE / FROZEN; launcher implementation COMPLETE / OWNER-REVIEWED / FROZEN at the substantive baseline above. Real LaunchAgent NOT INSTALLED; real detached runtime and 24h detached run NOT STARTED.
