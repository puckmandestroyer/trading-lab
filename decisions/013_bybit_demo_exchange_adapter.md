# 013 — Bybit Demo Exchange Adapter Contract

- Date: 2026-10-09
- Status: Accepted
- Scope: Stage 9.1 documentation/architecture only. No production API, authenticated session, network request, order, dependency, environment change, or new test is implemented.
- Completed baseline: `83e6df19377339ccb3c937f18e1067704e357035` — `Complete Stage 8 strategy robustness`.
- Related decisions: [010 — Generic strategy / backtest contract](010_generic_strategy_backtest_contract.md), [011 — Risk and position sizing](011_risk_and_position_sizing.md), and [012 — Strategy Robustness Contract](012_strategy_robustness.md), which remain authoritative and unchanged.

## Context and goal

Stages 6, 7, and 8 are COMPLETE. The project has generic historical backtesting, independent fixed capital allocation, reusable accounting/analytics, and robustness research. None of these proves readiness for real-money trading or implements an authenticated exchange adapter.

Stage 9 introduces an isolated Bybit Demo exchange boundary. Freeze environment safety, explicit order units, exchange normalization, response/error semantics, and the roadmap before authenticated code exists. Later implementation belongs under `src/trading_lab/exchange/` in separate focused modules, with small inspectable structures rather than a domain framework. Exact public APIs and files are reviewed in their implementation milestones.

## Responsibilities and strategy / risk / adapter boundary

The future flow is Market Data → Strategy → Signal / desired position → Risk Manager → Execution / Runtime → Exchange Adapter → Bybit Demo.

| Layer | Responsibility |
| --- | --- |
| Strategy | WHEN / desired LONG or FLAT position, under Decision 010. |
| Risk | HOW MUCH portfolio capital may be allocated, under Decision 011. |
| Execution / runtime | Turn authorized intent and account state into an explicit order request; orchestrate its lifecycle in Stage 10. |
| Exchange adapter | HOW to express that request to Bybit, communicate with the exchange, normalize metadata/responses, enforce exchange-specific formatting/constraints, and expose state primitives. |

The adapter receives explicit caller intent; it never infers a signal from market data and needs no strategy import. BUY means enter/increase spot asset exposure; SELL means reduce/close that exposure. These exchange directions do not change the existing canonical strategy signal schema or permit pyramiding in the historical engine.

The adapter does not decide whether to buy/sell, `position_fraction`, capital allocation, EMA parameters, stop-loss/take-profit policy, leverage, portfolio policy, backtest accounting, or strategy optimization. Exposing wallet balances does not authorize spending them. Stage 10 combines risk policy, current account state, and exchange constraints; the adapter cannot choose to use all wallet funds, borrow, add leverage, or resize for strategy reasons.

## Initial environment: Demo vs Testnet vs real trading

Stage 9 targets **Bybit Demo Trading only**, with a Demo Unified Trading Account (UTA). The intended official `pybit.unified_trading.HTTP` session uses **`testnet=False`, `demo=True`**, corresponding to authenticated REST **`https://api-demo.bybit.com`**. The connector's environment routing supports this distinction. [Official pybit HTTP manager](https://github.com/bybit-exchange/pybit/blob/master/pybit/_http_manager.py).

Credentials must be generated from the user's production/mainnet website account **after switching into Demo Trading mode**. Demo is an independent account with its own credentials/user ID. Production website login is the key-creation context, not authorization to use live trading keys. Testnet keys and ordinary real-trading production keys are not Demo keys. [Bybit Demo Trading Service](https://bybit-exchange.github.io/docs/v5/demo).

Bybit Testnet, real-money production trading, and the combination `testnet=True` / `demo=True` are excluded from the accepted path. Configuration must **fail closed**: missing, invalid, or ambiguous Demo configuration raises an error rather than falling back to authenticated `testnet=False`, `demo=False`. No initial `real_trading=True`, `mainnet=True`, or `production_mode=True` switch is permitted.

## Initial Spot scope and transport

