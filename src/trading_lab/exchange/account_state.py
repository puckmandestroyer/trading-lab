"""Broker-independent immutable snapshots and a read-only broker interface."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Protocol


class OrderStatus(str, Enum):
    """Finite lifecycle states; UNKNOWN never implies a successful outcome."""

    NEW = "NEW"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class BrokerOrderNotFoundError(LookupError):
    """An order was not observed in the queried broker windows; outcome is unknown."""


class BrokerReadFailureKind(str, Enum):
    """Safe read-failure facts; retry policy belongs to the runtime."""

    TRANSIENT = "TRANSIENT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    MALFORMED_DATA = "MALFORMED_DATA"
    PERMANENT = "PERMANENT"


class BrokerReadError(RuntimeError):
    """A classified read failure without a response, SDK error or retry policy."""

    __slots__ = ("_kind",)

    def __init__(self, kind: BrokerReadFailureKind):
        if not isinstance(kind, BrokerReadFailureKind):
            raise TypeError("An explicit BrokerReadFailureKind is required.")
        if hasattr(self, "_kind"):
            raise AttributeError("Read failure classification is immutable.")
        object.__setattr__(self, "_kind", kind)
        super().__init__(f"Broker read failed ({kind.value}).")

    @property
    def kind(self) -> BrokerReadFailureKind:
        return self._kind

    def __setattr__(self, name, value):
        if name in ("kind", "_kind"):
            raise AttributeError("Read failure classification is immutable.")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in ("kind", "_kind"):
            raise AttributeError("Read failure classification is immutable.")
        super().__delattr__(name)


@dataclass(frozen=True, slots=True)
class CurrencyBalance:
    """One currency's reported balances; unavailable amounts remain None."""

    currency: str
    total_balance: Decimal
    total_equity: Decimal | None
    locked_balance: Decimal | None
    available_balance: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AccountState:
    """Account totals share currency; individual coins stay in separate balances."""

    broker_id: str
    account_id: str | None
    currency: str
    available_balance: Decimal | None
    total_balance: Decimal | None
    total_equity: Decimal | None
    balances: tuple[CurrencyBalance, ...]
    broker_timestamp: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """One reported fill: base quantity, quote-per-base price, and signed fee.

    Fee currency is None when the broker does not report it; no unit is inferred.
    This record observes a fill and provides no order execution capability.
    """

    broker_id: str
    account_id: str | None
    broker_execution_id: str
    broker_order_id: str
    order_link_id: str | None
    symbol: str
    side: Literal["BUY", "SELL"]
    executed_quantity: Decimal
    execution_price: Decimal
    execution_fee: Decimal
    fee_currency: str | None
    executed_at: datetime
    broker_timestamp: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class OrderState:
    """Requested/filled/remaining amounts share quantity_unit, even for quote BUYs.

    Remaining means unfilled authorization, including unused terminal amounts;
    the status determines whether the order is still active.
    """

    broker_id: str
    account_id: str | None
    broker_order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT"]
    status: OrderStatus
    external_status: str
    quantity_unit: Literal["BASE", "QUOTE"]
    requested_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    filled_base_quantity: Decimal
    filled_quote_amount: Decimal | None
    average_fill_price: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    created_at: datetime
    updated_at: datetime
    broker_timestamp: datetime
    fetched_at: datetime
    order_link_id: str | None = None


class ReadOnlyBroker(Protocol):
    """Consumers see normalized objects, never broker payloads or trading methods."""

    def get_account_state(self) -> AccountState: ...

    def get_open_orders(self, symbol: str | None = None) -> tuple[OrderState, ...]: ...

    def get_order(self, order_id: str) -> OrderState: ...

    def get_executions(
        self, order_id: str | None = None, symbol: str | None = None,
    ) -> tuple[ExecutionState, ...]: ...
