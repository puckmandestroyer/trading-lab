"""Exact detailed text; float conversion exists only at the chart boundary."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import math

from .model import DashboardError

UNAVAILABLE = "Unavailable"


def format_value(value):
    if value is None:
        return UNAVAILABLE
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        if not value.is_finite():
            raise DashboardError("Invalid dashboard amount.")
        if value == 0:
            return "0"
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if type(value) is bool:
        return "Yes" if value else "No"
    if type(value) in (str, int):
        return str(value)
    if type(value) is tuple:
        return ", ".join(format_value(item) for item in value) or UNAVAILABLE
    raise DashboardError("Unsupported dashboard display value.")


def format_timestamp(milliseconds):
    if milliseconds is None:
        return UNAVAILABLE
    if type(milliseconds) is not int or milliseconds < 0:
        raise DashboardError("Invalid dashboard timestamp.")
    try:
        date = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)
        return date.strftime("%Y-%m-%d %H:%M:%S") + f".{milliseconds % 1000:03d} UTC"
    except (ValueError, OverflowError):
        return "Unavailable (outside display date range)"


def field_rows(record, names):
    return [{"Field": name, "Value": format_timestamp(getattr(record, name)) if name.endswith("_ms")
             else format_value(getattr(record, name))} for name in names]


def event_rows(events):
    return [{"Observed UTC": format_timestamp(event.observed_at_ms),
             "Occurred UTC": format_timestamp(event.occurred_at_ms), "Severity": event.severity.value,
             "Event": event.event_type.value, "Source": event.source, "Reference": event.event_id[:12],
             "Summary": event.summary} for event in events]


def chart_rows(points):
    """Approximate rendering only. Refuse float overflow/nonzero underflow."""
    rows = []
    for timestamp, amount in points:
        if type(amount) is not Decimal or not amount.is_finite():
            raise DashboardError("History cannot be plotted safely.")
        number = float(amount)
        if not math.isfinite(number) or number == 0 and amount != 0:
            raise DashboardError("History cannot be plotted safely.")
        rows.append({"Time UTC": format_timestamp(timestamp), "Value": number})
    return rows
