"""Local read-only rendering; start with an explicit observability root."""

import argparse
import sys
import time

import streamlit as st

from trading_lab.dashboard import (DashboardError, DashboardNotice, discover_instances, load_dashboard,
    format_value, format_timestamp, event_rows, chart_rows, filter_events, history_series)
from trading_lab.dashboard.formatting import field_rows

_NOTICES = {
    DashboardNotice.HISTORY_LIMITED: "Showing a bounded recent history window; earlier records may be unavailable.",
    DashboardNotice.TORN_TAIL: "Event history degraded: unfinished final line. Valid preceding records are shown.",
    DashboardNotice.HISTORY_CORRUPT: "Event history corrupt: invalid complete record or identity/segment mismatch. History is unavailable.",
    DashboardNotice.HISTORY_UNAVAILABLE: "Event history unavailable: missing, unsafe or unreadable local data.",
    DashboardNotice.HISTORY_RESOURCE_LIMIT: "Event history unavailable: a file, byte or record bound was exceeded.",
    DashboardNotice.CANDIDATE_UNAVAILABLE: "Some observability candidates are unavailable or invalid.",
}


def _table(ui, rows):
    if rows:
        ui.dataframe(rows, hide_index=True, width="stretch")
    else:
        ui.info("No retained records available.")


def _chart(ui, model, field, label):
    points = history_series(model, field)
    if len(points) < 2:
        ui.info(label + ": Insufficient history.")
        return
    try:
        rows = chart_rows(points)
    except DashboardError:
        ui.info(label + ": values cannot be plotted safely; exact values remain in the tables.")
        return
    ui.caption(label + " — retained observations only; chart values are approximate.")
    ui.line_chart(rows, x="Time UTC", y="Value", x_label="Recorded evidence time UTC", y_label=label)