- Product: `category="spot"`, LONG / FLAT only, with margin and borrowing disabled and no leverage. Order requests must not enable borrowing (`isLeverage=0`).
- Canonical integration/smoke symbol: `BTCUSDT`. The adapter may receive another valid Spot symbol supported by instrument metadata; reusable code must not hardwire BTC rules.
- Initial trading order type: MARKET only. No Limit, PostOnly, TP/SL, conditional, stop, trailing-stop, OCO, or batch orders.
- Transport: Bybit V5 REST through official `pybit.unified_trading.HTTP` only. No public/private WebSocket streams, subscriptions, reconnect manager, or WebSocket orders.

Linear/inverse contracts, options, spot margin, short selling, derivatives, borrowing, leverage, and hedge mode are excluded. Stage 10 initially uses REST polling; Stage 9 does not choose polling cadence or create a bot loop.

## Market BUY unit

For Spot market BUY, explicitly set `marketUnit="quoteCoin"`. The caller provides an authorized quote-currency amount, represented by Bybit's string `qty`; for BTCUSDT the unit is USDT. Do not rely on the exchange's implicit default or substitute an adapter-selected base quantity. The request amount cannot exceed the caller's authorization.

## Market SELL unit

For Spot market SELL, explicitly set `marketUnit="baseCoin"`. The caller provides the base-asset quantity available/authorized to sell; for BTCUSDT the unit is BTC. Never convert this into an arbitrary quote target or sell more than explicitly requested. These unit choices use the documented Spot market-order boundary. [Bybit Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order).

## Instrument metadata / decimal normalization

Bybit instrument metadata is authoritative. Stage 9.3 must fetch/parse the relevant Spot symbol's `baseCoin`, `quoteCoin`, `status`, `lotSizeFilter`, and `priceFilter`, including applicable minimum amount/quantity semantics, maximum market quantity, base/quote precision, and tick size where needed. Validate tradability and required rule fields; missing or malformed rules cannot become unconstrained orders.

Do not hard-code today's BTCUSDT minimums or precision. Interpret current applicable Spot fields and their units, rather than assuming derivative rules or deprecated fields govern Spot. BUY quote amounts and SELL base quantities must be checked in the correct dimensions; exact parsing and constraint checks belong to Stage 9.3. [Bybit Get Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument).

Use `Decimal` or equivalently exact decimal-safe handling at the normalization boundary. Emit canonical plain decimal strings for exchange numeric request fields; scientific notation requires explicit exchange acceptance and tests. `round(float_value, N)` is not an authoritative sizing rule. Invalid/non-finite/non-positive request amounts must fail clearly, without uncontrolled float coercion or repair.

## Rounding, minimums, and maximums

Precision/increment normalization may only round **DOWN toward zero** to an applicable valid step. It may reduce an amount to satisfy exchange precision, never increase the authorized quantity/budget or change allocation policy.

If the normalized amount is below an applicable minimum quantity, amount, or notional, raise a clear adapter-domain constraint error. Never round up or increase exposure merely to meet a minimum. Reject a request above an applicable market maximum; do not silently clip it or split a logical order into multiple orders. Automatic order splitting is outside Stage 9.

## Credentials / secret safety

Credentials come from runtime environment/configuration. Stage 9.2 will review clear Bybit-demo-specific variable names, replacing indefinite reliance on ambiguous generic names; this decision does not freeze exact names or change `.env.example`.

Never hard-code credentials in source, tests, or notebooks; commit credentials or `.env`; print keys/secrets in logs; or include authentication material in errors or object `repr`. Safe diagnostics may contain category, symbol, side, order type, normalized quantity, `orderLinkId`, `orderId`, and `retCode`. Exclude credential headers, signatures, tokens, and raw environment dumps. Raw SDK exceptions/responses must not be blindly logged or exposed if they contain authentication material; safe error context/redaction belongs to the adapter boundary.

## Dependency and centralized session construction

Stage 9.2 will add and verify official `pybit`, including compatibility with the existing Python environment. Stage 9.1 installs nothing and changes no requirements, lock files, or virtual environment.

A focused central session/client factory owns Demo configuration, `testnet=False`, `demo=True`, credentials, and safe construction. Order, wallet, instrument, and runtime code must not independently construct authenticated sessions. Demo identity must be established before requests; SDK defaults or configurable endpoint overrides cannot bypass the fail-closed contract.

No session is created at module import. Importing `trading_lab.exchange` or later Stage 9 modules must never authenticate, access the network, query instruments/wallet, or place orders. Network activity requires explicit method calls. Offline configuration/session-construction tests do not require an authenticated network request.

