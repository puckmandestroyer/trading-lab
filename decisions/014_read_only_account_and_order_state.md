# 014 — Read-only Demo account, order, and execution state

- Date: 2026-10-09
- Expanded: 2026-10-10, execution/fill reads required by Decision 013.
- Status: Accepted
- Scope: Stage 9.4, normalized read-only Demo snapshots only.
- Governing contract: [013 — Bybit Demo Exchange Adapter](013_bybit_demo_exchange_adapter.md).

## Boundary and public interface

Broker/demo API → broker-specific adapter → immutable Trading Lab snapshots.

`exchange/account_state.py` contains broker-independent frozen/slotted `CurrencyBalance`, `AccountState`, `OrderState`, and `ExecutionState` dataclasses, the finite `OrderStatus` enum, `BrokerOrderNotFoundError`, and the small structural `ReadOnlyBroker` Protocol. The interface is:

```python
get_account_state() -> AccountState
get_open_orders(symbol: str | None = None) -> tuple[OrderState, ...]
get_order(order_id: str) -> OrderState
get_executions(order_id: str | None = None, symbol: str | None = None) -> tuple[ExecutionState, ...]
```

`BybitDemoReadOnlyAdapter(session, *, account_id=None)` implements these reads. `account_id` is an optional caller-owned diagnostic label, not a fabricated exchange UID. Broker-specific schemas/parsing stay in `exchange/bybit_demo_read_only.py`. No raw payload, SDK session, credential, or broker-specific nested dictionary is returned. Explicit package imports preserve prior wildcard exports.

There is no execution capability: no placement, cancellation, modification, transfers, configuration writes, strategy/execution-engine wiring, state cache, or trading loop. Observing an existing Limit/conditional order does not authorize creating one. Stage 5 remains the frozen EMA regression baseline; timing, next-OPEN backtest fills, accounting, risk, and robustness contracts are unchanged.

## Demo and read safety

Use the existing Stage 9.2 session factory. Construction and every SDK read require `testnet=False`, `demo=True`, endpoint `https://api-demo.bybit.com`, `force_retry=False`, `max_retries=1`, `retry_delay=0`, and `log_requests=False`. The adapter does not create clients, inspect credentials, read environment variables, or make requests on import/construction. Missing/changed routing fails closed.

A closed dispatch allowlist contains only `get_wallet_balance`, `get_open_orders`, `get_order_history`, and `get_executions`; their actual installed pybit 5.17.0 signatures are `(self, **kwargs)` and their implementations use authenticated GET operations. No mutation method is exposed or dispatched. A caller-supplied client is trusted to implement its advertised reads; this Python adapter is a capability boundary for application code, not a sandbox against a malicious SDK/client or deliberate access to private attributes.

## Account quantities and unavailable information

Account-wide `totalAvailableBalance`, `totalWalletBalance`, and `totalEquity` are USD aggregates. `AccountState.currency` is therefore `USD`; never relabel these as USDT cash. Keep separate per-currency wallet balances/equity/locked values in a tuple of `CurrencyBalance`. Account-wide availability is informational margin availability, not permission to spend Spot quote funds.

| AccountState field | Type | Source / meaning |
| --- | --- | --- |
| broker_id | str | Adapter identity `bybit-demo`. |
| account_id | str or None | Optional caller label; no broker UID is invented. |
| currency | str | `USD` for the account-wide aggregates. |
| available_balance | Decimal or None | `totalAvailableBalance`; margin availability, not Spot cash authorization. |
| total_balance | Decimal or None | `totalWalletBalance`. |
| total_equity | Decimal or None | `totalEquity`. |
| balances | tuple[CurrencyBalance, ...] | `coin` rows, preserving their order and currency units. |
| broker_timestamp | aware UTC datetime | Top-level response `time`, integer milliseconds. |
| fetched_at | aware UTC datetime | Local observation time. |

`CurrencyBalance` has `currency: str` from `coin`, `total_balance: Decimal` from `walletBalance`, optional `total_equity: Decimal` from `equity`, optional non-negative `locked_balance: Decimal` from `locked`, and `available_balance: Decimal | None`, which this adapter leaves unavailable. The account type is validated as UNIFIED; it is not another configurable account API.

All monetary values are finite Decimal values parsed directly from broker strings. Reported negative account/coin balances are retained rather than repaired. Missing/malformed required shape or aggregate fields fails; documented blank aggregate values and optional coin equity/locked fields remain `None`. A valid empty coin collection stays empty, with no invented zero holdings.

The wallet response has no authoritative per-coin spendable-cash value for this boundary. Per-coin `available_balance` remains `None`; deprecated `free`/`availableToWithdraw` are ignored. No wallet-minus-locked estimate, price conversion, borrowing, allocation, or balance repair is performed. [Bybit wallet balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance).

## Orders, units, and optional prices

