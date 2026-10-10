"""Broker-independent authorized Spot requests and acceptance receipts, not fills."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class SpotMarketOrderRequest:
    """Caller authorization; adapter validates units and normalizes amounts down.

    BUY requires QUOTE, SELL requires BASE. Exact Decimal/int/string amounts
    are validated by the instrument boundary; no wallet or risk policy is implied.
    """

    symbol: str
    side: Literal["BUY", "SELL"]
    authorized_amount: Decimal | int | str
    amount_unit: Literal["QUOTE", "BASE"]
    order_link_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpotMarketOrderAcknowledgement:
    """Acceptance of a submitted request; carries no status or execution evidence."""

    broker_id: str
    broker_order_id: str
    order_link_id: str | None
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    submitted_amount: Decimal
    amount_unit: Literal["QUOTE", "BASE"]
    broker_timestamp: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class OrderCancellationAcknowledgement:
    """Acceptance of an exact-order cancellation, not terminal CANCELLED state."""

    broker_id: str
    broker_order_id: str
    order_link_id: str | None
    symbol: str
    broker_timestamp: datetime
    fetched_at: datetime