## Response normalization

Normalize instrument rules, runtime-relevant wallet balances, order acknowledgements, order state, and execution/fill records into small explicit project-owned structures. Later runtime code should not repeatedly unpack arbitrary pybit nesting. Do not build a large framework; exact fields/APIs are reviewed when implemented. Retain raw responses only for safe, explicitly justified debugging.

HTTP transport success alone is insufficient. Require accepted exchange success semantics (`retCode == 0`) and validate the expected result shape and matching symbol/category wherever the response provides them. Missing, unexpected, or malformed data raises an error rather than becoming empty success. A valid documented empty collection may represent no records; malformed or unavailable state must not be treated as that collection.

## Error behavior

Use a small exchange-specific boundary for configuration/authentication failures, transport/API failures, malformed responses, instrument constraint violations, and order-state mismatches. Do not design an enormous exception hierarchy, swallow SDK/API errors, invent successful results, or expose secrets. Ambiguous placement must remain distinguishable from a confirmed rejection.

## Order acknowledgement vs fills

A successful place-order acknowledgement means acceptance, **not proof of a full market fill**. Keep accepted request, eventual order state, and actual executions/fills distinct. Read-side primitives must make status and execution records available to Stage 10. Placement response alone is never realized execution PnL. Cancellation acknowledgement likewise requires subsequent state confirmation before claiming cancellation completed. [Bybit Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order).

Demo orders use exchange-simulated order/execution data. The historical signal N → next candle OPEN rule remains a BACKTEST model under Decision 010. Never fabricate Demo fills from next OPEN, research fees, or modeled slippage. Stage 8's `fee_rate=0.001` / `slippage_rate=0.0005` remain historical research assumptions, not current Demo fees; do not alter Demo market orders using research slippage. Actual fills, execution fees/currencies, and relevant account data are exchange-side evidence. Existing accounting/research APIs remain unchanged.

## Client order IDs / idempotency / no blind retries

Support an optional caller-provided unique `orderLinkId`, validating and forwarding it without silent replacement. Stage 10 owns generation, deterministic ID lifecycle, and runtime idempotency policy; the adapter does not invent that policy.

If placement times out, the connection resets, or the response is unknown, the first request may already have reached Bybit. **Do not blindly resend**, including by generating a fresh ID. Surface the ambiguous outcome; use order-state lookup by known `orderId` or `orderLinkId` before runtime decides whether another placement is safe. A temporarily missing record is not proof that placement failed; preserve uncertainty until reconciliation resolves it. [Bybit Get Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order).

This rule also applies to SDK/internal retries: later session/order implementation must review and test their behavior, not assume that disabling an adapter retry loop is sufficient. Read-only retries may be implemented later with an explicit safe policy. Placement retries require reviewed idempotency/reconciliation rules.

## Read-side capabilities and reconciliation primitives

