# Utility scripts

Use this directory for small command-line utilities that call reusable code under `src/trading_lab/`.

Keep reusable logic under `src/trading_lab/` and let scripts call that code. Store original datasets under `data/raw/`, transformed copies under `data/processed/`, and generated outputs under `results/`. Credentials must come from environment variables.

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
proves software contracts, not actual Demo fills or profitability. Stage 9 remains
INCOMPLETE; Stage 9.7 is next/NOT STARTED and Stage 10 is NOT STARTED.