`OrderState` contains the following exact fields. Optional `order_link_id` retains a reported caller identifier; absent/blank values remain `None` and no ID is generated.

| Field | Type | Source / meaning |
| --- | --- | --- |
| broker_id | str | `bybit-demo`. |
| account_id | str or None | Optional caller account label. |
| broker_order_id | str | `orderId`, required. |
| order_link_id | str or None | `orderLinkId`. |
| symbol | str | Uppercase `symbol`. |
| side | BUY or SELL | `side`: Buy/Sell. |
| order_type | MARKET or LIMIT | `orderType`: Market/Limit. |
| status | OrderStatus | Explicit mapping of `orderStatus`. |
| external_status | str | Original `orderStatus`. |
| quantity_unit | BASE or QUOTE | Market `marketUnit`; Limit quantities are BASE. |
| requested_quantity | Decimal | `qty`, positive in quantity_unit. |
| filled_quantity | Decimal | `cumExecQty` for BASE, `cumExecValue` for QUOTE. |
| remaining_quantity | Decimal | Exact same-unit requested minus filled. |
| filled_base_quantity | Decimal | `cumExecQty`, non-negative. |
| filled_quote_amount | Decimal or None | `cumExecValue`, non-negative when available. |
| average_fill_price | Decimal or None | `avgPrice`, positive when available. |
| limit_price | Decimal or None | Positive `price` for Limit; None for Market. |
| stop_price | Decimal or None | Positive `triggerPrice` when available. |
| created_at | aware UTC datetime | `createdTime`. |
| updated_at | aware UTC datetime | `updatedTime`, not before creation. |
| broker_timestamp | aware UTC datetime | Top-level `time`. |
| fetched_at | aware UTC datetime | Local observation time. |

For Market orders, require explicit `marketUnit`; `baseCoin` means BASE, `quoteCoin` means QUOTE. The accepted Spot path excludes leveraged orders and quote-unit Market SELLs. Observed Limit orders use BASE quantities. Normalize side to BUY/SELL and type to MARKET/LIMIT; unsupported values fail explicitly.

`qty` is requested authorization in that unit. BASE uses `cumExecQty` as filled quantity; QUOTE uses `cumExecValue`, never subtracting base quantity from a quote budget. Preserve both execution dimensions without deriving quantities from price. Missing quote execution value cannot become a successful quote-unit snapshot.

Remaining quantity is exact same-unit `requested - filled`, without caller Decimal-context rounding. It denotes unfilled authorization, including a terminal order's unused quote budget or cancelled remainder; **it does not imply a live executable remainder**. Status determines activity. Reject negative/non-finite amounts, zero requested quantity, overfills, contradictory execution dimensions, and inconsistent known statuses. A FILLED BASE order must be fully filled; a FILLED QUOTE order may leave unused budget. Broker-reported prices are authoritative; missing/blank/zero optional prices become `None`, without deriving or inventing a fill price. An observed Limit order requires its positive limit price.

