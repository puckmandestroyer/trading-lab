"""Immutable, strategy-agnostic display records; never trading authority."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..observability.health import HealthSnapshot
from ..observability.model import ObservabilityEvent, EvidenceFreshness, ObservabilityHealthLevel

DASHBOARD_VIEWS = ("Overview", "Position / Orders", "Risk", "Trades", "Runtime Health", "Event / Error History")
DEFAULT_HISTORY_LIMIT = 250
MAX_HISTORY_LIMIT = 1000
SNAPSHOT_MAX_AGE_MS = 120_000  # Display-only threshold; never a runtime deadline.


class DashboardError(ValueError):
    """Fixed safe diagnostics only; no paths or raw parser exceptions."""


class DashboardNotice(str, Enum):
    HISTORY_LIMITED = "HISTORY_LIMITED"
    TORN_TAIL = "TORN_TAIL"
    HISTORY_CORRUPT = "HISTORY_CORRUPT"
    HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"
    HISTORY_RESOURCE_LIMIT = "HISTORY_RESOURCE_LIMIT"
    CANDIDATE_UNAVAILABLE = "CANDIDATE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DashboardInstance:
    instance_name: str
    broker_id: str
    account_binding: str
    bot_id: str
    strategy_id: str
    symbol: str
    timeframe: str

    @property
    def label(self):
        return f"{self.strategy_id} · {self.symbol} · {self.timeframe} · {self.bot_id} · {self.account_binding}"


@dataclass(frozen=True, slots=True)
class DashboardDiscovery:
    instances: tuple[DashboardInstance, ...]
    notices: tuple[DashboardNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    snapshot_age_ms: int | None
    snapshot_freshness: EvidenceFreshness
    display_health: ObservabilityHealthLevel
    drawdown_percentage: Decimal | None
    snapshot_max_age_ms: int


@dataclass(frozen=True, slots=True)
class DashboardExecution:
    execution_id: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str | None
    executed_at_ms: int


@dataclass(frozen=True, slots=True)
class DashboardTrade:
    open_event_id: str
    close_event_id: str
    entry_time_ms: int | None
    exit_time_ms: int | None
    initial_owned_quantity: Decimal
    pre_close_owned_quantity: Decimal
    entry_execution_ids: tuple[str, ...]
    exit_execution_ids: tuple[str, ...]
    executions: tuple[DashboardExecution, ...]
    realized_pnl_quote: Decimal | None


@dataclass(frozen=True, slots=True)
class DashboardModel:
    identity: DashboardInstance
    health: HealthSnapshot
    events: tuple[ObservabilityEvent, ...]
    overview: DashboardOverview
    trades: tuple[DashboardTrade, ...]
    trade_history_incomplete: bool
    notices: tuple[DashboardNotice, ...]

    @property
    def views(self):
        return DASHBOARD_VIEWS
