"""Stage 12.1e component regression, complemented by automatic wiring tests.

Only temporary journals/artifacts, public production APIs and established
synthetic fixture helpers are used. No private SQL or new trading behavior.
The original audit's missing-wiring blocker is now covered by the production
wrapper regressions in test_observability_runtime_integration, not test hooks.
"""

import ast
from dataclasses import replace
from decimal import Decimal as D, localcontext
import errno
import hashlib
import io
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import requests

from trading_lab.observability import (
    ObservabilityStorage, ObservabilityStorageError,
    ObservabilityValidationError, ObservabilityEventType as T, EvidenceFreshness,
    build_health_snapshot, event_from_json, health_from_json,
    process_started, project_checkpoint_transition, project_retained_events,
    safe_append_event, safe_write_health,
)
from trading_lab.observability import model as event_model, storage as sink, telegram as telegram
from trading_lab.observability.telegram import (
    TelegramHttpTransport, TelegramDeliveryStore, TelegramDeliveryStatus as Delivery,
    TelegramDeliveryStateError, TelegramError, deliver_telegram_event,
    deliver_telegram_events, render_telegram_message,
)
from trading_lab.dashboard import (
    DASHBOARD_VIEWS, DashboardNotice, DashboardError, discover_instances,
    load_dashboard, performance_series, format_value,
)
from trading_lab.dashboard import loader as viewer
from trading_lab.runtime.state import (
    RuntimeState as State, PositionEvidence as Evidence, RuntimeReason as Reason,
    RuntimeStateSnapshot, PendingAction, PendingActionKind,
)
from trading_lab.runtime.store import ActionPhase, ActionRecord, JournalActionKind
from tests import test_runtime_store as store_fixtures
from tests import test_runtime_risk_rearm as risk_fixtures
from tests import test_runtime_integration_regression as golden_fixtures
from tests import test_observability_telegram as http_fixtures

RUN, SECOND_RUN = "0"*32, "1"*32
TOKEN, CHAT = "123456:FAKE_OBSERVABILITY_AUDIT_SECRET", "-1001234567890"
HOUR, DAY = 3_600_000, 86_400_000
PROJECT = Path(__file__).resolve().parents[1]


class Consumers:
    """Explicit test-side composition; never a production emission hook."""

    def setUp(self):
        super().setUp()
        self.root = Path(self.directory).resolve()/"observability-audit"
        self.output = ObservabilityStorage(self.root, self.config)
        self.receipts = TelegramDeliveryStore(self.output, CHAT)
        self.at = 100*HOUR
        for target in ("requests.Session.send", "socket.create_connection", "socket.socket.connect", "os.getenv"):
            self.enterContext(patch(target, side_effect=AssertionError("Offline audit only")))

    def truth(self):
        """Complete fixture-sized public facts, including decision authorization."""
        cp = self.store.get_checkpoint()
        history = () if cp.last_processed_candle_ms is None else tuple(
            (self.store.get_candle(ms), self.store.get_decision(ms))
            for ms in range(self.config.history_anchor_ms, cp.last_processed_candle_ms+HOUR, HOUR))
        return (self.store.get_configuration(), cp, history, self.store.list_actions(), self.store.list_fills(),
            self.store.get_risk_configuration(), self.store.get_current_risk_epoch(),
            self.store.list_risk_valuations(), self.store.list_risk_verdicts())

    def retained(self, run=RUN, at=None):
        return project_retained_events(self.store, run_id=run, observed_at_ms=self.at if at is None else at)

    def health(self, at=None, run=RUN):
        return build_health_snapshot(self.store, run_id=run, process_started_at_ms=0,
                                     generated_at_ms=self.at if at is None else at)

    def publish_artifacts(self, events, *, health=None):
        for event in events:
            self.output.append_event(event)
        self.output.write_health(self.health() if health is None else health)
        return self.load()

    def load(self, **changes):
        return load_dashboard(self.root, self.output.instance_name, **{"now_ms": self.at, **changes})

    def transport(self, *responses):
        self.telegram_session = self.enterContext(http_fixtures.FakeSession(*(responses or (http_fixtures.Response(),))))
        return TelegramHttpTransport(TOKEN, CHAT, session=self.telegram_session,
            sleeper=lambda _: self.fail("No retry sleep expected"))

    def deliver(self, event, *responses):
        return deliver_telegram_event(event, self.transport(*responses), self.receipts, utc_now_ms=lambda: self.at)

    def read_events(self, *, at=None, **bounds):
        return self.output.read_events(self.output.event_filename(self.at if at is None else at),
            **{"max_records": 1000, "max_bytes": 1_000_000, **bounds})

    def transition(self, before, execution_ids=()):
        return project_checkpoint_transition(self.config, before, self.store.get_checkpoint(), run_id=RUN,
            observed_at_ms=self.at, contributing_execution_ids=execution_ids)


