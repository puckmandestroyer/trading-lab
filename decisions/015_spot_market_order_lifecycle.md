# 015 — Demo Spot Market order lifecycle actions

- Date: 2026-10-10
- Status: Accepted
- Scope: Stage 9.5, explicitly called Demo Spot Market placement and exact-ID cancellation only.
- Reviewed baseline: `816f5391bc1b57b84524cc784df93068e731cae0` — `Add read-only Bybit demo account and order state adapter`.
- Governing decisions: [013](013_bybit_demo_exchange_adapter.md) and [014](014_read_only_account_and_order_state.md), unchanged. Historical Decisions 010–012 and Stage 5 frozen EMA results/tolerances/next-OPEN timing remain unchanged.

## Boundary and public API

Caller-authorized request → existing Stage 9.3 metadata/normalization → Stage 9.5 action → immutable acknowledgement → separate, explicitly called Stage 9.4 state/fill reads.

`exchange/order_actions.py` defines broker-independent frozen/slotted `SpotMarketOrderRequest`, `SpotMarketOrderAcknowledgement`, and `OrderCancellationAcknowledgement`. `exchange/bybit_demo_orders.py` contains the broker-specific action adapter and four small errors. These eight names are available by explicit package import; existing wildcard exports are unchanged.

```python
BybitDemoOrderAdapter(session)
place_market_order(request: SpotMarketOrderRequest) -> SpotMarketOrderAcknowledgement
cancel_order(symbol: str, order_id: str) -> OrderCancellationAcknowledgement
```

The caller supplies an existing Stage 9.2 session. No environment read, client construction, request, global cache, or credentials exist in the new models/action boundary on import or construction. The public methods accept no arbitrary broker kwargs or environment/order-type switches.

## Authorization and exact amounts

| Request field | Contract enforced at placement |
| --- | --- |
| symbol | Non-empty uppercase string without surrounding whitespace; fresh metadata must match. |
| side | Exactly BUY or SELL. |
| authorized_amount | Positive finite exact Decimal, integer or decimal string, following Stage 9.3 validation; bool, float and unsupported types fail. |
| amount_unit | QUOTE for BUY, BASE for SELL; no implicit conversion. |
| order_link_id | Optional caller-provided identifier, validated below. |

The dataclass stores caller authorization; adapter validation runs before mutation. It has no signal, desired position, wallet balance, allocation fraction, credentials, client or payload. Stage 9.5 never derives an amount from wallet/risk/portfolio state. SELL requires caller authorization of available base assets; the adapter does not independently inspect holdings or authorize shorting/borrowing.

Each placement explicitly fetches fresh rules through `fetch_bybit_spot_instrument_rules(session, symbol)` once, then delegates to `normalize_spot_market_buy_quote_amount` or `normalize_spot_market_sell_base_quantity`. No rule, precision, min/max or rounding implementation is copied. Decimal round-down cannot increase exposure. BUY quote minimum and SELL base maximum retain Stage 9.3's same-unit limits; price-dependent checks remain exchange-authoritative. Below-minimum/above-maximum requests fail without clipping, splitting or wallet resizing.

## SDK requests and Demo guard

The installed pinned **pybit 5.17.0** implements both SDK methods as `(self, **kwargs)`, using authenticated POST: `/v5/order/create` and `/v5/order/cancel`. Source and HTTP behavior were inspected and tested offline.

```python
# BUY: qty is normalized quote authorization, not base quantity.
session.place_order(
    category="spot", symbol=symbol, side="Buy", orderType="Market",
    qty=normalized_amount, marketUnit="quoteCoin", isLeverage=0,
    # orderLinkId=caller_link only when provided
)

# SELL: qty is normalized authorized base quantity.
session.place_order(
    category="spot", symbol=symbol, side="Sell", orderType="Market",
    qty=normalized_amount, marketUnit="baseCoin", isLeverage=0,
    # orderLinkId=caller_link only when provided
)

session.cancel_order(category="spot", symbol=symbol, orderId=order_id)
```

