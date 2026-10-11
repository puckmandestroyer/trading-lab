# 016 — Explicit, bounded manual Demo smoke

- Date: 2026-10-10
- Status: Accepted
- Scope: Stage 9.6 manual diagnostic CLI and secret-safe SDK diagnostics; no runtime.
- Reviewed baseline: `9508eb659a22b55b5d5674bac7714ec0ea6de330`.
- Governing decisions: [013](013_bybit_demo_exchange_adapter.md), [014](014_read_only_account_and_order_state.md), [015](015_spot_market_order_lifecycle.md), unchanged.

## Why this decision exists

Decision 013 permits an optional opt-in manual Demo smoke. A command that can
make an explicitly authorized order action needs a stable activation boundary.
Integration tests alone do not need another architectural decision.

`scripts/bybit_demo_smoke.py` calls the existing Stage 9 APIs. It adds no exchange
API, broker parsing, sizing policy, persistence, scheduler, polling or retry loop.
Historical Decisions 010–012, Stage 5 EMA values and next-OPEN timing stay frozen.

## Activation and modes

Run from the project root with `PYTHONPATH=src` and the existing Python environment.
No mode (or `--help`) shows help, reads no credentials, constructs no client and
makes no request. Import also has no side effects. Credentials alone never
authorize an action.

| Mode | Required arguments | Bounded behavior |
| --- | --- | --- |
| read | `--symbol` | Metadata, account and complete open-order reads. Optional `--executions` adds one complete execution read. No action adapter is constructed. |
| place | `--symbol --side BUY\|SELL --amount --order-link-id --confirm-demo-action` | Verify read-only account connectivity, show caller authorization, then one Stage 9.5 Spot Market placement. |
| cancel | `--symbol --order-id --confirm-demo-action` | Verify read-only account connectivity, show the exact identifier, then one Stage 9.5 cancellation request. No placement. |

Actions require the additional explicit flag. Symbol, side and amount have no
defaults. CLI validation precedes credential loading/client construction.
Placement requires a caller-owned 1–36-character link; uniqueness remains the
caller’s responsibility. Cancellation requires the exact broker order ID.
There are no credential, routing, order-type, leverage or arbitrary SDK flags.

BUY amount is QUOTE authorization; SELL amount is BASE authorization. The CLI
derives that unit solely from the explicitly supplied side. It never derives an
amount from the account or converts quote/base quantities. Stage 9.5 fetches
fresh Stage 9.3 rules and performs exact normalization/constraints before any
mutation. The displayed request is authorization; the receipt reports the final
normalized submitted amount.

Optional `--read-after` on either action explicitly requests one order lookup
and one complete execution read after a valid acknowledgement. Existing bounded
pagination/history fallback remains Decision 014 behavior, not polling. No
read-after runs when placement/cancellation acceptance is ambiguous or malformed.
Placement never automatically cancels; cancellation acceptance never chooses
terminal status. The caller must invoke cancellation separately.

## Demo, diagnostics and failure safety

Reuse only Stage 9.2 Demo-specific environment names and its central factory.
Adapters retain fixed Demo routing, one-attempt settings and disabled request
logging; unsafe configuration fails before broker calls. No Testnet/live option,
automatic fallback, ID generation or resend exists.

An offline integration probe found pybit 5.17.0 emits raw `retMsg` and HTTP
response text through its logger even with `log_requests=False`. The factory
therefore supplies each client its own disabled standard-library logger. It
does not disable/configure the shared SDK/root logger, change constructor kwargs,
retry policy, error classification or any public API. This is the sole genuine
integration-bug exception to frozen production code. Adapters still expose safe
operation/code/type diagnostics. Real SDK mocked-send regressions cover the leak.

The CLI prints normalized models and validated operator parameters, never raw
responses, credentials, headers, signatures, client repr or SDK exception text.
Argument errors do not echo rejected values. Failures report an error class and
nonzero exit; action parsing/transport uncertainty is labeled unknown with no
automatic resend or follow-up read. Clients close on success/failure; cleanup
errors also produce safe diagnostics and nonzero exit. Nothing persists.

## Verification and authorization

Tests invoke CLI control logic only with synthetic environment values and fake
clients; no authenticated Bybit request occurs. Cross-component tests explicitly
invoke each lifecycle observation and use production parsing/normalization.
These tests prove software contracts, not Demo fill behavior, execution quality,
strategy profitability or production readiness.

No actual authenticated Demo smoke/order was executed during Stage 9.6. A future
manual run requires separate explicit owner authorization; providing this tool
or passing tests is not that authorization.

Stage 9.1–9.6 are COMPLETE. Stage 9 remains INCOMPLETE. Stage 9.7 — Final Stage 9
Audit + Docs is next and NOT STARTED; Stage 10 is NOT STARTED.