class OfflinePipelineTests(Consumers, risk_fixtures.LocalRearmCase):
    def test_restart_reprojection_storage_receipts_and_dashboard_deduplicate_facts(self):
        self.settle(self.acknowledge(), store_fixtures.fill())
        before, first = self.truth(), self.retained()
        self.publish_artifacts(first)
        start = process_started(self.config, run_id=RUN, observed_at_ms=self.at, process_started_at_ms=0)
        self.assertIs(self.deliver(start).status, Delivery.DELIVERED)
        self.reopen()  # Real close/open; no manufactured checkpoint/action history.
        second = self.retained(SECOND_RUN, self.at+1)
        self.assertEqual([e.event_id for e in first], [e.event_id for e in second])
        self.assertTrue(all(a.run_id != b.run_id and a.observed_at_ms != b.observed_at_ms for a,b in zip(first,second)))
        self.publish_artifacts(second, health=self.health(self.at+1, SECOND_RUN))
        self.assertEqual(len(self.read_events().events), len(first)*2)
        self.assertEqual(len(self.load().events), len(first))
        self.assertEqual(self.load().trades, ())  # Catch-up does not invent OPEN/CLOSE.
        self.assertEqual(self.truth(), before)
        later_start = process_started(self.config, run_id=SECOND_RUN, observed_at_ms=self.at+1, process_started_at_ms=self.at)
        self.assertNotEqual(start.event_id, later_start.event_id)
        self.assertIs(self.deliver(start).status, Delivery.ALREADY_DELIVERED)
        self.assertEqual(self.telegram_session.calls, [])

    def test_partial_buy_growth_partial_sell_and_exact_zero_form_one_cycle(self):
        action = self.acknowledge()
        events = []

        def observe(action, quantity, index, *, terminal=False):
            before = self.store.get_checkpoint()
            is_buy = action.side == "BUY"
            time = (HOUR if is_buy else 2*HOUR)+10*index
            fill = replace(store_fixtures.fill("partial-"+str(index)), action_id=action.logical_action_id,
                broker_order_id=action.broker_order_id, order_link_id=action.order_link_id, side=action.side,
                executed_quantity=D(quantity), execution_price=D(100), execution_fee=D(0), fee_currency=None,
                executed_at_ms=time, observed_at_ms=time)
            owned = {1:D("0.02"), 2:D("0.05"), 3:D("0.03"), 4:D(0)}[index]
            state = State.LONG if terminal and owned else State.FLAT if terminal else State.ORDER_PENDING
            snapshot = RuntimeStateSnapshot(state, owned, Evidence.CONFIRMED, int(is_buy),
                None if terminal else before.snapshot.pending_action)
            observed = replace(action, phase=ActionPhase.TERMINAL_CONFIRMED if terminal else action.phase,
                order_status="FILLED" if terminal else "PARTIALLY_FILLED", external_status="Filled" if terminal else "PartiallyFilled",
                observed_at_ms=time, terminal_at_ms=time if terminal else None)
            checkpoint = replace(before, sequence=before.sequence+1, snapshot=snapshot,
                                 last_reconciled_at_ms=time, observed_at_ms=time)
            self.store.record_observation(observed, checkpoint, expected_sequence=before.sequence, fills=(fill,))
            events.extend(self.transition(before, (fill.broker_execution_id,)))
            events.extend(self.retained())
            return observed

        action = observe(action, "0.02", 1)
        self.assertEqual(sum(e.event_type is T.POSITION_OPEN_CONFIRMED for e in events), 1)
        observe(action, "0.03", 2, terminal=True)
        before = self.store.get_checkpoint()
        exit_id = "f"*64
        exit_action = ActionRecord(exit_id, JournalActionKind.EXIT, self.config.symbol, 2*HOUR+600000, 5, 3,
            "bot1-"+exit_id[:23], HOUR, side="SELL", amount_unit="BASE", currency="BTC", authorized_amount=D("0.05"))
        pending = RuntimeStateSnapshot(State.ORDER_PENDING, D("0.05"), Evidence.CONFIRMED, 0,
                                     PendingAction(exit_id, PendingActionKind.EXIT))
        checkpoint = replace(before, sequence=before.sequence+1, snapshot=pending, last_processed_candle_ms=HOUR)
        decision = replace(store_fixtures.decision(HOUR, action=True), signal="LONG_EXIT", desired_position=0, action_id=exit_id)
        self.store.commit_decision(store_fixtures.candle(HOUR), decision, checkpoint, expected_sequence=before.sequence, action=exit_action)
        before = self.store.get_checkpoint()
        self.store.start_attempt(exit_id, replace(before, sequence=before.sequence+1), expected_sequence=before.sequence)
        before = self.store.get_checkpoint()
        exit_action = replace(self.store.get_action(exit_id), phase=ActionPhase.ACKNOWLEDGED, broker_order_id="order-2",
            submitted_amount=D("0.05"), acknowledgement_broker_ms=2*HOUR+1, acknowledgement_observed_ms=2*HOUR+2)
        self.store.record_observation(exit_action, replace(before, sequence=before.sequence+1), expected_sequence=before.sequence)
        exit_action = observe(exit_action, "0.02", 3)
        self.assertFalse(any(e.event_type is T.POSITION_CLOSE_CONFIRMED for e in events))
        observe(exit_action, "0.03", 4, terminal=True)
        before = self.truth()
        model = self.publish_artifacts(tuple(events))
        positions = [e for e in model.events if e.event_type in (T.POSITION_OPEN_CONFIRMED, T.POSITION_QUANTITY_CHANGED, T.POSITION_CLOSE_CONFIRMED)]
        self.assertEqual([sum(e.event_type is kind for e in positions) for kind in
            (T.POSITION_OPEN_CONFIRMED,T.POSITION_QUANTITY_CHANGED,T.POSITION_CLOSE_CONFIRMED)], [1,2,1])
        self.assertEqual(len(model.trades), 1)
        self.assertEqual(len(model.trades[0].executions), 4)
        self.assertIsNone(model.trades[0].realized_pnl_quote)
        closing = next(e for e in positions if e.event_type is T.POSITION_CLOSE_CONFIRMED)
        self.assertNotIn("Realized trade PnL",render_telegram_message(closing))
        self.assertIn("Owned base quantity: 0",render_telegram_message(closing))
        results = deliver_telegram_events(tuple(positions), self.transport(http_fixtures.Response(),http_fixtures.Response()),
                                         self.receipts, utc_now_ms=lambda:self.at)
        self.assertEqual([r.status for r in results].count(Delivery.DELIVERED), 2)
        self.assertIn("order may still be pending", render_telegram_message(next(e for e in positions if e.event_type is T.POSITION_OPEN_CONFIRMED)))
        self.assertEqual(self.truth(), before)

    def test_ack_pipeline_never_creates_exposure_trade_or_realized_pnl(self):
        self.acknowledge()
        before = self.truth()
        model = self.publish_artifacts(self.retained())
        self.assertEqual([e.event_type for e in model.events], [T.ACTION_ACKNOWLEDGED])
        self.assertEqual(model.health.owned_base_quantity, D(0))
        self.assertEqual(model.trades, ())
        self.assertIsNone(model.performance.net_pnl_quote)
        self.assertIs(self.deliver(model.events[0]).status, Delivery.NOT_ALERTABLE)
        self.assertEqual(self.telegram_session.calls, [])
        self.assertEqual(self.truth(), before)

    def test_unknown_outcome_is_visible_without_ack_terminal_ownership_or_resend_advice(self):
        action = self.attempt()
        cp = self.store.get_checkpoint()
        uncertain = replace(cp.snapshot, state=State.UNCERTAIN, position_evidence=Evidence.LAST_KNOWN,
                            reason=Reason.ACTION_OUTCOME_UNKNOWN)
        self.store.record_observation(replace(action, phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=Reason.ACTION_OUTCOME_UNKNOWN),
            replace(cp, sequence=cp.sequence+1, snapshot=uncertain), expected_sequence=cp.sequence)
        before = self.truth()
        model = self.publish_artifacts(self.retained())
        self.assertEqual({e.event_type for e in model.events}, {T.ACTION_UNKNOWN_OUTCOME,T.RUNTIME_UNCERTAIN})
        self.assertEqual(model.overview.display_health.value, "CRITICAL")
        self.assertEqual(model.trades, ())
        alert = next(e for e in model.events if e.event_type is T.RUNTIME_UNCERTAIN)
        text = render_telegram_message(alert)
        self.assertIn("Operator review required", text)
        self.assertNotIn("retry order", text.lower())
        self.assertIsNone(alert.broker_order_id)
        unknown = next(e for e in model.events if e.event_type is T.ACTION_UNKNOWN_OUTCOME)
        self.assertIsNone(unknown.occurred_at_ms)
        self.assertIs(self.deliver(alert).status, Delivery.DELIVERED)
        self.assertEqual(self.truth(), before)

    def test_overwritten_history_does_not_fabricate_transitions_ack_or_occurrence(self):
        self.settle(self.acknowledge(), store_fixtures.fill())
        self.reopen()
        model = self.publish_artifacts(self.retained(SECOND_RUN))
        self.assertEqual({e.event_type for e in model.events}, {T.ACTION_TERMINAL_CONFIRMED,T.OWNED_EXECUTION_DISCOVERED})
        self.assertEqual(model.trades, ())
        self.assertTrue(model.trade_history_incomplete)
        self.assertTrue(all(e.occurred_at_ms != self.at for e in model.events))

    def test_high_precision_risk_book_events_json_dashboard_and_telegram(self):
        fee = "0.000012345678901234567890123456789"
        self.long_activation(fee=fee, currency="USDT", close="100",
            cfg=store_fixtures.risk_configuration(max_daily_loss_fraction=D("0.01")))
        row, _ = self.live("80")
        before = self.truth()
        model = self.publish_artifacts(self.retained())
        trip = next(e for e in model.events if e.event_type is T.RISK_TRIPPED)
        execution = next(e for e in model.events if e.event_type is T.OWNED_EXECUTION_DISCOVERED)
        self.assertEqual(dict(execution.details)["execution_fee"], D(fee))
        self.assertEqual(dict(trip.details)["risk_equity"], row.risk_equity)
        self.assertEqual(model.health.risk_equity, row.risk_equity)
        with localcontext() as context:
            context.prec = 200
            net = row.risk_equity-D(1000)
            self.assertEqual(model.performance.net_pnl_quote, net)
            self.assertEqual(model.performance.return_percent, net/10)
        self.assertEqual(performance_series(model), ((row.valued_at_ms, model.performance.return_percent),))
        self.assertIn(format_value(row.risk_equity), render_telegram_message(trip))
        self.assertIn(format_value(row.daily_pnl), render_telegram_message(trip))
        self.assertIn(('"risk_equity":"'+format_value(row.risk_equity)+'"').encode(), trip.to_json())
        self.assertEqual(event_from_json(trip.to_json()), trip)
        self.assertEqual(self.truth(), before)

    def test_unknown_null_vs_confirmed_zero_and_zero_return_across_artifacts(self):
        unknown = self.publish_artifacts(())
        self.assertIsNone(unknown.health.owned_base_quantity)
        self.assertIsNone(unknown.performance.risk_equity)
        self.assertEqual(format_value(unknown.health.owned_base_quantity), "Unavailable")
        self.activate()
        known = self.publish_artifacts(self.retained())
        self.assertEqual(known.health.owned_base_quantity, D(0))
        self.assertEqual(known.health.daily_pnl, D(0))
        self.assertEqual(known.performance.return_percent, D(0))
        self.assertEqual(performance_series(known), ())  # ACTIVATION is not an equity event.
        self.assertEqual(self.output.read_health(), known.health)

    def test_positive_snapshot_with_no_retained_equity_events_never_becomes_history(self):
        self.long_activation(close="100")
        row, _ = self.live("300")
        model = self.publish_artifacts(self.retained())
        self.assertEqual(row.risk_equity,D(1200))
        self.assertEqual(model.performance.net_pnl_quote,D(200))
        self.assertEqual(model.performance.return_percent,D(20))
        self.assertEqual(len(self.store.list_risk_valuations()),2)
        self.assertEqual(performance_series(model),())
        self.assertTrue(model.performance.history_incomplete)

    def test_trip_and_runtime_halt_are_independent_through_both_consumers(self):
        self.tripped_long()
        model = self.publish_artifacts(self.retained())
        self.assertEqual(model.health.runtime_state, State.LONG)
        trip = next(e for e in model.events if e.event_type is T.RISK_TRIPPED)
        self.assertNotIn("Runtime halted", render_telegram_message(trip))
        risk_before = self.store.list_risk_valuations(), self.store.list_risk_verdicts(), self.store.get_current_risk_epoch()
        self.halt()
        model = self.publish_artifacts(self.retained())
        self.assertEqual(model.health.runtime_state, State.HALTED)
        self.assertIsNotNone(model.health.risk_trip_reason)
        halt = next(e for e in model.events if e.event_type is T.RUNTIME_HALTED)
        self.assertIn("Runtime halted", render_telegram_message(halt))
        self.assertEqual((self.store.list_risk_valuations(),self.store.list_risk_verdicts(),self.store.get_current_risk_epoch()),risk_before)

    def test_risk_child_preserves_history_runtime_rearm_requires_reconciliation(self):
        self.tripped_long()
        parent_events = self.retained()
        self.publish_artifacts(parent_events)
        parent_rows = self.store.list_risk_valuations()
        self.rearm()
        child = self.store.get_current_risk_epoch()
        model = self.publish_artifacts(self.retained())
        self.assertEqual(self.store.list_risk_valuations()[:len(parent_rows)],parent_rows)
        self.assertEqual(sum(e.event_type is T.RISK_TRIPPED for e in model.events),1)
        self.assertEqual(len(performance_series(model)),1)
        risk_rearm = next(e for e in model.events if e.event_type is T.RISK_REARMED)
        self.assertIn("Book and capital allocation are unchanged",render_telegram_message(risk_rearm))
        self.halt()
        self.control_halt()
        before = self.truth()
        model = self.publish_artifacts(self.retained())
        runtime_rearm = next(e for e in model.events if e.event_type is T.RUNTIME_REARMED)
        self.assertIn("Reconciliation still required",render_telegram_message(runtime_rearm))
        self.assertEqual(model.health.runtime_state,State.SYNCHRONIZING)
        self.assertEqual(model.health.position_evidence,Evidence.LAST_KNOWN)
        self.assertEqual(model.health.risk_epoch_id,child.epoch_id)
        self.assertNotEqual(model.overview.display_health.value,"OK")
        self.assertEqual(self.truth(),before)

    def test_health_atomic_replace_is_complete_to_storage_and_dashboard_readers(self):
        self.activate()
        old, new = self.health(), self.health(self.at+1, SECOND_RUN)
        self.output.write_health(old)
        observed = []
        real_replace = sink.os.replace
        def observe_replace(*args,**kwargs):
            observed.append((self.output.read_health(),self.load().health))
            real_replace(*args,**kwargs)
            observed.append((self.output.read_health(),self.load().health))
        before = self.truth()
        with patch.object(sink.os,"replace",side_effect=observe_replace):
            self.output.write_health(new)
        self.assertEqual(observed,[(old,old),(new,new)])
        self.assertEqual(health_from_json((self.output.instance_directory/"health.json").read_bytes()),new)
        self.assertEqual(self.truth(),before)

    def test_new_snapshot_does_not_refresh_stale_underlying_evidence_and_viewer_ages(self):
        self.tripped_long()
        self.publish_artifacts(self.retained())
        model = self.load()
        self.assertEqual(model.health.generated_freshness,EvidenceFreshness.FRESH)
        for field in ("market_freshness","reconciliation_freshness","broker_freshness","risk_freshness"):
            self.assertEqual(getattr(model.health,field),EvidenceFreshness.STALE)
        raw = (self.output.instance_directory/"health.json").read_bytes()
        aged = self.load(now_ms=self.at+120001)
        self.assertEqual(aged.overview.snapshot_freshness,EvidenceFreshness.STALE)
        self.assertEqual(aged.health,model.health)
        self.assertEqual((self.output.instance_directory/"health.json").read_bytes(),raw)

    def test_torn_tail_preserves_prefix_in_both_readers_without_repair(self):
        self.acknowledge()
        events = self.retained()
        self.publish_artifacts(events)
        path = self.output.instance_directory/self.output.event_filename(self.at)
        with path.open("ab") as stream:
            stream.write(b'{"unfinished')
        raw = path.read_bytes()
        self.assertEqual(self.read_events().events,events)
        self.assertTrue(self.read_events().degraded)
        model = self.load()
        self.assertIn(DashboardNotice.TORN_TAIL,model.notices)
        self.assertEqual(model.events,events)
        self.assertEqual(model.trades,())
        self.assertEqual(path.read_bytes(),raw)

    def test_interior_corruption_disables_history_and_retains_valid_health(self):
        self.acknowledge()
        event, = self.retained()
        self.publish_artifacts((event,))
        path = self.output.instance_directory/self.output.event_filename(self.at)
        raw = event.to_json()+b'\n{"invalid":true}\n'+event.to_json()+b'\n'
        path.write_bytes(raw)
        with self.assertRaises(ObservabilityStorageError):
            self.read_events()
        model = self.load()
        self.assertIn(DashboardNotice.HISTORY_CORRUPT,model.notices)
        self.assertEqual(model.events,())
        self.assertEqual(model.health,self.output.read_health())
        self.assertEqual(path.read_bytes(),raw)

    def test_storage_failure_fallbacks_are_bounded_sanitized_and_non_authoritative(self):
        self.tripped_long()
        event = self.retained()[0]
        self.publish_artifacts((event,))
        before = self.truth()
        old_health = self.output.read_health()
        errors = io.StringIO()
        with patch.object(sink.os,"write",side_effect=OSError(errno.ENOSPC,TOKEN)) as write, patch.object(sink.sys,"stderr",errors):
            self.assertFalse(safe_append_event(self.output,event))
            self.assertFalse(safe_write_health(self.output,self.health(self.at+1)))
            self.assertEqual(write.call_count,2)
        self.assertEqual(errors.getvalue(),"Trading Lab observability: local output unavailable.\n"*2)
        self.assertEqual(self.output.read_health(),old_health)
        self.assertEqual(self.truth(),before)
        with patch.object(sink.os,"write",side_effect=OSError(errno.ENOSPC,TOKEN)), \
                patch.object(sink.sys.stderr,"write",side_effect=OSError(TOKEN)) as fallback:
            self.assertFalse(safe_append_event(self.output,event))
            self.assertEqual(fallback.call_count,1)
        self.assertEqual(self.truth(),before)

    def test_telegram_success_and_reprojection_receipt_dedupe_use_actual_trip(self):
        self.tripped_long()
        model = self.publish_artifacts(self.retained())
        trip = next(e for e in model.events if e.event_type is T.RISK_TRIPPED)
        before = self.truth()
        self.assertIs(self.deliver(trip).status,Delivery.DELIVERED)
        second = next(e for e in self.retained(SECOND_RUN,self.at+1) if e.event_type is T.RISK_TRIPPED)
        self.assertEqual(second.event_id,trip.event_id)
        self.assertIs(self.deliver(second).status,Delivery.ALREADY_DELIVERED)
        self.assertEqual(self.telegram_session.calls,[])
        self.assertIsNotNone(self.receipts.get_receipt(trip.event_id))
        self.assertEqual(self.truth(),before)

    def test_telegram_ambiguity_stops_once_then_only_explicit_notification_retry(self):
        self.tripped_long()
        trip = next(e for e in self.publish_artifacts(self.retained()).events if e.event_type is T.RISK_TRIPPED)
        before = self.truth()
        result = self.deliver(trip,requests.Timeout(TOKEN))
        self.assertIs(result.status,Delivery.AMBIGUOUS)
        self.assertEqual((result.attempt_count,len(self.telegram_session.calls)),(1,1))
        self.assertIsNone(self.receipts.get_receipt(trip.event_id))
        self.assertIs(self.deliver(trip).status,Delivery.DELIVERED)
        self.assertEqual(self.truth(),before)

    def test_remote_success_receipt_failure_no_same_call_resend_or_trading_change(self):
        self.tripped_long()
        trip = next(e for e in self.publish_artifacts(self.retained()).events if e.event_type is T.RISK_TRIPPED)
        before = self.truth()
        errors = io.StringIO()
        with patch.object(TelegramDeliveryStore,"record_delivery",side_effect=TelegramDeliveryStateError(TOKEN)), \
                patch.object(telegram.sys,"stderr",errors):
            result = self.deliver(trip)
        self.assertIs(result.status,Delivery.DELIVERED_UNRECORDED)
        self.assertEqual(len(self.telegram_session.calls),1)
        self.assertIsNone(self.receipts.get_receipt(trip.event_id))
        self.assertEqual(errors.getvalue().count("\n"),1)
        self.assertNotIn(TOKEN,errors.getvalue()+repr(result))
        self.assertIs(self.deliver(trip).status,Delivery.DELIVERED)
        (self.receipts.directory/(trip.event_id+".json")).unlink()
        self.assertIs(self.deliver(trip).status,Delivery.DELIVERED)
        self.assertEqual(self.truth(),before)

    def test_synthetic_secret_never_leaks_outside_fake_endpoint_and_destination(self):
        self.tripped_long()
        model = self.publish_artifacts(self.retained())
        trip = next(e for e in model.events if e.event_type is T.RISK_TRIPPED)
        transport = self.transport()
        result = deliver_telegram_event(trip,transport,self.receipts,utc_now_ms=lambda:self.at)
        self.assertEqual(self.telegram_session.calls[0][0],"https://api.telegram.org/bot"+TOKEN+"/sendMessage")
        self.assertEqual(self.telegram_session.calls[0][1]["json"]["chat_id"],CHAT)
        errors = io.StringIO()
        with patch.object(sink.os,"write",side_effect=OSError(errno.EIO,TOKEN)),patch.object(sink.sys,"stderr",errors):
            self.assertFalse(safe_append_event(self.output,trip))
            with self.assertRaises(ObservabilityStorageError) as caught:
                self.output.write_health(self.health())
        text = repr((model,transport,self.receipts,result))+str(caught.exception)+errors.getvalue()
        for path in self.root.rglob("*"):
            text += str(path)
            if path.is_file():
                text += path.read_text()
        for secret in (TOKEN,CHAT):
            self.assertNotIn(secret,text)

    def test_resource_bounds_cover_event_storage_dashboard_and_telegram(self):
        self.activate()
        events = tuple(process_started(self.config,run_id=f"{n:032x}",observed_at_ms=n*DAY,
                                      process_started_at_ms=0) for n in range(8))
        self.publish_artifacts(events)
        self.assertEqual(len(self.load().events),viewer.MAX_EVENT_FILES)
        model = self.load(limit=1)
        self.assertEqual(len(model.events),1)
        self.assertIn(DashboardNotice.HISTORY_LIMITED,model.notices)
        self.assertLessEqual(len(model.events),viewer.MAX_HISTORY_LIMIT)
        with self.assertRaises(ObservabilityValidationError):
            event_from_json(b" "*(event_model.MAX_EVENT_BYTES+1))
        for bounds in ({"max_records":0},{"max_records":event_model.MAX_RETAINED_RECORDS+1},
                       {"max_bytes":1},{"max_bytes":sink.MAX_READ_BYTES+1}):
            with self.subTest(bounds=bounds),self.assertRaises(ObservabilityStorageError):
                self.read_events(at=0,**bounds)
        self.output.append_event(events[0])
        with self.assertRaises(ObservabilityStorageError):
            self.read_events(at=0,max_records=1)
        with self.assertRaises(DashboardError):
            self.load(limit=viewer.MAX_HISTORY_LIMIT+1)
        with patch.object(viewer,"MAX_HISTORY_BYTES",1):
            self.assertIn(DashboardNotice.HISTORY_RESOURCE_LIMIT,self.load().notices)
        with patch.object(viewer,"MAX_EVENT_FILE_BYTES",1):
            self.assertIn(DashboardNotice.HISTORY_RESOURCE_LIMIT,self.load().notices)
        transport = self.transport()
        with self.assertRaises(TelegramError):
            deliver_telegram_events((events[0],)*(telegram.MAX_TELEGRAM_BATCH_EVENTS+1),transport,self.receipts)
        self.assertEqual(self.telegram_session.calls,[])
        self.assertIs(self.deliver(events[0]).status,Delivery.DELIVERED)
        receipt = self.receipts.directory/(events[0].event_id+".json")
        receipt.write_bytes(b" "*(telegram.MAX_TELEGRAM_RECEIPT_BYTES+1))
        transport = self.transport()
        with self.assertRaises(TelegramDeliveryStateError):
            deliver_telegram_event(events[0],transport,self.receipts)
        self.assertEqual(self.telegram_session.calls,[])

    def test_generic_identity_uses_same_real_artifacts_and_loader_without_new_strategy(self):
        self.activate()
        start = process_started(self.config,run_id=RUN,observed_at_ms=self.at,process_started_at_ms=0)
        original = self.publish_artifacts((start,))
        # Synthetic parser records only; never construct a non-v1 RuntimeConfiguration.
        from trading_lab.observability.model import canonical_bytes
        identity = dict(strategy_id="donchian",symbol="ETHUSDT",bot_id="bot2")
        future_start = process_started(replace(self.config,bot_id="bot2"),run_id=RUN,
                                       observed_at_ms=self.at,process_started_at_ms=0)
        event = event_from_json(canonical_bytes({**future_start.to_dict(),**identity}))
        values = {**original.health.to_dict(),**identity,"base_currency":"ETH"}
        configuration = {key:values[key] for key in ("risk_capital_quote","buy_quote_budget","max_entry_notional_quote",
            "max_position_notional_quote","max_daily_loss_fraction","max_drawdown_fraction","max_entries_per_utc_day",
            "base_currency","quote_currency")}
        configuration["risk_contract_version"] = 1
        values["risk_configuration_digest"] = hashlib.sha256(canonical_bytes(configuration)).hexdigest()
        health = health_from_json(canonical_bytes(values))
        output = ObservabilityStorage(self.root,replace(self.config,bot_id="bot2"))
        output.append_event(event)
        output.write_health(health)
        generic = load_dashboard(self.root,output.instance_name,now_ms=self.at)
        self.assertEqual(type(original),type(generic))
        self.assertEqual(original.views,generic.views)
        self.assertEqual(generic.views,DASHBOARD_VIEWS)
        self.assertEqual(generic.identity.strategy_id,"donchian")
        self.assertEqual(len(discover_instances(self.root).instances),2)


