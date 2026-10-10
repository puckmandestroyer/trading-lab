"""Explicit Demo Spot Market placement/cancellation; no sizing or lifecycle loop."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re

from pybit.exceptions import InvalidRequestError

from .bybit_demo import BybitDemoConfigurationError
from .bybit_spot_rules import (
    fetch_bybit_spot_instrument_rules,
    normalize_spot_market_buy_quote_amount,
    normalize_spot_market_sell_base_quantity,
)
from .order_actions import (
    OrderCancellationAcknowledgement,
    SpotMarketOrderAcknowledgement,
    SpotMarketOrderRequest,
)


class BybitDemoActionError(RuntimeError):
    """An action/preflight failed; messages never retain raw broker/SDK data."""


class BybitDemoOrderRejectedError(BybitDemoActionError):
    """Confirmed nonzero broker error code, distinct from transport uncertainty."""

    def __init__(self, operation: str, ret_code: int):
        self.operation = operation
        self.ret_code = ret_code
        super().__init__(f"{operation}: broker rejected request (retCode={ret_code}).")


class BybitDemoActionParseError(BybitDemoActionError):
    """Untrustworthy acknowledgement; acceptance remains unknown, never retry."""


class BybitDemoAmbiguousActionError(BybitDemoActionError):
    """Request may have reached the broker; no automatic resend is safe."""


_MUTATION_METHODS = frozenset({"place_order", "cancel_order"})


def _text(value, name: str, *, uppercase: bool = False) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or (uppercase and value != value.upper())
    ):
        raise ValueError(f"{name} must be a non-empty string without surrounding whitespace.")
    return value


def _order_link(value) -> str | None:
    if value is None:
        return None
    # Documented Bybit format only; caller owns uniqueness and ID lifecycle.
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,36}", value) is None:
        raise ValueError("order_link_id must contain 1–36 ASCII letters, digits, dashes or underscores.")
    return value


def _acknowledgement(response, operation: str, *, symbol: str):
    if not isinstance(response, Mapping):
        raise BybitDemoActionParseError(f"{operation}: response must be a Mapping; outcome unknown.")
    code = response.get("retCode")
    if type(code) is not int:
        raise BybitDemoActionParseError(f"{operation}: invalid retCode; outcome unknown.")
    if code != 0:
        raise BybitDemoOrderRejectedError(operation, code)
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise BybitDemoActionParseError(f"{operation}: invalid result; outcome unknown.")
    # These echoes are not required by the API; reject disagreement when supplied.
    for field, expected in (("category", "spot"), ("symbol", symbol)):
        if field in result and result[field] != expected:
            raise BybitDemoActionParseError(f"{operation}: mismatched {field}; outcome unknown.")
    try:
        order_id = _text(result.get("orderId"), "orderId")
        link = result.get("orderLinkId")
        link = None if isinstance(link, str) and link == "" else _order_link(link)
    except ValueError:
        raise BybitDemoActionParseError(f"{operation}: invalid order identity; outcome unknown.") from None
    value = response.get("time")
    if type(value) is int:
        milliseconds = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            milliseconds = int(value)
        except ValueError:
            raise BybitDemoActionParseError(f"{operation}: invalid time; outcome unknown.") from None
    else:
        raise BybitDemoActionParseError(f"{operation}: invalid time; outcome unknown.")
    if milliseconds < 0:
        raise BybitDemoActionParseError(f"{operation}: negative time; outcome unknown.")
    try:
        timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)
    except OverflowError:
        raise BybitDemoActionParseError(f"{operation}: time out of range; outcome unknown.") from None
    return order_id, link, timestamp


class BybitDemoOrderAdapter:
    """Two explicitly called mutations using the supplied Stage 9.2 session.

    Placement fetches fresh Stage 9.3 rules once, then makes at most one SDK
    placement call. Cancellation takes an exact broker ID and makes one call.
    Subsequent state/fill confirmation is a separate Stage 9.4 caller action.
    """

    __slots__ = ("_session",)

    def __init__(self, session):
        self._session = session
        self._validate_session()
        if not all(callable(getattr(session, method, None)) for method in (*_MUTATION_METHODS, "get_instruments_info")):
            raise TypeError("Demo session must provide instrument, placement and cancellation methods.")

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
            raise BybitDemoConfigurationError("Session must retain Stage 9.2 Demo endpoint and safety settings.")

    def _mutate(self, operation: str, **params):
        if operation not in _MUTATION_METHODS:
            raise BybitDemoActionError("Operation is outside the Spot action allowlist.")
        self._validate_session()
        try:
            return getattr(self._session, operation)(**params)
        except InvalidRequestError as error:
            # Pinned pybit raises this for a returned broker retCode, not HTTP
            # failure. Do not expose its request, headers, message or repr.
            code = error.status_code
            if type(code) is int and code != 0:
                raise BybitDemoOrderRejectedError(operation, code) from None
            raise BybitDemoAmbiguousActionError(f"{operation}: invalid SDK error code; outcome unknown; no retry.") from None
        except Exception as error:
            raise BybitDemoAmbiguousActionError(f"{operation}: outcome unknown ({type(error).__name__}); no retry.") from None

    def place_market_order(self, request: SpotMarketOrderRequest) -> SpotMarketOrderAcknowledgement:
        """Submit an authorized quote BUY or base SELL; receipt is not a fill."""
        if not isinstance(request, SpotMarketOrderRequest):
            raise TypeError("request must be a SpotMarketOrderRequest.")
        symbol = _text(request.symbol, "symbol", uppercase=True)
        if not isinstance(request.side, str) or request.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL.")
        unit = "QUOTE" if request.side == "BUY" else "BASE"
        if not isinstance(request.amount_unit, str) or request.amount_unit != unit:
            raise ValueError("BUY requires QUOTE authorization; SELL requires BASE authorization.")
        link = _order_link(request.order_link_id)
        self._validate_session()
        try:
            rules = fetch_bybit_spot_instrument_rules(self._session, symbol)
        except Exception as error:
            # Metadata failure occurs before submission, so it is not an
            # ambiguous placement; also sanitize Stage 9.3's SDK propagation.
            raise BybitDemoActionError(f"Instrument preflight failed ({type(error).__name__}); order not submitted.") from None
        if request.side == "BUY":
            amount = normalize_spot_market_buy_quote_amount(rules, request.authorized_amount)
        else:
            amount = normalize_spot_market_sell_base_quantity(rules, request.authorized_amount)
        params = {
            "category": "spot", "symbol": symbol,
            "side": "Buy" if request.side == "BUY" else "Sell",
            "orderType": "Market", "qty": amount,
            "marketUnit": "quoteCoin" if unit == "QUOTE" else "baseCoin",
            "isLeverage": 0,
        }
        if link is not None:
            params["orderLinkId"] = link
        response = self._mutate("place_order", **params)
        order_id, reported_link, timestamp = _acknowledgement(response, "place_order", symbol=symbol)
        if reported_link != link:
            raise BybitDemoActionParseError("place_order: mismatched orderLinkId; outcome unknown.")
        return SpotMarketOrderAcknowledgement(
            broker_id="bybit-demo", broker_order_id=order_id, order_link_id=reported_link,
            symbol=symbol, side=request.side, order_type="MARKET",
            submitted_amount=Decimal(amount), amount_unit=unit,
            broker_timestamp=timestamp, fetched_at=datetime.now(timezone.utc),
        )

    def cancel_order(self, symbol: str, order_id: str) -> OrderCancellationAcknowledgement:
        """Request exact-order cancellation; terminal state needs a separate read."""
        symbol = _text(symbol, "symbol", uppercase=True)
        order_id = _text(order_id, "order_id")
        response = self._mutate("cancel_order", category="spot", symbol=symbol, orderId=order_id)
        reported_id, link, timestamp = _acknowledgement(response, "cancel_order", symbol=symbol)
        if reported_id != order_id:
            raise BybitDemoActionParseError("cancel_order: mismatched orderId; outcome unknown.")
        return OrderCancellationAcknowledgement(
            broker_id="bybit-demo", broker_order_id=reported_id, order_link_id=link,
            symbol=symbol, broker_timestamp=timestamp, fetched_at=datetime.now(timezone.utc),
        )
