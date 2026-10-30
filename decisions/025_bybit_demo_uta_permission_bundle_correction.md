# 025 — Bybit Demo UTA permission-bundle compatibility correction

- Date: 2026-10-30
- Status: **Proposed / owner review pending / not frozen.**
- Scope: Additive operational compatibility clarification for Stage 12.2 Bybit Demo Trading, virtual Demo funds and the frozen local V1 Spot runtime only. No implementation or operational authorization.
- Repository baseline: `98db2c588bc4fd633549a02c5a54d1b397787d5e` — `Close Stage 12.2a documentation state`; documentation bookkeeping only.
- Stage 12.2a remains COMPLETE / FROZEN at reviewed substantive publication baseline `aa479968f58bd9e1cd22864ace94176c2cf7044c`. Stage 12.1 remains COMPLETE / FROZEN at production baseline `e4c88c4408d85386c7081c94a2871952f03bf41f`.
- Frozen Decisions 001–024, including [024](024_demo_activation_runbook_contract.md), are unchanged. This proposal requires owner acceptance before the exception can be used; it does not relax the existing permission gate while pending.

## Context and sanitized activation evidence

Decision 024 requires: “Grant only permissions required for approved Demo reads/Spot trading, no unrelated permissions or withdrawal/transfer capability.” That remains the preferred least-privilege requirement. Use a Spot-only grant whenever the current Demo profile permits it.

The owner supplied only these sanitized facts from an owner-authorized Stage 12.2 pre-mutation permission audit:

```text
SECRET CUSTODY: PASS
KEY TYPE: READ-WRITE
SPOT TRADE PERMISSION: YES

additional non-empty permission groups observed:
ContractTrade
Derivatives
Options

no order placement occurred
no order cancellation occurred
the authenticated client was closed
```

The owner observed that the current Bybit Demo UTA permission UI did not allow selecting only Spot for this key and instead bundled the broader trading selection. This is activation evidence for that observed Demo profile/UI, not a universal claim about every Bybit account, UI version or future permission configuration. This documentation task made no broker request and did not independently inspect the key or its response.

Earlier in the Stage 12.2 activation sequence, the owner replaced the diagnostic Read-Only key with a new Read-Write Demo key. That owner-reported operational change is distinct from this documentation task, which did not perform or inspect the replacement.

No API key, secret, API-key identifier, user/account UID, note/remark, address, expiry date or raw response is retained here. The issue is excess Demo permission scope, **not a credential leak incident**. Preparing this proposal alone does not require revoking the existing key. Any actual exposure still requires STOP and immediate revoke/rotate under Decision 024.

## Official permission vocabulary

