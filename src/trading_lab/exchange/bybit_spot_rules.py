"""Spot metadata and exact Market amounts; only explicit fetches perform I/O."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from numbers import Integral


class BybitSpotInstrumentError(RuntimeError):
    """Spot instrument metadata is malformed or unusable."""


class BybitSpotOrderConstraintError(ValueError):
    """An authorized Market amount cannot satisfy the available Spot rules."""


@dataclass(frozen=True, slots=True)
class BybitSpotInstrumentRules:
    """Immutable current Spot metadata; numeric rules are positive Decimals."""

    symbol: str
    base_coin: str
    quote_coin: str
    status: str
    base_precision: Decimal
    quote_precision: Decimal
    min_order_amount: Decimal
    max_market_order_quantity: Decimal
    tick_size: Decimal

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        for name in ("base_coin", "quote_coin"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise BybitSpotInstrumentError(f"{name} must be a non-empty coin string.")
        if self.status != "Trading":
            raise BybitSpotInstrumentError("Spot instrument status must be Trading.")
        for name in (
            "base_precision", "quote_precision", "min_order_amount",
            "max_market_order_quantity", "tick_size",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise BybitSpotInstrumentError(f"{name} must be a positive finite Decimal.")


def _validate_symbol(symbol: str) -> None:
    if (
        not isinstance(symbol, str) or not symbol or symbol != symbol.strip()
        or symbol != symbol.upper()
    ):
        raise BybitSpotInstrumentError("symbol must be a non-empty uppercase string without surrounding whitespace.")


def _parse_metadata_decimal(value, name: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise BybitSpotInstrumentError(f"{name} must be a decimal string.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise BybitSpotInstrumentError(f"{name} must be a valid decimal string.") from None
    if not number.is_finite() or number <= 0:
        raise BybitSpotInstrumentError(f"{name} must be positive and finite.")
    return number


def fetch_bybit_spot_instrument_rules(session, symbol: str) -> BybitSpotInstrumentRules:
    """Fetch one exact Spot symbol using the supplied client; no retries or cache."""
    _validate_symbol(symbol)
    fetch = getattr(session, "get_instruments_info", None)
    if not callable(fetch):
        raise TypeError("session must provide callable get_instruments_info.")
    response = fetch(category="spot", symbol=symbol)
    if not isinstance(response, Mapping):
        raise BybitSpotInstrumentError("Instrument response must be a Mapping.")
    code = response.get("retCode")
    if type(code) is not int or code != 0:
        raise BybitSpotInstrumentError("Instrument response must contain successful integer retCode 0.")
    result = response.get("result")
    if not isinstance(result, Mapping) or result.get("category") != "spot":
        raise BybitSpotInstrumentError("Instrument result must be a Mapping with category spot.")
    records = result.get("list")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], Mapping):
        raise BybitSpotInstrumentError("Exact-symbol result must contain exactly one instrument Mapping.")
    record = records[0]
    if record.get("symbol") != symbol:
        raise BybitSpotInstrumentError("Returned instrument symbol must match the requested symbol.")
    lot = record.get("lotSizeFilter")
    price = record.get("priceFilter")
    if not isinstance(lot, Mapping) or not isinstance(price, Mapping):
        raise BybitSpotInstrumentError("lotSizeFilter and priceFilter must be Mappings.")
    # Only current Spot fields are authoritative; deprecated fields are ignored.
    return BybitSpotInstrumentRules(
        symbol=record["symbol"],
        base_coin=record.get("baseCoin"),
        quote_coin=record.get("quoteCoin"),
        status=record.get("status"),
        base_precision=_parse_metadata_decimal(lot.get("basePrecision"), "basePrecision"),
        quote_precision=_parse_metadata_decimal(lot.get("quotePrecision"), "quotePrecision"),
        min_order_amount=_parse_metadata_decimal(lot.get("minOrderAmt"), "minOrderAmt"),
        max_market_order_quantity=_parse_metadata_decimal(lot.get("maxMarketOrderQty"), "maxMarketOrderQty"),
        tick_size=_parse_metadata_decimal(price.get("tickSize"), "tickSize"),
    )


def _parse_authorized_amount(value) -> Decimal:
    if isinstance(value, bool):
        raise BybitSpotOrderConstraintError("Amount must be a Decimal, integer, or decimal string; bool is invalid.")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, Integral):
        amount = Decimal(int(value))
    elif isinstance(value, str) and value and value == value.strip():
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise BybitSpotOrderConstraintError("Amount must be a valid decimal string.") from None
    else:
        raise BybitSpotOrderConstraintError("Amount must be a Decimal, integer, or decimal string without surrounding whitespace.")
    if not amount.is_finite() or amount <= 0:
        raise BybitSpotOrderConstraintError("Amount must be positive and finite.")
    return amount


def _floor_to_step(amount: Decimal, step: Decimal) -> Decimal:
    # Integer ratios keep the step count exact even with a small Decimal context.
    amount_numerator, amount_denominator = amount.as_integer_ratio()
    step_numerator, step_denominator = step.as_integer_ratio()
    steps = (amount_numerator * step_denominator) // (amount_denominator * step_numerator)
    parts = step.as_tuple()
    coefficient = 0
    for digit in parts.digits:
        coefficient = coefficient * 10 + digit
    # Tuple construction also avoids context rounding when rebuilding the result.
    digits = Decimal(steps * coefficient).as_tuple().digits
    normalized = Decimal((0, digits, parts.exponent))
    if normalized == 0:
        raise BybitSpotOrderConstraintError("Amount becomes zero after precision rounding.")
    return normalized


def _canonical_amount(amount: Decimal) -> str:
    text = format(amount, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize_spot_market_buy_quote_amount(rules: BybitSpotInstrumentRules, amount) -> str:
    """Round quote budget down and check its minimum; no price-based BUY maximum."""
    if not isinstance(rules, BybitSpotInstrumentRules):
        raise TypeError("rules must be a BybitSpotInstrumentRules instance.")
    normalized = _floor_to_step(_parse_authorized_amount(amount), rules.quote_precision)
    if normalized < rules.min_order_amount:
        raise BybitSpotOrderConstraintError("Normalized quote amount is below minOrderAmt.")
    # A base-quantity maximum cannot be compared with a quote budget without price.
    return _canonical_amount(normalized)


def normalize_spot_market_sell_base_quantity(rules: BybitSpotInstrumentRules, quantity) -> str:
    """Round base quantity down and check its Market maximum; no price-based minimum."""
    if not isinstance(rules, BybitSpotInstrumentRules):
        raise TypeError("rules must be a BybitSpotInstrumentRules instance.")
    normalized = _floor_to_step(_parse_authorized_amount(quantity), rules.base_precision)
    if normalized > rules.max_market_order_quantity:
        raise BybitSpotOrderConstraintError("Normalized base quantity exceeds maxMarketOrderQty.")
    # minOrderAmt is quote notional, not a base-quantity minimum; no price is supplied.
    return _canonical_amount(normalized)