def render_dashboard(model, ui=st):
    """The same six-view template renders every validated instance identity."""
    identity, health, overview = model.identity, model.health, model.overview
    ui.title("Trading Lab — Runtime Monitor")
    for column, field in zip(ui.columns(4), ("strategy_id", "symbol", "timeframe", "bot_id")):
        column.metric(field.replace("_id", "").title(), getattr(identity, field))
    ui.text(f"Broker: {identity.broker_id} | Account binding: {identity.account_binding}")
    ui.caption("Read-only local observations. Snapshot and event history are separate observation boundaries.")
    level = overview.display_health.value
    getattr(ui, {"OK": "success", "ATTENTION": "warning", "CRITICAL": "error"}[level])(
        f"{level} · Snapshot {overview.snapshot_freshness.value} · Runtime {health.runtime_state.value}")
    for notice in model.notices:
        ui.warning(_NOTICES[notice])
    tabs = ui.tabs(model.views)
    with tabs[0]:
        risk_state = "TRIPPED" if health.risk_trip_reason is not None else "ACTIVE" if health.risk_active else "NOT READY"
        metrics = (
            ("Runtime state", health.runtime_state), ("Overall health (display)", overview.display_health),
            ("Risk state", risk_state), ("Owned base quantity", health.owned_base_quantity),
            ("Latest accepted mark", health.latest_accepted_mark_price), ("Risk equity", health.risk_equity),
            ("Daily PnL", health.daily_pnl),
            ("Drawdown (display %)", None if overview.drawdown_percentage is None else format_value(overview.drawdown_percentage) + "%"),
            ("Entries used / limit", format_value(health.entries_this_utc_day) + " / " + format_value(health.max_entries_per_utc_day)),
        )
        for index in range(0, len(metrics), 3):
            for column, (label, value) in zip(ui.columns(3), metrics[index:index+3]):
                column.metric(label, format_value(value))
        _table(ui, field_rows(health, ("position_evidence", "runtime_reason", "last_processed_candle_ms",
            "last_reconciled_at_ms", "pending_action_id", "pending_action_phase")) + [
                {"Field": "snapshot_age_ms", "Value": format_value(overview.snapshot_age_ms)},
                {"Field": "display_snapshot_freshness", "Value": overview.snapshot_freshness.value}])
    with tabs[1]:
        _table(ui, field_rows(health, ("position_evidence", "owned_base_quantity", "desired_position",
            "pending_action_id", "pending_action_kind", "pending_action_phase", "pending_reconciliation_deadline_ms",
            "last_reconciled_at_ms", "last_broker_observation_at_ms")))
        ui.caption("Acknowledgement is not fill evidence; pending/unknown outcomes remain explicit.")
        _table(ui, event_rows(tuple(event for event in model.events
            if event.event_type.value.startswith("ACTION_") or event.event_type.value == "OWNED_EXECUTION_DISCOVERED")))
        _chart(ui, model, "owned_base_quantity", "Confirmed owned quantity")
    with tabs[2]:
        ui.caption("Percentages are rounded to six decimal places for display. Exact source amounts remain below; wallet totals are not risk equity.")
        _table(ui, field_rows(health, ("risk_active", "risk_capital_quote", "buy_quote_budget", "max_entry_notional_quote",
            "max_position_notional_quote", "max_daily_loss_fraction", "max_drawdown_fraction", "max_entries_per_utc_day",
            "risk_equity", "peak_risk_equity", "utc_day_start_risk_equity", "daily_pnl", "entries_this_utc_day",
            "drawdown_numerator", "drawdown_denominator", "risk_trip_reason", "tripped_at_ms", "risk_epoch_id",
            "risk_epoch_sequence", "risk_configuration_digest", "valued_at_ms", "base_currency", "quote_currency")))
        ui.caption("Risk trip and rearm history: a child epoch does not erase accounting history.")
        _table(ui, event_rows(tuple(event for event in model.events if event.event_type.value in ("RISK_TRIPPED", "RISK_REARMED"))))
        _chart(ui, model, "risk_equity", "Risk equity")
        _chart(ui, model, "daily_pnl", "Daily PnL")
    with tabs[3]:
        if model.trade_history_incomplete:
            ui.warning("History incomplete / unavailable. Only retained confirmed closed cycles are listed.")
        ui.caption("Quantities show initial and pre-close owned exposure, not inferred total order size. PnL is shown only when supplied exactly by the closing event.")
        _table(ui, [{"Entry UTC": format_timestamp(trade.entry_time_ms), "Exit UTC": format_timestamp(trade.exit_time_ms),
            "Initial owned quantity": format_value(trade.initial_owned_quantity),
            "Pre-close owned quantity": format_value(trade.pre_close_owned_quantity),
            "Realized PnL (quote)": format_value(trade.realized_pnl_quote), "Close reference": trade.close_event_id[:12]}
            for trade in model.trades])
        for trade in model.trades:
            with ui.expander("Confirmed cycle " + trade.close_event_id[:12]):
                ui.text("OPEN event: " + trade.open_event_id + "\nCLOSE event: " + trade.close_event_id)
                ui.text("Entry executions: " + format_value(trade.entry_execution_ids)
                        + "\nExit executions: " + format_value(trade.exit_execution_ids))
                _table(ui, [{"Execution ID": execution.execution_id, "Side": execution.side,
                    "Quantity": format_value(execution.quantity), "Price": format_value(execution.price),
                    "Signed fee": format_value(execution.fee), "Fee currency": format_value(execution.fee_currency),
                    "Executed UTC": format_timestamp(execution.executed_at_ms)} for execution in trade.executions])
                if not trade.executions or len(trade.executions) < len(set(trade.entry_execution_ids + trade.exit_execution_ids)):
                    ui.info("Execution/fee history unavailable or incomplete; no fee totals are inferred.")
    with tabs[4]:
        _table(ui, field_rows(health, ("generated_at_ms", "process_started_at_ms", "last_scheduler_activity_ms",
            "last_cycle_activity_ms", "last_cycle_outcome", "runtime_state", "runtime_reason", "checkpoint_sequence",
            "overall_health", "reason_codes", "generated_freshness", "market_freshness", "reconciliation_freshness",
            "broker_freshness", "risk_freshness", "last_processed_candle_ms", "latest_accepted_candle_open_ms",
            "market_valued_at_ms", "last_reconciled_at_ms", "last_broker_observation_at_ms", "pending_action_id",
            "pending_action_kind", "pending_action_phase", "pending_reconciliation_deadline_ms", "halted_at_ms",
            "rearmed_at_ms", "observability_status")) + [
                {"Field": "viewer_snapshot_age_ms", "Value": format_value(overview.snapshot_age_ms)},
                {"Field": "viewer_snapshot_freshness", "Value": overview.snapshot_freshness.value}])
        ui.caption(f"Stored freshness describes generation time. Viewer freshness ages the snapshot with a separate {overview.snapshot_max_age_ms}ms presentation threshold.")
        _table(ui, event_rows(tuple(event for event in model.events if event.event_type.value in
            ("RUNTIME_HALTED", "RUNTIME_UNCERTAIN", "RUNTIME_REARMED", "CRITICAL_FAILURE", "OBSERVABILITY_DEGRADED"))))
    with tabs[5]:
        severities = ui.multiselect("Severity", ("INFO", "WARNING", "ERROR", "CRITICAL"),
                                   default=("INFO", "WARNING", "ERROR", "CRITICAL"))
        kinds = ui.multiselect("Event type", sorted({event.event_type.value for event in model.events}))
        events = filter_events(model, severities=tuple(severities), event_types=tuple(kinds)) if severities else ()
        _table(ui, event_rows(events))
        if events:
            by_id = {event.event_id: event for event in events}
            chosen = ui.selectbox("Event detail", tuple(by_id),
                format_func=lambda key: by_id[key].event_type.value + " · " + key[:12])
            with ui.expander("Validated event details / full references"):
                ui.json(by_id[chosen].to_dict())


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise DashboardError("Supply --observability-root with an explicit absolute local path.")


def main(argv=None):
    st.set_page_config(page_title="Trading Lab — Runtime Monitor", layout="wide")
    parser = _Arguments(add_help=False)
    parser.add_argument("--observability-root", required=True)
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        discovery = discover_instances(args.observability_root)
    except DashboardError:
        st.error("Observability root unavailable or invalid. Supply --observability-root with an absolute private local directory.")
        return
    st.sidebar.button("Refresh local files")  # A click reruns this read-only script.
    for notice in discovery.notices:
        st.warning(_NOTICES[notice])
    if not discovery.instances:
        st.info("No valid Trading Lab observability instance found.")
        return
    choices = {instance.instance_name: instance for instance in discovery.instances}
    name = st.sidebar.selectbox("Observability instance", tuple(choices), format_func=lambda key: choices[key].label)
    try:
        model = load_dashboard(args.observability_root, name, now_ms=time.time_ns() // 1_000_000)
    except DashboardError:
        st.error("Selected observability instance unavailable or invalid. Refresh to re-read local files.")
        return
    render_dashboard(model)


if __name__ == "__main__":
    main()