Implement/test read-side capabilities before placement: instrument information, required wallet/account balances, open/realtime order lookup, and order history/execution reads where directly needed. Do not implement every account endpoint. Normalize enough state for Stage 10 to reconcile open/completed orders, fills, and wallet/base-asset balances. [Bybit Get Order History](https://bybit-exchange.github.io/docs/v5/order/order-list), [Bybit Get Trade History](https://bybit-exchange.github.io/docs/v5/order/execution).

Stage 9 provides explicit query primitives; continuous reconciliation belongs to Stage 10. No `while True` loop, scheduler, candle/signal polling cadence, runtime state machine, automatic EMA-triggered order, or continuous orchestration is added in Stage 9.

## Order-side capabilities

Later Stage 9 supports only explicit Spot market BUY, Spot market SELL, acknowledgement normalization, status lookup, and cancellation of an active order when applicable. Market orders may complete before cancellation is possible; acceptance and cancellation must not fabricate terminal state or fills. No derivatives, conditional strategy orders, leverage, bulk trading, or automatic signal execution.

## Offline testing policy

Implementation tests are offline by default: mock/fake pybit clients and synthetic instrument, wallet, order, and execution responses. The full suite must require no internet, Bybit account, credentials, Demo funds, or live/Demo order placement. Later tests must cover units/precision/constraints, malformed/error responses, secret safety, Demo fail-closed configuration, acknowledgement/state separation, and ambiguous-placement behavior.

Stage 9.1 adds zero tests. Its documentation gate runs the unchanged full suite once: **982 tests, zero failures, errors, or skips**, plus `git diff --check`. Source, tests, dependencies, environment, notebooks, data/results, and Decisions 001–012 must remain unchanged.

## Optional manual Demo smoke policy

Stage 9.6 may define an explicitly opt-in manual Demo-only smoke workflow with explicit credentials and environment safeguards. It never runs on import, in unit tests, or automatically during the full suite. Read-only connectivity precedes any separately authorized optional order smoke; testing connectivity must never silently place an order. Exact design is deferred to Stage 9.6, with no smoke execution in Stage 9.1.

## Existing public historical market-data separation

`src/trading_lab/exchange/bybit_market_data.py` remains the unchanged Stage 1 public Bybit V5 Kline HTTP helper: no credentials, authenticated trading, or order management. Historical collection stays independent; authenticated Demo functionality uses separate focused modules later. Runtime market reads may eventually use pybit if needed, without rewriting the historical downloader merely for consistency.

## Accepted Stage 9 roadmap

| Milestone | Direction | Status after Stage 9.1 |
| --- | --- | --- |
| 9.1 — Demo Exchange Adapter Contract | Decision 013 and project documentation. | COMPLETE; Accepted, architecture only. |
| 9.2 — Pybit Dependency + Secure Demo Configuration / Session | Verify/add pybit; review Demo-specific env names and safe `.env.example`; central Demo-only session construction and offline tests. No authenticated request required to prove construction. | Awaiting explicit owner approval; NOT STARTED. |
| 9.3 — Instrument Metadata + Order Normalization | Fetch/parse Spot rules; exact decimal amounts, round down, enforce applicable minimums/maximums without increased exposure. | Planned; NOT STARTED. |
| 9.4 — Read-Only Demo Account / Order State Adapter | Only needed wallet, realtime/order status/history, and execution/fill queries; no placement. | Planned; NOT STARTED. |
| 9.5 — Spot Market Order Lifecycle Adapter | Explicit BUY/SELL, acknowledgements, status, cancellation where applicable; no bot loop. | Planned; NOT STARTED. |
| 9.6 — Adapter Integration + Offline Regression + Optional Manual Demo Smoke | Mocked integration/error/environment/formatting regression; explicit optional manual Demo workflow. | Planned; NOT STARTED. |
| 9.7 — Final Stage 9 Audit + Docs | Contract/regression/scope/secret/Demo safety audit; confirm no runtime loop, close Stage 9, declare Stage 10 next. No new functionality. | Planned; NOT STARTED. |

Only 9.1 is complete now. Stage 9 overall has STARTED and remains INCOMPLETE. Stage 9.2 requires explicit owner approval. Stage 10 — Demo Trading Runtime is future work, initially using REST polling; it is not started or implemented here.

## Out of scope

Stage 9 excludes WebSockets, continuous bot/reconciliation loops, cron/schedulers, PostgreSQL, Redis/message queues, dashboards/FastAPI, Docker/VPS deployment, multiple bot instances, multi-asset portfolio allocation, ML, strategy optimization, limit-order strategy logic, stop-loss/take-profit engines, derivatives, leverage, shorts, and real-money mode.

Stage 9.1 changes only this decision, `PROJECT_STATE.md`, `README.md`, and `CHANGELOG.md`. It does not install pybit, modify credentials/configuration/dependencies, create sessions, call exchange APIs, place orders, add tests, or start 9.2.

## Consequences / trade-offs

Explicit Demo identity, request units, caller authorization, metadata constraints, decimal handling, and small normalized responses make the boundary inspectable and testable offline. Strict rejection may leave an authorized intent unsubmitted when exchange minimums/maximums prevent it; the adapter cannot solve that by increasing risk or splitting orders.

Market-only REST is sufficient for the first Demo runtime but does not guarantee complete or immediate fills. Acknowledgements need later state/execution reads; uncertain placement needs reconciliation instead of blind retries. Polling/orchestration remains Stage 10 work. This contract preserves historical research and layer ownership; Demo integration and its eventual smoke results do not establish profitability or real-money readiness.

Official environment/order/metadata references above were checked on 2026-10-09. Implementation milestones must recheck applicable SDK/API semantics without silently expanding this accepted scope.