class GoldenArtifactIsolationTests(Consumers,golden_fixtures.IntegrationCase):
    def test_delete_entire_derived_tree_preserves_golden_and_next_logical_behavior(self):
        history,actions,fills,_ = self.golden()
        self.assertEqual((len(history),len(self.sends),len(fills),len(self.cancels),
                          self.store.get_current_risk_epoch().epoch_sequence),(54,2,2,0,1))
        self.at = self.clock.ms
        model = self.publish_artifacts(self.retained())
        start = process_started(self.config,run_id=RUN,observed_at_ms=self.at,process_started_at_ms=0)
        self.assertIs(self.deliver(start).status,Delivery.DELIVERED)
        self.assertEqual(model.views,DASHBOARD_VIEWS)
        self.assertEqual(model.trades,())  # Durable catch-up has no overwritten transitions.
        control = self.cycle()
        before = self.truth()
        shutil.rmtree(self.root)  # Only this test's derived tree, never its journal.
        self.assertEqual(self.truth(),before)
        self.assertFalse(self.root.exists())
        following = self.cycle()
        fields = ("outcome","processed_candle_open_ms","logical_action_id","new_execution_ids","risk_verdict")
        self.assertEqual(tuple(getattr(control,key) for key in fields),tuple(getattr(following,key) for key in fields))
        self.assertEqual(self.store.list_actions(),before[3])
        self.assertEqual(self.store.list_fills(),before[4])
        self.assertEqual(self.logical_history(),history)
        self.assertEqual((len(self.sends),len(self.cancels)),(2,0))


