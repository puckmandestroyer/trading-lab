"""Generic local read-only dashboard; framework and execution stay separate."""

from .model import (DASHBOARD_VIEWS, DashboardError, DashboardNotice, DashboardInstance,
                    DashboardDiscovery, DashboardOverview, DashboardExecution, DashboardTrade, DashboardModel, DashboardPerformance)
from .analytics import build_dashboard_model, recent_events, display_percentage, filter_events, history_series, performance_series
from .loader import discover_instances, load_dashboard
from .formatting import format_value, format_timestamp, event_rows, chart_rows, format_signed, format_percent, format_instance_label

__all__ = ["DASHBOARD_VIEWS", "DashboardError", "DashboardNotice", "DashboardInstance",
           "DashboardDiscovery", "DashboardOverview", "DashboardExecution", "DashboardTrade", "DashboardModel",
           "build_dashboard_model", "recent_events", "display_percentage", "filter_events", "history_series",
           "discover_instances", "load_dashboard", "format_value", "format_timestamp", "event_rows", "chart_rows",
           "DashboardPerformance", "performance_series", "format_signed", "format_percent", "format_instance_label"]
