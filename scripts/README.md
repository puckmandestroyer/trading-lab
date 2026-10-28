# Utility scripts

Use this directory for small command-line utilities that call reusable code under `src/trading_lab/`.

Keep reusable logic under `src/trading_lab/` and let scripts call that code. Store original datasets under `data/raw/`, transformed copies under `data/processed/`, and generated outputs under `results/`. Credentials must come from environment variables.

## Stage 12.2a activation contract (COMPLETE / FROZEN)

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
