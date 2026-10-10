"""Demo-only Spot account/order/fill reads; no credentials, clients, or actions."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, InvalidOperation, MAX_EMAX, MIN_EMIN, localcontext

from .account_state import (
    AccountState, BrokerOrderNotFoundError, CurrencyBalance, ExecutionState,
    OrderState, OrderStatus,
)


class BybitDemoReadError(RuntimeError):
    """A Demo read failed, with safe operation/code context and no raw SDK error."""


class BybitDemoStateParseError(BybitDemoReadError):
    """A response cannot become a complete, trustworthy normalized snapshot."""


_READ_METHODS = frozenset({"get_wallet_balance", "get_open_orders", "get_order_history", "get_executions"})
_STATUS_MAP = {
    "New": OrderStatus.OPEN,
    "Untriggered": OrderStatus.NEW,
    "Triggered": OrderStatus.NEW,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Filled": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELLED,
    "PartiallyFilledCanceled": OrderStatus.CANCELLED,
    "Deactivated": OrderStatus.CANCELLED,
    "Rejected": OrderStatus.REJECTED,
}


def _text(value, name: str, *, uppercase: bool = False) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or (uppercase and value != value.upper())
    ):
        raise BybitDemoStateParseError(f"Invalid {name}: expected a non-empty string without surrounding whitespace.")
    return value


def _optional_text(value, name: str, *, uppercase: bool = False) -> str | None:
    if value is None or (isinstance(value, str) and value == ""):
        return None
    return _text(value, name, uppercase=uppercase)


def _number(value, name: str, *, optional: bool = False, nonnegative: bool = False) -> Decimal | None:
    if optional and (value is None or (isinstance(value, str) and value == "")):
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise BybitDemoStateParseError(f"Invalid {name}: expected a decimal string.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise BybitDemoStateParseError(f"Invalid {name}: malformed decimal.") from None
    if not number.is_finite() or (nonnegative and number < 0):
        raise BybitDemoStateParseError(f"Invalid {name}: non-finite or negative amount.")
    return number


def _price(value, name: str) -> Decimal | None:
    price = _number(value, name, optional=True, nonnegative=True)
    return None if price == 0 else price


def _timestamp(value, name: str) -> datetime:
    if type(value) is int:
        milliseconds = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            milliseconds = int(value)
        except ValueError:
            raise BybitDemoStateParseError(f"Invalid {name}: timestamp out of range.") from None
    else:
        raise BybitDemoStateParseError(f"Invalid {name}: expected integer milliseconds.")
    if milliseconds < 0:
        raise BybitDemoStateParseError(f"Invalid {name}: negative timestamp.")
    try:
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)
    except OverflowError:
        raise BybitDemoStateParseError(f"Invalid {name}: timestamp out of range.") from None


def _exact_difference(left: Decimal, right: Decimal) -> Decimal:
    # Enough aligned digits prevent the caller's Decimal context rounding a balance.
    a, b = left.as_tuple(), right.as_tuple()
    exponent = min(a.exponent, b.exponent)
    precision = max(len(a.digits) + a.exponent - exponent, len(b.digits) + b.exponent - exponent) + 1
    with localcontext(Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN)):
        return left - right


def _result(response, operation: str, *, orders: bool = False):
    if not isinstance(response, Mapping):
        raise BybitDemoStateParseError(f"{operation}: response must be a Mapping.")
    code = response.get("retCode")
    if type(code) is not int:
        raise BybitDemoStateParseError(f"{operation}: missing or invalid retCode.")
    if code != 0:
        raise BybitDemoReadError(f"{operation}: broker rejected read (retCode={code}).")
    result = response.get("result")
    if not isinstance(result, Mapping) or not isinstance(result.get("list"), list):
        raise BybitDemoStateParseError(f"{operation}: result/list has invalid shape.")
    if orders and result.get("category") != "spot":
        raise BybitDemoStateParseError(f"{operation}: category must be spot.")
    if not all(isinstance(record, Mapping) for record in result["list"]):
        raise BybitDemoStateParseError(f"{operation}: every record must be a Mapping.")
    timestamp = _timestamp(response.get("time"), f"{operation}.time")
    return result, timestamp


def _order(record: Mapping, account_id, broker_timestamp, fetched_at) -> OrderState:
    order_id = _text(record.get("orderId"), "orderId")
    symbol = _text(record.get("symbol"), "symbol", uppercase=True)
    side = {"Buy": "BUY", "Sell": "SELL"}.get(record.get("side")) if isinstance(record.get("side"), str) else None
    order_type = {"Market": "MARKET", "Limit": "LIMIT"}.get(record.get("orderType")) if isinstance(record.get("orderType"), str) else None
    if side is None or order_type is None:
        raise BybitDemoStateParseError("Order side or type is unsupported.")
    if record.get("isLeverage", "0") != "0":
        raise BybitDemoStateParseError("Margin orders are outside the Spot read contract.")
    external_status = _text(record.get("orderStatus"), "orderStatus")
    status = _STATUS_MAP.get(external_status, OrderStatus.UNKNOWN)
    requested = _number(record.get("qty"), "qty", nonnegative=True)
    if requested == 0:
        raise BybitDemoStateParseError("Order qty must be positive.")
    filled_base = _number(record.get("cumExecQty"), "cumExecQty", nonnegative=True)
    filled_quote = _number(record.get("cumExecValue"), "cumExecValue", optional=True, nonnegative=True)
    if filled_quote is not None and ((filled_base == 0) != (filled_quote == 0)):
        raise BybitDemoStateParseError("Executed base quantity and quote value disagree about whether a fill occurred.")
    if order_type == "MARKET":
        unit = {"baseCoin": "BASE", "quoteCoin": "QUOTE"}.get(record.get("marketUnit")) if isinstance(record.get("marketUnit"), str) else None
        if unit is None:
            raise BybitDemoStateParseError("Market order requires an explicit supported marketUnit.")
        if side == "SELL" and unit == "QUOTE":
            raise BybitDemoStateParseError("Quote-unit Market SELL is outside the Spot read contract.")
    else:
        unit = "BASE"
    filled = filled_base if unit == "BASE" else filled_quote
    if filled is None or filled > requested:
        raise BybitDemoStateParseError("Filled amount is missing or exceeds same-unit requested amount.")
    remaining = _exact_difference(requested, filled)
    if status in (OrderStatus.NEW, OrderStatus.OPEN, OrderStatus.REJECTED) and filled != 0:
        raise BybitDemoStateParseError("Order status contradicts filled amount.")
    if status == OrderStatus.PARTIALLY_FILLED and not (0 < filled < requested):
        raise BybitDemoStateParseError("Partial status requires an intermediate filled amount.")
    if status == OrderStatus.FILLED and (filled == 0 or (unit == "BASE" and remaining != 0)):
        raise BybitDemoStateParseError("Filled status contradicts same-unit execution amounts.")
    created_at = _timestamp(record.get("createdTime"), "createdTime")
    updated_at = _timestamp(record.get("updatedTime"), "updatedTime")
    if updated_at < created_at:
        raise BybitDemoStateParseError("updatedTime precedes createdTime.")
    limit_price = _price(record.get("price"), "price") if order_type == "LIMIT" else None
    if order_type == "LIMIT" and limit_price is None:
        raise BybitDemoStateParseError("Limit order requires a positive limit price.")
    return OrderState(
        broker_id="bybit-demo", account_id=account_id, broker_order_id=order_id,
        symbol=symbol, side=side, order_type=order_type, status=status,
        external_status=external_status, quantity_unit=unit,
        requested_quantity=requested, filled_quantity=filled, remaining_quantity=remaining,
        filled_base_quantity=filled_base, filled_quote_amount=filled_quote,
        average_fill_price=_price(record.get("avgPrice"), "avgPrice"),
        limit_price=limit_price, stop_price=_price(record.get("triggerPrice"), "triggerPrice"),
        created_at=created_at, updated_at=updated_at,
        broker_timestamp=broker_timestamp, fetched_at=fetched_at,
        order_link_id=_optional_text(record.get("orderLinkId"), "orderLinkId"),
    )


def _execution(record: Mapping, account_id, broker_timestamp, fetched_at) -> ExecutionState:
    if record.get("execType") != "Trade":
        raise BybitDemoStateParseError("Execution type must be Trade; non-trade records are not fills.")
    if record.get("isLeverage", "0") != "0":
        raise BybitDemoStateParseError("Margin executions are outside the Spot read contract.")
    side = {"Buy": "BUY", "Sell": "SELL"}.get(record.get("side")) if isinstance(record.get("side"), str) else None
    if side is None:
        raise BybitDemoStateParseError("Execution side is unsupported.")
    quantity = _number(record.get("execQty"), "execQty", nonnegative=True)
    price = _number(record.get("execPrice"), "execPrice", nonnegative=True)
    if quantity == 0 or price == 0:
        raise BybitDemoStateParseError("Execution quantity and price must be positive.")
    return ExecutionState(
        broker_id="bybit-demo", account_id=account_id,
        broker_execution_id=_text(record.get("execId"), "execId"),
        broker_order_id=_text(record.get("orderId"), "orderId"),
        order_link_id=_optional_text(record.get("orderLinkId"), "orderLinkId"),
        symbol=_text(record.get("symbol"), "symbol", uppercase=True), side=side,
        executed_quantity=quantity, execution_price=price,
        execution_fee=_number(record.get("execFee"), "execFee"),
        fee_currency=_optional_text(record.get("feeCurrency"), "feeCurrency", uppercase=True),
        executed_at=_timestamp(record.get("execTime"), "execTime"),
        broker_timestamp=broker_timestamp, fetched_at=fetched_at,
    )


class BybitDemoReadOnlyAdapter:
    """Expose only complete normalized snapshots through four read operations.

    Supply a Stage 9.2 Demo session. No SDK client is exposed by the public API;
    a closed read-method allowlist prevents accidental mutation dispatch.
    """

    __slots__ = ("_session", "_account_id")

    def __init__(self, session, *, account_id: str | None = None):
        self._session = session
        self._account_id = None if account_id is None else _text(account_id, "account_id")
        self._validate_session()
        if not all(callable(getattr(session, method, None)) for method in _READ_METHODS):
            raise TypeError("Demo session must provide the four required read methods.")

    def _validate_session(self) -> None:
        session = self._session
        if (
            getattr(session, "testnet", None) is not False
            or getattr(session, "demo", None) is not True
            or getattr(session, "endpoint", None) != "https://api-demo.bybit.com"
            or getattr(session, "force_retry", None) is not False
            or type(getattr(session, "max_retries", None)) is not int
            or session.max_retries != 1
            or getattr(session, "retry_delay", None) != 0
            or getattr(session, "log_requests", None) is not False
        ):
            raise BybitDemoReadError("Session must retain Stage 9.2 Demo endpoint and safety settings.")

    def _read(self, operation: str, **kwargs):
        if operation not in _READ_METHODS:
            raise BybitDemoReadError("Operation is outside the read-only allowlist.")
        self._validate_session()
        try:
            return getattr(self._session, operation)(**kwargs)
        except Exception as error:
            # SDK errors may embed authenticated requests; retain only safe context.
            raise BybitDemoReadError(f"{operation} failed ({type(error).__name__}).") from None

    def get_account_state(self) -> AccountState:
        """Read USD UTA aggregates and separate coins; never invent spendable coin cash."""
        result, timestamp = _result(self._read("get_wallet_balance", accountType="UNIFIED"), "get_wallet_balance")
        accounts = result["list"]
        if len(accounts) != 1 or accounts[0].get("accountType") != "UNIFIED":
            raise BybitDemoStateParseError("Wallet result must contain exactly one UNIFIED account.")
        account = accounts[0]
        if not all(name in account for name in ("totalAvailableBalance", "totalWalletBalance", "totalEquity")):
            raise BybitDemoStateParseError("Account aggregate balance fields are missing.")
        coins = account.get("coin")
        if not isinstance(coins, list) or not all(isinstance(coin, Mapping) for coin in coins):
            raise BybitDemoStateParseError("Account coin balances must be a list of Mappings.")
        balances = []
        seen = set()
        for coin in coins:
            currency = _text(coin.get("coin"), "coin", uppercase=True)
            if currency in seen:
                raise BybitDemoStateParseError("Duplicate currency in account balances.")
            seen.add(currency)
            balances.append(CurrencyBalance(
                currency=currency,
                total_balance=_number(coin.get("walletBalance"), "walletBalance"),
                total_equity=_number(coin.get("equity"), "equity", optional=True),
                locked_balance=_number(coin.get("locked"), "locked", optional=True, nonnegative=True),
            ))
        # Bybit's account-wide values are USD, not USDT or a particular coin.
        return AccountState(
            broker_id="bybit-demo", account_id=self._account_id, currency="USD",
            available_balance=_number(account.get("totalAvailableBalance"), "totalAvailableBalance", optional=True),
            total_balance=_number(account.get("totalWalletBalance"), "totalWalletBalance", optional=True),
            total_equity=_number(account.get("totalEquity"), "totalEquity", optional=True),
            balances=tuple(balances), broker_timestamp=timestamp,
            fetched_at=datetime.now(timezone.utc),
        )

    def get_open_orders(self, symbol: str | None = None) -> tuple[OrderState, ...]:
        """Read all Spot open-order pages atomically; pagination is bounded to 100 pages."""
        params = {"category": "spot", "openOnly": 0, "limit": 50}
        if symbol is not None:
            params["symbol"] = _text(symbol, "symbol", uppercase=True)
        orders, seen_ids, seen_cursors = [], set(), set()
        for _ in range(100):
            result, timestamp = _result(self._read("get_open_orders", **params), "get_open_orders", orders=True)
            fetched_at = datetime.now(timezone.utc)
            for record in result["list"]:
                order = _order(record, self._account_id, timestamp, fetched_at)
                if symbol is not None and order.symbol != symbol:
                    raise BybitDemoStateParseError("Returned order symbol does not match the requested symbol.")
                if order.broker_order_id in seen_ids:
                    raise BybitDemoStateParseError("Duplicate order across open-order pages.")
                if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                    raise BybitDemoStateParseError("Closed order returned by the open-only query.")
                seen_ids.add(order.broker_order_id)
                orders.append(order)
            cursor = result.get("nextPageCursor")
            if not isinstance(cursor, str) or cursor != cursor.strip():
                raise BybitDemoStateParseError("Open-order pagination cursor is missing or malformed.")
            if not cursor:
                return tuple(orders)
            if cursor in seen_cursors or not result["list"]:
                raise BybitDemoStateParseError("Open-order pagination did not make progress.")
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        raise BybitDemoStateParseError("Open-order pagination exceeded the 100-page safety bound.")

    def get_order(self, order_id: str) -> OrderState:
        """Read one ID, falling back to retained history only after a valid empty realtime result."""
        order_id = _text(order_id, "order_id")
        for operation in ("get_open_orders", "get_order_history"):
            result, timestamp = _result(self._read(operation, category="spot", orderId=order_id), operation, orders=True)
            records = result["list"]
            if not records:
                continue
            if len(records) != 1:
                raise BybitDemoStateParseError("Exact order lookup returned multiple records.")
            order = _order(records[0], self._account_id, timestamp, datetime.now(timezone.utc))
            if order.broker_order_id != order_id:
                raise BybitDemoStateParseError("Returned order ID does not match the requested ID.")
            return order
        raise BrokerOrderNotFoundError("Order was not observed in realtime or retained history; outcome remains unknown.")

    def get_executions(
        self, order_id: str | None = None, symbol: str | None = None,
    ) -> tuple[ExecutionState, ...]:
        """Read reported Spot Trade fills, at most 100 pages in the broker's default window.

        Without explicit time bounds Bybit returns its default seven-day window;
        an empty tuple is no observed fills there, not proof an order never filled.
        """
        params = {"category": "spot", "execType": "Trade", "limit": 100}
        if order_id is not None:
            params["orderId"] = _text(order_id, "order_id")
        if symbol is not None:
            params["symbol"] = _text(symbol, "symbol", uppercase=True)
        executions, seen_ids, seen_cursors = [], set(), set()
        for _ in range(100):
            result, timestamp = _result(self._read("get_executions", **params), "get_executions", orders=True)
            fetched_at = datetime.now(timezone.utc)
            for record in result["list"]:
                execution = _execution(record, self._account_id, timestamp, fetched_at)
                if order_id is not None and execution.broker_order_id != order_id:
                    raise BybitDemoStateParseError("Returned execution order ID does not match the requested ID.")
                if symbol is not None and execution.symbol != symbol:
                    raise BybitDemoStateParseError("Returned execution symbol does not match the requested symbol.")
                if execution.broker_execution_id in seen_ids:
                    raise BybitDemoStateParseError("Duplicate execution across fill pages.")
                seen_ids.add(execution.broker_execution_id)
                executions.append(execution)
            cursor = result.get("nextPageCursor")
            if not isinstance(cursor, str) or cursor != cursor.strip():
                raise BybitDemoStateParseError("Execution pagination cursor is missing or malformed.")
            if not cursor:
                return tuple(executions)
            if cursor in seen_cursors or not result["list"]:
                raise BybitDemoStateParseError("Execution pagination did not make progress.")
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        raise BybitDemoStateParseError("Execution pagination exceeded the 100-page safety bound.")
