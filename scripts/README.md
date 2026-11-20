# Utility scripts

Use this directory for small command-line utilities that call reusable code under `src/trading_lab/`.

Keep reusable logic under `src/trading_lab/` and let scripts call that code. Store original datasets under `data/raw/`, transformed copies under `data/processed/`, and generated outputs under `results/`. Credentials must come from the explicitly approved external source, never literal source-code or CLI values.

## Detached bounded Demo launcher (implemented, NOT DEPLOYED)

[Decision 027](../decisions/027_detached_bounded_demo_runtime_launcher.md) is PROPOSED / IMPLEMENTED / OWNER REVIEW REQUIRED. This task installs no LaunchAgent, loads no real credentials, opens no real store and starts no runtime. Stage 12.2b STARTED / INCOMPLETE; 24h NOT COMPLETED; 72h NOT STARTED. The commands below describe later separately authorized operations only.

`trading_lab_demo_runtime.py --help` describes explicit non-secret configuration. The runtime requires `--registry-root`, `--observability-root`, `--secret-file`, `--duration-hours`, `--start-next-hour` and `--confirm-demo-runtime`. Supply absolute paths resolved locally by the owner, never literal secrets. Use the one established canonical registry for bybit-demo/demo-main/bot1; no alternate root/identity on contention. Whole-hour durations 1–72 are capability only; current reviewed duration is 24 and each start requires fresh authorization.

`trading_lab_launchagent.py --help` describes `generate`, `install`, `status`, `start`, `stop`, `uninstall`. In addition to the runtime path/duration flags, supply an absolute `--python-executable` for the existing virtual environment and an external private `--operator-root`. No shell wrapper or PYTHONPATH environment is stored in the plist: scripts import the repository's src directly. Every operation except status requires `--confirm-management`; that flag is a deliberate invocation gate, not a substitute for owner approval or Gate G.

Later reviewed workflow: generate private plist/logs → inspect exact non-secret configuration → install/register the reviewed stopped job → separately authorize one bounded start → inspect process-only status → request graceful SIGTERM stop if needed → wait for process/sinks/lock cleanup → uninstall only when stopped. No command in that workflow is executed by this implementation task. Install never starts trading (RunAtLoad=false); completion/crash never restarts (KeepAlive=false). No `kickstart -k`, SIGKILL, automatic rearm/retry or bootout of a running job.

The runtime chooses the next UTC-hour H, waits in its own foreground process until H+8s before lock/store/credentials, then gates activation within the first minute. Absolute stop is H+duration+90s. It calls the canonical lock, existing-store-only validation, restart once, reconciliation once and fresh clock/history gates before the frozen observed scheduler. One unprotected unseen startup candle refuses activation rather than granting historical LIVE authority; see Decision027. No automatic retry on gate failure.

Private secret parent0700/file0600, current-user ownership, regular/single-link/no symlinks, outside repo; only four approved names, no expansion/sourcing/search. Values are mapped directly into frozen loaders/transports, never exported or printed. Explicit ObservabilityStorage and nested Telegram receipts remain outside repo. Operator root0700 and logs/plists0600; existing unsafe paths are refused without repair. Do not dump environments, enable shell tracing or display secret-file contents. Demo/Live separation, permission re-audit and compromise→revoke/rotate remain mandatory.

Status reads launchd process metadata/log existence only; no credentials/store/network/broker truth. GUI user session, AC power, lid-open/host-awake conditions must last through cleanup. launchd/caffeinate cannot prevent clamshell sleep or logout/shutdown. Codex/terminal lifetime no longer controls a launchd-started process, but physical downtime remains possible. Stop handlers only set an Event; frozen shutdown owns state changes. Sink draining may extend cleanup past the trading deadline without further trading authority. Never start another run to work around an unresolved cleanup or ambiguous outcome.

## Historical Stage 12.2a activation contract (COMPLETE / FROZEN)

The following section records the contract-only milestone at its completion, before the separately authorized Stage 12.2b attempts and Decision 027 capability. Its NOT STARTED/no-launcher wording is historical; it does not override the current implementation state above.

[Accepted Decision 024](../decisions/024_demo_activation_runbook_contract.md) is the canonical future Demo activation/runbook contract: **COMPLETE / FROZEN** after independent remote owner audit of reviewed substantive publication `aa479968f58bd9e1cd22864ace94176c2cf7044c`. It authorizes no request or runtime. A documentation-only closure records the independent remote audit and corrects stale pre-publication status wording without altering the accepted contract or production/trading baseline. Stage 12.1 is COMPLETE / FROZEN at production baseline e4c88c4; 12.2 STARTED / INCOMPLETE through documentation only; 12.2b–d and 12.3/12.4 NOT STARTED; Stage 12 INCOMPLETE; v1.0.0 NOT RELEASED.