# SHA256 over sorted relative path + NUL + each file's SHA256 bytes.
# Captured at independently frozen 0c3b6a82; only observability/runtime package
# digests include the owner-approved integration correction. All other guards
# and the protected primitive/authority files remain unchanged.
FROZEN = {
    "src/trading_lab/observability":"f67eb3a80421d73ee04cfcc5dbff4f2692e3a570274d76ecd138cecdeab0fd62",
    "src/trading_lab/dashboard":"bdb8b1db4a3927b4cf0c13d7a5946df5f1b183b382e2bec356b2056b4316d38d",
    "dashboard/app.py":"7298145c0ccae620cdc4b1149917a47d7492af7a4bb3c8755cf0cd2a2ac368fe",
    ".streamlit/config.toml":"3a57bb7c48a19a0f2890e8f800bf3d7ab0e3a0cf3e1fb9e62ad70f0bffdbfcee",
    "src/trading_lab/runtime":"b137d1d21073777a4f4f5794ca4b3465cbce34f1de7316a9bbf789a65213b44b",
    "src/trading_lab/risk":"263fee1375d59b1222d4da9d5918cb2a512cb98f597c35f9585f2469fe2be007",
    "src/trading_lab/exchange":"0e6704369fc862848f49627c769ba6dc7d9a381b1e5a81164aaf67585928842a",
    "src/trading_lab/strategies":"94bf53f33446251fd969eb72013ab21cf206f939caf3baa37b0a16cc8ed754b9",
    "src/trading_lab/backtest":"4ce97250d710bcaec724767b1ca6d8af1edf2b9d753a8679c55743fe041f3caa",
    "decisions":"46c758ebeda9978365a9a3833b61cdd952d406db971dadcebd265e54df70d662",
    "requirements.txt":"c67f2c580b0a06d18d891a22538cd6ad66638d06e1b31191f40ca4da642528d2",
}


class FrozenBoundaryAuditTests(unittest.TestCase):
    def test_frozen_production_decisions_and_dependency_blobs(self):
        for name,expected in FROZEN.items():
            path = PROJECT/name
            files = sorted(path.rglob("*.py") if path.is_dir() and name!="decisions" else
                           path.glob("*.md") if path.is_dir() else (path,))
            digest = hashlib.sha256()
            for file in files:
                digest.update(file.relative_to(PROJECT).as_posix().encode()+b"\0"+hashlib.sha256(file.read_bytes()).digest())
            self.assertEqual(digest.hexdigest(),expected,name)

    def test_authority_modules_do_not_depend_on_observability_or_dashboard(self):
        roots = ("runtime","risk","exchange","strategies")
        for name in roots:
            for path in (PROJECT/"src/trading_lab"/name).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    imports = [alias.name for alias in node.names] if isinstance(node,ast.Import) else \
                        [node.module or "",*(alias.name for alias in node.names)] if isinstance(node,ast.ImportFrom) else ()
                    for module in imports:
                        self.assertFalse({"observability","dashboard","telegram"} & set(module.split(".")),path.name)