All timestamps become timezone-aware UTC datetimes by exact integer-millisecond conversion. Reject invalid/out-of-range timestamps and updates preceding creation. Server observation time and local fetched_at remain distinct. [Bybit realtime orders](https://bybit-exchange.github.io/docs/v5/order/open-order).

Repeated identical broker responses produce identical financial/status fields. Local `fetched_at` changes with observation time; tests fix that clock when comparing complete snapshots. Each call returns independent objects without a cache.

## Execution/fill observations

`ExecutionState` represents exactly one exchange-reported Spot Trade execution. Multiple fills for one order remain separate records in the returned broker sequence; they are not aggregated into an average price or inferred from an order status. This model adds no order execution capability.

| Field | Type | Source / meaning |
| --- | --- | --- |
| broker_id | str | `bybit-demo`. |
| account_id | str or None | Optional caller account label. |
| broker_execution_id | str | Required `execId`. |
| broker_order_id | str | Required `orderId`. |
| order_link_id | str or None | Optional `orderLinkId`. |
| symbol | str | Required uppercase `symbol`. |
| side | BUY or SELL | `side`: Buy/Sell. |
| executed_quantity | Decimal | Positive `execQty`, in base currency. |
| execution_price | Decimal | Positive `execPrice`, quote currency per base unit. |
| execution_fee | Decimal | Required finite signed `execFee`; zero charges and negative rebates are preserved. |
| fee_currency | str or None | Reported uppercase `feeCurrency`; missing/blank remains unavailable. |
| executed_at | aware UTC datetime | Required integer-millisecond `execTime`. |
| broker_timestamp | aware UTC datetime | Top-level response `time`. |
| fetched_at | aware UTC datetime | Local observation time. |

Require `execType="Trade"`; non-trade/unknown execution types fail explicitly instead of becoming fills. Reject margin execution flags when reported. Missing required fields, invalid IDs/side/currency/timestamps, non-finite amounts, and non-positive execution quantity/price fail. Unknown extra fields are ignored. No arithmetic, fee conversion, currency inference from side/symbol, or modeled fee/slippage is applied. A fee with unavailable currency remains informational and cannot safely be combined with another currency. Historical Stage 5–8 next-OPEN fills and research costs remain separate. [Bybit trade history](https://bybit-exchange.github.io/docs/v5/order/execution).

## Finite statuses

| External Bybit status | Internal status |
| --- | --- |
| New | OPEN |
| Untriggered, Triggered | NEW (pending/transient activation) |
| PartiallyFilled | PARTIALLY_FILLED |
| Filled | FILLED |
| Cancelled, PartiallyFilledCanceled, Deactivated | CANCELLED |
| Rejected | REJECTED |
| Any other non-empty status | UNKNOWN |

The internal enum also reserves EXPIRED for brokers that explicitly support it. Unsupported Bybit values, including new future statuses, never silently become a known valid state. Always preserve `external_status`. Missing/invalid status raises a parsing error. Unknown records returned by an open-only query remain UNKNOWN rather than being silently filtered or declared active. [Bybit status definitions](https://bybit-exchange.github.io/docs/v5/enum#orderstatus).

## Complete reads and failures

Wallet reads use `get_wallet_balance(accountType="UNIFIED")`. Open orders use Spot `openOnly=0`, `limit=50`, optional validated uppercase symbol, and response cursors. Consume all pages before returning a tuple. Duplicate IDs, repeated/malformed cursors, an empty page with another cursor, unexpected closed records, or exceeding 100 pages fail rather than returning a truncated collection. This is bounded pagination, not a runtime loop or exchange-transactional snapshot.

An exact order lookup queries realtime by Spot orderId, then history by the same ID **only after a valid empty realtime result**. Matching identity is mandatory; multiple records fail. No retries after network/API/parsing failures. History retention and latency are exchange limitations; a result absent from both inspected windows raises `BrokerOrderNotFoundError`, never a fabricated rejection/fill/cancellation or proof that placement failed. [Bybit order history](https://bybit-exchange.github.io/docs/v5/order/order-list).

Execution reads use `get_executions(category="spot", execType="Trade", limit=100)` with optional validated orderId/symbol and response cursors. Each supplied filter is checked against every returned record, even though Bybit prioritizes orderId over symbol. Consume all pages before returning; reject duplicate execution IDs, malformed/repeated cursors, empty continuing pages, late failures, or more than 100 pages. No truncated tuple or partial state is returned. Without time bounds, the endpoint uses its default seven-day query window; an empty tuple means no fills were observed in that window, not that an order never filled. There is no automatic reconciliation, polling, backtest/portfolio write, or inference from order state.

| Public operation | pybit methods | Maximum logical calls |
| --- | --- | ---: |
| get_account_state() | get_wallet_balance(accountType="UNIFIED") | 1 |
| get_open_orders(symbol=None) | get_open_orders(category="spot", openOnly=0, limit=50, optional symbol/cursor) | 100, one per page; fail if more remain. |
| get_order(order_id) | get_open_orders(category="spot", orderId=...); optional get_order_history with the same category/ID | 2; history only after valid empty realtime. |
| get_executions(order_id=None, symbol=None) | get_executions(category="spot", execType="Trade", limit=100, optional orderId/symbol/cursor) | 100, one per page; fail if more remain. |

Invalid arguments or unsafe Demo settings fail before a request. Each SDK call retains Stage 9.2's one-attempt configuration; no extra retries or sessions are introduced.

`BybitDemoReadError` reports safe operation/retCode or transport exception type. `BybitDemoStateParseError` reports schema/field context. Never include raw response/SDK/client repr, authentication data, or SDK exception text/chains in normal diagnostics. No existing snapshot or local trading state is mutated on failure, including late-page failure. Previous snapshots remain independent and immutable; no partial snapshot is returned.

## Verification and later work

Offline fixtures cover account/order/fill normalization, zero/multiple coin balances, empty/multiple orders and fills, partial/final/cancelled/rejected/unknown states, optional prices/identifiers/fee currencies, reported fees/rebates, units, exact decimals, UTC timestamps, pagination, history fallback, malformed/API/network failures, input preservation, repeated reads, Demo routing, import safety, and absence of mutation paths. Guarded SDK tests verify only GET read paths; AST/behavior checks constrain dispatch to the read allowlist. No account, real credentials, broker connection, or exchange API call is required.

No dependency change. Order lifecycle actions, reconciliation, price-aware spendability/preflight, and live request smoke remain separate later work. Stage 9.4 is ready for owner review/freeze; Stage 9 remains INCOMPLETE. Stage 9.5 requires explicit approval; Stage 10 runtime is not started.