Amounts are canonical plain decimal strings. No price, trigger, TP/SL, margin, derivative, leverage, Limit, batch or extra request options can be supplied through the public adapter. The fixed `isLeverage=0` disables Spot margin/borrowing. [Bybit placement parameters](https://bybit-exchange.github.io/docs/v5/order/create-order).

Construction, preflight, and immediately before every mutation require `testnet is False`, `demo is True`, endpoint `https://api-demo.bybit.com`, `force_retry is False`, integer `max_retries == 1` (bool rejected), `retry_delay == 0`, and `log_requests is False`. A change during metadata fetch is caught before submission. No live/Testnet fallback or session configuration mutation occurs. The sole mutation dispatch allowlist is **place_order / cancel_order**. The supplied SDK is trusted to implement its advertised methods; deliberate private access or a malicious replacement SDK is not sandboxed by this Python boundary.

## Caller orderLinkId

Optional placement IDs contain 1–36 ASCII letters, digits, dashes or underscores, matching the documented format/maximum. Forward unchanged; never generate, replace or remember an ID. Caller owns uniqueness and later Stage 10 owns idempotency/lifecycle policy. A provided ID requires an identical acknowledgement echo. If no ID was provided, absent/null/blank echo remains None; an unexpected non-empty echo fails. No automatic ID lookup, replacement or resend is implemented. [Bybit orderLinkId rules](https://bybit-exchange.github.io/docs/v5/order/create-order).

## Acceptance receipts are not execution evidence

Require a Mapping, exact integer `retCode == 0`, result Mapping, non-empty broker `orderId`, valid optional reported link and top-level integer-millisecond time. Optional category/symbol echoes must match when present. Parsing preserves the response. Timestamps become aware UTC; local fetched time is separate.

| Placement acknowledgement fields | Cancellation acknowledgement fields |
| --- | --- |
| broker_id, broker_order_id, order_link_id | broker_id, broker_order_id, order_link_id |
| symbol, side, order_type (MARKET) | symbol |
| submitted_amount (Decimal), amount_unit (QUOTE/BASE) | — |
| broker_timestamp, fetched_at | broker_timestamp, fetched_at |

**Placement acknowledgement means request acceptance, not a fill. Cancellation acknowledgement means cancellation request acceptance, not terminal CANCELLED state.** Neither receipt contains status, filled quantity, execution price, fee or PnL. No historical fill, modeled slippage, portfolio mutation or wallet deduction is synthesized. Extra fill-like response fields do not become receipt fields.

Cancellation accepts only explicit `symbol` plus exact broker `order_id`; no orderLinkId-only, symbol-only, bulk or automatic cancellation. The acknowledgement ID must equal the requested ID. It may retain a reported link as diagnostics, without sending one. Bybit decides whether an order is still cancellable; a Market order can already be filled or fill concurrently. No pre/post state query or terminal-state assumption occurs. [Bybit cancellation semantics](https://bybit-exchange.github.io/docs/v5/order/cancel-order).

Only later explicit `BybitDemoReadOnlyAdapter.get_order(receipt.broker_order_id)` / `get_executions(...)` observations establish state/fills. Prior snapshots remain immutable; unknown statuses and unobserved-order uncertainty retain Decision 014 semantics. The existing read adapter remains strictly read-only and unchanged.

## Failures and no automatic resend

| Error | Meaning |
| --- | --- |
| BybitDemoConfigurationError | Unsafe session, blocked before mutation. |
| ValueError / TypeError / Stage 9.3 constraint error | Invalid caller request/amount, blocked before mutation. |
| BybitDemoActionError | Safe metadata-preflight failure; placement was not attempted. |
| BybitDemoOrderRejectedError | Confirmed nonzero broker code, retained as safe operation/ret_code. The current request was rejected; this proves nothing about an earlier request with the same caller ID. |
| BybitDemoActionParseError | Untrustworthy or mismatched acknowledgement; acceptance remains unknown. |
| BybitDemoAmbiguousActionError | Transport/SDK failure; the request may have reached Bybit. |

Pinned pybit raises `InvalidRequestError` for returned broker codes; only a nonzero exact integer status_code becomes confirmed rejection. Generic exceptions, `FailedRequestError`, timeout/reset, and malformed SDK codes remain ambiguous. SDK retry-code exhaustion loses trustworthy rejection evidence, so it is conservatively ambiguous. No raw SDK message/request/headers, raw payload, client repr, credential or exception chain is exposed in adapter diagnostics.

One placement call follows one metadata read; cancellation makes one call. There are no adapter retries, follow-up reads, retry loops, sleep, alternate IDs or automatic replacement. Pinned SDK one-attempt settings are enforced and actual send counts are tested, including its retryable-code branch. Unknown/malformed responses must not trigger a resend. Caller reconciliation and any future retry policy remain Stage 10 work; an unobserved order is not proof of rejection.

## Verification and deferred work

All 76 new tests are offline, using synthetic fixtures and network guards. They cover exact BUY/SELL/cancel params, Stage 9.3 reuse, fresh rules, units/authorization/constraints, caller IDs, immutable receipts, UTC/schema/identity validation, API/SDK/ambiguous failures, actual SDK single sends, unchanged Stage 9.4 reads, absence of automatic state mutation, and the two-method capability guard. Existing tests/tolerances are preserved; no new dependency or broker connection is needed.

Stage 9.1–9.5 are COMPLETE; Stage 9 remains INCOMPLETE. Stage 9.6 — Adapter Integration + Offline Regression + Optional Manual Demo Smoke is next and NOT STARTED. No smoke was run. Stage 10 is NOT STARTED. No strategy/engine/risk wiring, automated sizing, runtime/reconciliation loop, scheduler, portfolio write, amend/replace, transfer/configuration mutation or real-money route is introduced. Historical Stages 5–8 and Demo Stages 9.2–9.4 remain frozen.