The official [Get API Key Information documentation](https://bybit-exchange.github.io/docs/v5/user/apikey-info), checked on 2026-10-30, defines the authenticated read endpoint `GET /v5/user/query-api`. It describes `uta=0` as a regular account and `uta=1` as a unified trading account; `readOnly=0` means Read and Write and `readOnly=1` means read-only. Its relevant permission groups are:

| Group | Documented permission values / meaning |
| --- | --- |
| Spot | SpotTrade |
| ContractTrade | Order, Position |
| Options | OptionsTrade |
| Derivatives | DerivativesTrade |
| Wallet | AccountTransfer, SubMemberTransfer, SubMemberTransferList, Withdraw: account/subaccount transfer or withdrawal authority |

This field vocabulary does not prove that a given UI must bundle those groups. The observed bundling above comes from the owner's activation audit. Do not copy the documentation's example credentials, routing examples or raw response into an operational procedure.

## Proposed fail-closed Demo permission gate

Only if the current Bybit Demo UTA profile unavoidably bundles the additional trading groups with required Spot Read-Write authority may this narrow exception be considered after owner acceptance. It is not a general weakening of least privilege and does not apply to Stage 12.4 Live.

Require all of the following for the exact active Demo key:

- `uta == 1`, `readOnly == 0` and Spot contains `SpotTrade`. The UTA condition binds this exception to a unified trading account, not to every Bybit Demo account globally.
- Both fields must be present and valid documented integers. Missing/malformed `uta`, `uta != 1`, missing/malformed `readOnly`, `readOnly != 0` or missing `SpotTrade` is FAIL.
- The complete allowlist for **non-empty permission groups** is exactly **Spot, ContractTrade, Derivatives, Options**. Spot is mandatory; the other three are permitted bundled groups, not requirements to add grants that are absent. A non-empty group outside this set is FAIL.
- Wallet, Exchange, Earn, FiatP2P, FiatBitPay, FiatConvertBroker, BitCard, ByXPost, Affiliate and BlockTrade must be empty or absent of granted authority. The same prohibition covers every other unrelated or newly introduced group.
- Withdrawal, asset/account transfer, convert/exchange, earn and fiat/payment authority are forbidden, regardless of which field reports them.
- Validate the documented response/array shapes and reviewed permission values. Missing required evidence, malformed/ambiguous data or changed permission shapes/values stops activation for owner review. Never silently expand the allowlist or interpret unfamiliar authority as safe.

An earlier PASS is not permanent authority. A different key or changed permissions require a new audit; a new non-empty group is FAIL until separately reviewed, not an automatic extension of this proposal.

## Runtime boundary versus credential capability

The frozen production boundary remains unchanged under Decisions 013, 015 and 017:

- `create_bybit_demo_session(...)` uses `testnet=False`, `demo=True`; the action adapter requires the fixed origin `https://api-demo.bybit.com` and the existing retry/logging safety settings.
- The mutation SDK allowlist is only `place_order` and `cancel_order`.
- Placement sends `category="spot"`, `orderType="Market"` and `isLeverage=0`.
- BUY uses explicit quote authorization and `marketUnit="quoteCoin"`. The runtime supplies the exact reconciled owned base for SELL, which uses `marketUnit="baseCoin"`; it never authorizes the whole wallet.
- Cancellation sends `category="spot"` with the exact order identity. Acknowledgement remains separate from fill/terminal evidence.
- No derivatives/options action path exists through the frozen runtime adapter. No new endpoint, SDK method, strategy behavior or mutation capability is introduced here.

**These code restrictions do not make the API key itself Spot-only.** Broader key grants remain real credential capabilities. A stolen or externally reused Demo key could potentially be used outside Trading Lab against the additional groups; the adapter cannot constrain that use.

The proposed exception is limited to Demo Trading and virtual Demo funds, private secret custody, controlled Stage 12.2 validation and immediate revoke/rotate upon exposure. Real secrets remain outside the repository with 0700 private parent / 0600 secret file; no values or identifiers belong in Git/chat/logs/dashboard/observability. Existing no-tracing, no-environment-dump and no-secret-file-display rules remain unchanged. The permission bundle alone is not evidence of exposure and does not require rotation solely because this documentation is prepared.

## Proposed pre-Gate-G procedure

This is a future permission-audit requirement, not executable code or authorization to make a request now:

1. Obtain separate explicit owner authorization for a bounded read-only permission audit of the exact active Demo key, using the frozen Demo session routing and secret-custody boundary.
2. Query `GET /v5/user/query-api` with that key. Do not persist/display the raw response, SDK details, key/secret, key identifier, user/account UID, note/remark, addresses or expiry data. Extract only the validated permission facts privately; use sanitized failure diagnostics.
3. Verify `uta == 1`, `readOnly == 0`, `SpotTrade` and the complete non-empty-group allowlist above. Explicitly establish that Wallet/transfer/withdraw and all other prohibited authority are absent. Unknown, missing, malformed or non-UTA evidence is FAIL.
4. Record only sanitized PASS/FAIL and non-secret permission-group names; optional `UTA: YES` is acceptable only after the UTA check passes. Never persist/display userID, account UID, key ID, API key or raw response. Never put a key fingerprint or identifier into the audit record to associate it with a key; bind the check to the active explicitly supplied key during the approved procedure. Confirming UTA does not authorize trading.
5. Close the client on success or failure. Place/cancel no order, open no RuntimeStore and perform no runtime/reconciliation/risk/rearm operation as part of a standalone permission audit.

Like the standalone Stage 9 read diagnostic, a separately authorized standalone permission audit runs only while runtime is fully stopped and no other process operates this bot/account runtime. It proves permission/connectivity facts only, not ownership, reconciliation, risk readiness or trading authority. It neither holds nor satisfies the operational runtime account lock. Every operational activation/preflight/restart still requires the canonical RuntimeAccountLock first, then RuntimeStore, exact configuration/risk checks, `prepare_process_restart` when applicable, authenticated runtime resources, reconciliation and the separately authorized `run_observed_hourly_scheduler(...)`.

Re-run the permission gate after API-key rotation, permission changes, replacement runtime-key creation or any observed Bybit permission/API behavior change. An earlier successful audit cannot authorize a different key. This proposal adds no audit CLI, credential loader or automatic re-audit/retry loop.

## Gate G and Live remain separate

A verified UTA RW key, an owner-accepted Demo UTA permission bundle, prior read smoke, Telegram smoke, RuntimeStore readiness, risk activation, reconciliation and a final readiness audit **do not equal trading authorization**. Listing these prerequisites does not claim they have all been executed or passed.

Stage 12.2b still requires a separate explicit owner authorization with exact runtime configuration, exact risk configuration, a bounded run window, permitted mutation scope and stop conditions. Decision 025 itself authorizes no Gate G, Demo mutation or runtime operation, even if later accepted.

**This Demo compatibility exception does not carry into Stage 12.4.** Before Live, independently re-review permissions against then-current Bybit behavior and obtain a new Live-specific contract/approval. Bundled derivative/option authority must not be accepted automatically because it was considered for Demo. Live and Demo credentials remain entirely separate, with no Demo → Live fallback. This proposal grants no Live exception or routing capability.

## Unchanged runtime identity and approved risk profile

The following owner-supplied non-secret profile is recorded for context only; no database/configuration/credential was inspected or changed to verify it here. It creates no defaults or new authorization:

```text
broker_id = bybit-demo
account_binding = demo-main
bot_id = bot1
strategy = ema_trend
EMA = 20 / 50
symbol = BTCUSDT
timeframe = 60
Spot LONG/FLAT MARKET
no borrowing
no leverage
no shorts

risk_capital_quote          = 100 USDT
buy_quote_budget            = 10 USDT
max_entry_notional_quote    = 10 USDT
max_position_notional_quote = 10 USDT
max_daily_loss_fraction     = 0.05
max_drawdown_fraction       = 0.10
max_entries_per_utc_day     = 3
```

RuntimeStore identity, configuration digest, risk epoch, history anchor, database and durable state remain unchanged by Decision 025. Decision 025 does not inspect, modify, rotate or persist any credential value or change the credential-storage contract. No credential file was accessed by this documentation task. No wallet-driven sizing, risk activation/rearm or new trading behavior is introduced.

## Stage state and verification scope

Stage 12.1 and Stage 12.2a remain COMPLETE / FROZEN. Decision 025 is **PROPOSED / OWNER REVIEW PENDING / NOT FROZEN**. Stage 12.2 remains STARTED / INCOMPLETE; Stage 12.2b, 12.2c, 12.2d, 12.3 and 12.4 remain NOT STARTED. Stage 12 remains INCOMPLETE; v1.0.0 remains NOT RELEASED.

Only this new Decision plus PROJECT_STATE.md, README.md and CHANGELOG.md expose the proposal. Existing Decisions 001–024, source, tests, dashboard, scripts, dependencies, schemas, templates, notebooks and data are unchanged. This task performs repository diff/scope/secret checks only; no full-suite rerun. The prior 3,368-test result remains local historical evidence, not a new run or CI claim. No credential file access, broker/Telegram request, order mutation, RuntimeStore operation, runtime/reconciliation/risk/rearm operation occurs in preparing this proposal.