Real secrets belong in owner-only external storage, conceptually `~/.config/trading-lab/demo.env`, with 0700 parent / 0600 file, current-user ownership and no symlinks. Never put values in ChatGPT/Codex, Git/GitHub, shell literal arguments/history, logs or observability/dashboard artifacts. Future approved loading requires `set +x`, no environment/file display, explicit process-environment population and no dotenv discovery. Do not create/load that file here. `.env.example` has four empty names only; .gitignore is defense in depth. Suspected exposure means STOP and revoke/rotate.

The first future authenticated operation is separately authorized **read mode only**, without place/cancel/--confirm-demo-action. This diagnostic is not the runtime. Future operational activation requires the canonical account lock/store/restart/risk preflight and **run_observed_hourly_scheduler(...)**, with explicit resources. Credentials, read success or Telegram success cannot authorize trading; Stage 12.2b requires a separate owner decision. Streamlit remains a separate credential-free localhost-only reader. No new launcher/CLI or execution of the commands below is part of 12.2a.

## Optional manual Bybit Demo smoke

`bybit_demo_smoke.py` is a bounded manual diagnostic, not a trading runtime.
[Decision 016](../decisions/016_manual_demo_smoke.md) records its activation contract.
Run commands from the project root. No mode (or `--help`) reads credentials,
constructs a session or makes a request:

```sh
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py --help
```

Only after separate owner authorization for an actual authenticated manual run,
supply `BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` in the process environment.
The script does not load `.env`, accept CLI secrets or print credentials. Demo
only: no Testnet, live route, routing overrides or implicit credential fallback.

Explicit read mode makes bounded metadata/account/open-order reads and no mutation.
Optional `--executions` adds a complete fill read using the existing default window:

```sh
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py read --symbol BTCUSDT
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py read --symbol BTCUSDT --executions
```

Actions require **additional explicit --confirm-demo-action** and every required
input; credentials alone or launching the script cannot place an order. The
following commands contain placeholders, not default order sizes or IDs:

```sh
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py place --symbol BTCUSDT --side BUY --amount AUTHORIZED_QUOTE_AMOUNT --order-link-id UNIQUE_CALLER_ID --confirm-demo-action
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py place --symbol BTCUSDT --side SELL --amount AUTHORIZED_BASE_QUANTITY --order-link-id UNIQUE_CALLER_ID --confirm-demo-action
PYTHONPATH=src ../.venv/bin/python scripts/bybit_demo_smoke.py cancel --symbol BTCUSDT --order-id EXACT_BROKER_ORDER_ID --confirm-demo-action
```

BUY implies QUOTE (USDT for BTCUSDT); SELL implies BASE (BTC). Positive exact
amounts and caller links are validated before session construction. Read-only
account connectivity must succeed before either action; balances do not determine
the amount. The script shows validated caller authorization/identifiers, then
Stage 9.5 revalidates Demo settings and fresh Stage 9.3 rules before one mutation.
Placement receipt reports the final normalized amount, not a fill. Cancellation
acceptance does not imply terminal CANCELLED state and can race with a fill.

Add `--read-after` to an action only to explicitly request one order lookup and
one complete execution read after a valid acknowledgement. Existing bounded
pagination/history fallback applies. No read-after occurs for ambiguous or
malformed acceptance. Placement never automatically cancels; cancellation is a
separate invocation. There is no retry, monitoring, reconciliation loop, sizing,
strategy wiring, persistence or local portfolio mutation.

Exit codes: 0 success/help, 2 invalid arguments or missing action confirmation,
1 safe operational/cleanup failure. Errors omit raw SDK messages/tracebacks and
authentication data. Clients close on success/failure. Unknown action outcomes
remain unknown and are never permission to blindly resubmit.

All CLI control tests use synthetic credentials and fake clients. **No actual
authenticated Demo smoke/order was executed during Stage 9.6.** Offline success
proves software contracts, not actual Demo fills or profitability. No actual
authenticated Demo smoke/order was executed during Stage 9. Stage 9.1–9.7 and
Stages 9–11 remain COMPLETE / FROZEN. Stage 12.1 is COMPLETE / FROZEN; its observed
runtime entrypoint is implemented and offline-tested but has never been activated
on a real account. Stage 12.2a is an accepted COMPLETE / FROZEN contract, not a
launcher or operational authorization; 12.2b–d remain NOT STARTED.
Do not run this tool against Demo automatically.
