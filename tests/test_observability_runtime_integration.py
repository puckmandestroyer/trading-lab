"""Automatic runtime wiring, authority isolation and offline sink failures.

Only temporary journals, public durable APIs and the existing synthetic runtime
fixtures are used. No real session, environment credential or network is used.
"""

import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal as D, localcontext
import inspect
import io
from pathlib import Path
import shutil
from threading import Event, current_thread, main_thread
import unittest
from unittest.mock import Mock, patch

import requests

from trading_lab.observability import runtime_integration as integration
from trading_lab.observability import ObservabilityEventType as T, ObservabilityStorageError
from trading_lab.observability.telegram import TelegramDeliveryStateError
from trading_lab.runtime import scheduler
from trading_lab.runtime.cycle import CycleOutcome, SingleCycleResult
from trading_lab.runtime.scheduler import SchedulerError
from trading_lab.runtime.state import RuntimeStateSnapshot, RuntimeState as State, PositionEvidence as Evidence
from trading_lab.runtime.store import RuntimeStore, ActionRecord, ActionPhase, JournalActionKind
from trading_lab.runtime.recovery import prepare_process_restart
from trading_lab.dashboard import performance_series, format_value
from tests import test_runtime_scheduler as clocks
from tests import test_runtime_store as journal
from tests import test_runtime_integration_regression as golden
from tests import test_observability_offline_regression as consumers
from tests import test_observability_telegram as http
from tests import test_runtime_risk_rearm as risk

RUN = "2"*32
SECOND_RUN = "3"*32
HOUR = journal.HOUR


class HookTests(clocks.SchedulerCase):
    def call(self, observer=None):
        with patch.object(scheduler, "run_single_cycle", side_effect=self.fake_cycle):
            return scheduler.run_hourly_scheduler(self.store,self.market,self.broker,self.adapter,self.stop,
                utc_now=self.clock.utc,monotonic=self.clock.monotonic,cycle_observer=observer)

    def test_hook_sees_validated_durable_result_after_cycle_transaction(self):
        observed = []
        def capture(result):
            self.assertFalse(self.active)
            self.assertFalse(self.store._connection.in_transaction)
            self.assertEqual(result.checkpoint,self.store.get_checkpoint())
            observed.append(result)
        result = self.call(capture)
        self.assertEqual(observed,[result.last_cycle])

    def test_no_callback_after_cycle_exception(self):
        original = RuntimeError("PRIVATE")
        self.effects = [Mock(side_effect=original)]
        observer = Mock()
        with self.assertRaises(RuntimeError) as caught:
            self.call(observer)
        self.assertIs(caught.exception,original)
        observer.assert_not_called()

    def test_no_callback_after_malformed_cycle_result(self):
        observer = Mock()
        self.effects = [lambda: object()]
        with self.assertRaises(SchedulerError):
            self.call(observer)
        observer.assert_not_called()

    def test_no_callback_after_durable_checkpoint_mismatch(self):
        observer = Mock()
        cp = self.store.get_checkpoint()
        self.effects = [lambda: SingleCycleResult(replace(cp,sequence=cp.sequence+1),CycleOutcome.NOOP)]
        with self.assertRaises(SchedulerError):
            self.call(observer)
        observer.assert_not_called()

    def test_return_value_cannot_stop_or_replace_result(self):
        observer = Mock(return_value=State.HALTED)
        result = self.call(observer)
        self.assertEqual(result.cycle_count,1)
        self.assertIs(result.exit_reason,scheduler.SchedulerExit.STOP_REQUESTED)
        self.assertIsNot(result.checkpoint.snapshot.state,State.HALTED)

    def test_one_fixed_fallback_per_failed_callback_no_exception_values(self):
        error = RuntimeError("PRIVATE_CREDENTIAL_VALUE")
        with patch.object(scheduler.sys,"stderr",new_callable=io.StringIO) as stderr:
            result = self.call(Mock(side_effect=error))
        self.assertEqual(result.cycle_count,1)
        self.assertEqual(stderr.getvalue(),"Runtime cycle observation failed.\n")

    def test_fallback_failure_is_also_isolated(self):
        with patch.object(scheduler.sys,"stderr",Mock(write=Mock(side_effect=OSError("PRIVATE")))):
            result = self.call(Mock(side_effect=ValueError("PRIVATE")))
        self.assertEqual((result.cycle_count,result.wake_count),(1,0))

    def test_observer_failure_preserves_scheduler_backoff_and_retry_counts(self):
        self.effects = [self.transient(),self.transient(),lambda:self.result()]
        self.stop.steps = [self.stop.elapsed_wait]*2
        with patch.object(scheduler.sys,"stderr",new_callable=io.StringIO):
            result = self.call(Mock(side_effect=RuntimeError("PRIVATE")))
        self.assertEqual((result.cycle_count,result.wake_count),(3,0))
        self.assertEqual(self.times,[12*HOUR+37*60000,12*HOUR+37*60000+1000,12*HOUR+37*60000+3000])
        self.assertEqual(self.stop.waits[:2],[1.0,2.0])


class AutomaticCase(consumers.Consumers,clocks.SchedulerCase):
    def observed(self, **changes):
        with patch.object(scheduler,"run_single_cycle",side_effect=self.fake_cycle):
            return integration.run_observed_hourly_scheduler(self.store,self.market,self.broker,self.adapter,self.stop,
                **{**dict(storage=self.output,utc_now=self.clock.utc,monotonic=self.clock.monotonic,
                    observability_now_ms=lambda:self.at,run_id=RUN),**changes})

    def events(self):
        return self.read_events(max_records=10000,max_bytes=16_000_000).events

    def assert_quiet_authority(self):
        self.assertEqual(self.market.mock_calls,[])
        self.assertEqual(self.broker.mock_calls,[])
        self.assertEqual(self.adapter.mock_calls,[])
        self.assertEqual(self.store.list_actions(),())
        self.assertEqual(self.store.list_fills(),())
        self.assertIsNone(self.store.get_current_risk_epoch())


class AutomaticWiringTests(AutomaticCase):
    def test_all_five_runtime_boundaries_are_automatic(self):
        self.acknowledge()
        transport = self.transport(http.Response(),http.Response())
        result = self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
        types = [event.event_type for event in self.events()]
        self.assertTrue({T.PROCESS_STARTED,T.SCHEDULER_STARTED,T.CYCLE_COMPLETED,T.ACTION_ACKNOWLEDGED,
            T.SCHEDULER_EXITED,T.PROCESS_STOPPED} <= set(types))
        self.assertEqual(types.count(T.CYCLE_COMPLETED),result.cycle_count)
        self.assertEqual(types.count(T.ACTION_ACKNOWLEDGED),1)
        self.assertEqual(self.output.read_health().checkpoint_sequence,result.checkpoint.sequence)
        self.assertEqual(len(self.telegram_session.calls),2)  # Lifecycle only; ACK is not a fill/alert.
        self.assertFalse({T.POSITION_OPEN_CONFIRMED,T.OWNED_EXECUTION_DISCOVERED} & set(types))
        self.assertEqual(self.load().trades,())

    def test_per_cycle_references_are_deterministic_and_noop_does_not_spam_telegram(self):
        self.stop.steps = [self.stop.elapsed_wait]*2
        transport = self.transport(http.Response(),http.Response())
        result = self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
        cycles = [e for e in self.events() if e.event_type is T.CYCLE_COMPLETED]
        self.assertEqual(len(cycles),3)
        from trading_lab.observability.projection import cycle_completed
        self.assertEqual([e.event_id for e in cycles],[cycle_completed(self.config,result.last_cycle,
            run_id=RUN,observed_at_ms=self.at,occurrence_reference=f"cycle-{n:06d}").event_id for n in range(1,4)])
        self.assertEqual(len(self.telegram_session.calls),2)

    def test_observability_uses_no_extra_scheduler_clock_reads(self):
        utc,mono = Mock(side_effect=self.clock.utc),Mock(side_effect=self.clock.monotonic)
        observer_clock = Mock(return_value=self.at)
        self.observed(utc_now=utc,monotonic=mono,observability_now_ms=observer_clock)
        observed_counts = (utc.call_count,mono.call_count,self.stop.waits[:])
        # Repeat low-level scenario on an independent identical durable journal.
        other = clocks.SchedulerCase()
        other.setUp()
        try:
            raw_utc,raw_mono = Mock(side_effect=other.clock.utc),Mock(side_effect=other.clock.monotonic)
            other.run_scheduler(utc_now=raw_utc,monotonic=raw_mono)
            self.assertEqual(observed_counts,(raw_utc.call_count,raw_mono.call_count,other.stop.waits))
        finally:
            other.doCleanups()
        self.assertEqual(observer_clock.call_count,3)

    def test_telegram_resources_must_be_a_matching_explicit_pair(self):
        transport = self.transport()
        before = self.truth()
        for changes in ({"telegram_transport":transport},{"telegram_receipts":self.receipts}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                self.observed(**changes)
        self.assertEqual(self.truth(),before)
        self.assertEqual(self.times,[])

    def test_default_run_id_is_created_once_and_cannot_change_durable_state(self):
        with patch.object(integration,"new_run_id",return_value=SECOND_RUN) as identifier:
            self.observed(run_id=None)
        identifier.assert_called_once_with()
        self.assertEqual({e.run_id for e in self.events()},{SECOND_RUN})
        self.assert_quiet_authority()

    def test_nonadjacent_checkpoint_is_a_gap_not_invented_open(self):
        def gap():
            self.flat()
            cp = self.store.get_checkpoint()
            self.store.save_checkpoint(replace(cp,sequence=cp.sequence+1),expected_sequence=cp.sequence)
            return self.result()
        self.effects = [gap]
        with patch.object(integration,"project_checkpoint_transition",wraps=integration.project_checkpoint_transition) as transition:
            self.observed()
        transition.assert_not_called()
        self.assertFalse(any(e.event_type is T.POSITION_OPEN_CONFIRMED for e in self.events()))

    def test_failed_capture_advances_boundary_and_next_capture_is_degraded(self):
        self.flat()
        def next_cp():
            cp = self.store.get_checkpoint()
            self.store.save_checkpoint(replace(cp,sequence=cp.sequence+1),expected_sequence=cp.sequence)
            return self.result()
        self.effects = [next_cp,next_cp]
        self.stop.steps = [self.stop.elapsed_wait]
        real = integration.project_checkpoint_transition
        calls = []
        def project(cfg,before,after,**kwargs):
            calls.append((before.sequence,after.sequence))
            if len(calls) == 1:
                raise ValueError("PRIVATE")
            return real(cfg,before,after,**kwargs)
        with patch.object(integration,"project_checkpoint_transition",side_effect=project), patch.object(integration.sys,"stderr",new_callable=io.StringIO):
            result = self.observed()
        self.assertEqual(calls,[(1,2),(2,3)])
        self.assertEqual(result.cycle_count,2)
        self.assertEqual(self.output.read_health().observability_status,"DEGRADED")

    def test_normal_halted_return_retains_halt_and_health_is_not_ok(self):
        self.state(State.HALTED)
        result = self.observed()
        self.assertIs(result.exit_reason,scheduler.SchedulerExit.HALTED)
        health = self.output.read_health()
        self.assertIs(health.runtime_state,State.HALTED)
        self.assertNotEqual(health.overall_health.value,"OK")
        self.assertIn(T.RUNTIME_HALTED,[e.event_type for e in self.events()])
        self.assertIn(T.PROCESS_STOPPED,[e.event_type for e in self.events()])

    def test_unknown_outcome_remains_uncertain_and_ack_is_not_a_fill(self):
        self.state(State.UNCERTAIN)
        before = (self.store.list_actions(),self.store.list_fills())
        self.observed()
        types = {e.event_type for e in self.events()}
        self.assertIn(T.ACTION_UNKNOWN_OUTCOME,types)
        self.assertIn(T.RUNTIME_UNCERTAIN,types)
        self.assertFalse({T.POSITION_OPEN_CONFIRMED,T.OWNED_EXECUTION_DISCOVERED} & types)
        self.assertEqual((self.store.list_actions(),self.store.list_fills()),before)

    def test_durable_catchup_is_deduped_within_run(self):
        self.settle(self.acknowledge(),journal.fill())
        self.stop.steps = [self.stop.elapsed_wait]*2
        self.observed()
        durable = [e.event_id for e in self.events() if e.source == "DURABLE"]
        self.assertEqual(len(durable),len(set(durable)))
        self.assertEqual(sum(e.event_type is T.OWNED_EXECUTION_DISCOVERED for e in self.events()),1)

    def test_per_run_durable_cache_is_bounded_by_existing_limit(self):
        self.settle(self.acknowledge(),journal.fill())
        sessions = []
        original = integration._RuntimeObservationSession
        def session(*args):
            obj = original(*args)
            sessions.append(obj)
            return obj
        with patch.object(integration,"MAX_RETAINED_RECORDS",1),patch.object(integration,"_RuntimeObservationSession",side_effect=session):
            self.observed()
        self.assertLessEqual(len(sessions[0].seen),1)
        self.assertEqual(sessions[0].queue.maxsize,64)

    def test_batch_is_immutable_and_contains_only_frozen_observations(self):
        self.assertEqual([f.name for f in fields(integration._ObservationBatch)],["events","health"])
        batch = integration._ObservationBatch((),None)
        with self.assertRaises(FrozenInstanceError):
            batch.events = ()
        self.assertFalse(hasattr(batch,"__dict__"))

    def test_restart_stable_durable_ids_distinct_process_ids_dashboard_and_receipt_dedupe(self):
        self.state(State.HALTED)
        transport = self.transport(*[http.Response() for _ in range(5)])
        self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
        first = self.events()
        self.reopen()
        prepare_process_restart(self.store)
        self.stop = clocks.FakeStop(self.clock)
        self.observed(run_id=SECOND_RUN,telegram_transport=transport,telegram_receipts=self.receipts)
        second = [e for e in self.events() if e.run_id == SECOND_RUN]
        self.assertEqual([e.event_id for e in first if e.source == "DURABLE"],
                         [e.event_id for e in second if e.source == "DURABLE"])
        self.assertFalse({e.event_id for e in first if e.source == "PROCESS"} &
                         {e.event_id for e in second if e.source == "PROCESS"})
        self.assertEqual(sum(e.event_type is T.RUNTIME_HALTED for e in self.events()),2)
        self.assertEqual(sum(e.event_type is T.RUNTIME_HALTED for e in self.load().events),1)
        self.assertEqual(len(self.telegram_session.calls),5)  # HALT receipt suppresses second notification.
        self.assert_quiet_authority()

    def test_partial_entry_growth_partial_exit_and_zero_are_automatic_adjacent_transitions(self):
        action = [self.acknowledge()]
        def observe(quantity,index,*,terminal=False):
            before = self.store.get_checkpoint()
            buy = action[0].side == "BUY"
            at = (HOUR if buy else 2*HOUR)+10*index
            fill = replace(journal.fill("partial-"+str(index)),action_id=action[0].logical_action_id,
                broker_order_id=action[0].broker_order_id,order_link_id=action[0].order_link_id,side=action[0].side,
                executed_quantity=D(quantity),execution_price=D(100),execution_fee=D(0),fee_currency=None,
                executed_at_ms=at,observed_at_ms=at)
            owned = {1:D("0.02"),2:D("0.05"),3:D("0.03"),4:D(0)}[index]
            state = State.LONG if terminal and owned else State.FLAT if terminal else State.ORDER_PENDING
            snapshot = RuntimeStateSnapshot(state,owned,Evidence.CONFIRMED,int(buy),
                                            None if terminal else before.snapshot.pending_action)
            observed = replace(action[0],phase=ActionPhase.TERMINAL_CONFIRMED if terminal else action[0].phase,
                order_status="FILLED" if terminal else "PARTIALLY_FILLED",external_status="Filled" if terminal else "PartiallyFilled",
                observed_at_ms=at,terminal_at_ms=at if terminal else None)
            cp = replace(before,sequence=before.sequence+1,snapshot=snapshot,last_reconciled_at_ms=at,observed_at_ms=at)
            self.store.record_observation(observed,cp,expected_sequence=before.sequence,fills=(fill,))
            action[0] = observed
            return replace(self.result(),new_execution_ids=(fill.broker_execution_id,))
        def prepare_exit():
            before = self.store.get_checkpoint()
            exit_id = "f"*64
            exit_action = ActionRecord(exit_id,JournalActionKind.EXIT,self.config.symbol,2*HOUR+600000,5,3,
                "bot1-"+exit_id[:23],HOUR,side="SELL",amount_unit="BASE",currency="BTC",authorized_amount=D("0.05"))
            from trading_lab.runtime.state import PendingAction, PendingActionKind
            pending = RuntimeStateSnapshot(State.ORDER_PENDING,D("0.05"),Evidence.CONFIRMED,0,
                                          PendingAction(exit_id,PendingActionKind.EXIT))
            cp = replace(before,sequence=before.sequence+1,snapshot=pending,last_processed_candle_ms=HOUR)
            decision = replace(journal.decision(HOUR,action=True),signal="LONG_EXIT",desired_position=0,action_id=exit_id)
            self.store.commit_decision(journal.candle(HOUR),decision,cp,expected_sequence=before.sequence,action=exit_action)
            before = self.store.get_checkpoint()
            self.store.start_attempt(exit_id,replace(before,sequence=before.sequence+1),expected_sequence=before.sequence)
            before = self.store.get_checkpoint()
            action[0] = replace(self.store.get_action(exit_id),phase=ActionPhase.ACKNOWLEDGED,broker_order_id="order-2",
                submitted_amount=D("0.05"),acknowledgement_broker_ms=2*HOUR+1,acknowledgement_observed_ms=2*HOUR+2)
            self.store.record_observation(action[0],replace(before,sequence=before.sequence+1),expected_sequence=before.sequence)
            return self.result()
        self.effects = [lambda:observe("0.02",1),lambda:observe("0.03",2,terminal=True),prepare_exit,
                        lambda:observe("0.02",3),lambda:observe("0.03",4,terminal=True)]
        self.stop.steps = [self.stop.elapsed_wait]*4
        transport = self.transport(*[http.Response() for _ in range(4)])
        self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
        positions = [e for e in self.events() if e.event_type in
                     (T.POSITION_OPEN_CONFIRMED,T.POSITION_QUANTITY_CHANGED,T.POSITION_CLOSE_CONFIRMED)]
        self.assertEqual([e.event_type for e in positions],[T.POSITION_OPEN_CONFIRMED,T.POSITION_QUANTITY_CHANGED,
                                                         T.POSITION_QUANTITY_CHANGED,T.POSITION_CLOSE_CONFIRMED])
        self.assertEqual([dict(e.details)["owned_base_quantity"] for e in positions],[D("0.02"),D("0.05"),D("0.03"),D(0)])
        self.assertEqual(len(self.telegram_session.calls),4)  # START, OPEN, CLOSE, STOP; no quantity spam.
        model = self.load()
        self.assertEqual(len(model.trades),1)
        self.assertEqual(len(model.trades[0].executions),4)
        self.assertIsNone(model.trades[0].realized_pnl_quote)


class FailureIsolationTests(AutomaticCase):
    def assert_failed_sink_keeps_trading(self, **kwargs):
        result = self.observed(**kwargs)
        self.assertEqual((result.cycle_count,result.wake_count),(1,0))
        self.assertEqual(self.stop.waits,[23*60.0])
        self.assertIs(result.exit_reason,scheduler.SchedulerExit.STOP_REQUESTED)
        self.assert_quiet_authority()
        return result

    def test_jsonl_failure_does_not_suppress_health_or_telegram(self):
        transport = self.transport(http.Response(),http.Response())
        with patch.object(type(self.output),"append_event",side_effect=ObservabilityStorageError("PRIVATE")),patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        self.assertIsNotNone(self.output.read_health())
        self.assertEqual(len(self.telegram_session.calls),2)

    def test_health_failure_does_not_suppress_events_or_telegram(self):
        transport = self.transport(http.Response(),http.Response())
        with patch.object(type(self.output),"write_health",side_effect=ObservabilityStorageError("PRIVATE")) as writer,patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        self.assertEqual(writer.call_count,3)
        self.assertIn(T.CYCLE_COMPLETED,[e.event_type for e in self.events()])
        self.assertEqual(len(self.telegram_session.calls),2)

    def test_storage_failure_latches_future_capture_degraded(self):
        known = Event()
        original = integration.safe_append_event
        def append(storage,event):
            if event.event_type is T.PROCESS_STARTED:
                known.set()
                return False
            return original(storage,event)
        def cycle():
            self.assertTrue(known.wait(2))  # Test synchronization only, never production observer waiting.
            return self.result()
        self.effects = [cycle]
        with patch.object(integration,"safe_append_event",side_effect=append):
            self.assert_failed_sink_keeps_trading()
        self.assertEqual(self.output.read_health().observability_status,"DEGRADED")

    def test_telegram_timeout_is_ambiguous_once_per_event_without_receipt_or_resend(self):
        transport = self.transport(requests.Timeout("PRIVATE"),http.Response())
        with patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        start = next(e for e in self.events() if e.event_type is T.PROCESS_STARTED)
        self.assertIsNone(self.receipts.get_receipt(start.event_id))
        self.assertEqual(len(self.telegram_session.calls),2)  # One ambiguous START, one distinct STOP.

    def test_telegram_429_backoff_is_worker_only(self):
        self._retry_failure(429)

    def test_telegram_5xx_backoff_is_worker_only(self):
        self._retry_failure(503)

    def _retry_failure(self, status):
        transport = self.transport(*[http.Response(status) for _ in range(3)],http.Response())
        sleeps = []
        # Transport sleeper is an explicit dependency; no real sleep or scheduler time advances.
        with patch.object(transport,"_sleeper",side_effect=lambda delay:sleeps.append((delay,current_thread().name))),patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        self.assertEqual([x[0] for x in sleeps],[1,2])
        self.assertTrue(all(name == "trading-lab-observability" for _,name in sleeps))
        self.assertEqual(len(self.telegram_session.calls),4)

    def test_remote_success_receipt_loss_never_resends_same_event(self):
        transport = self.transport(http.Response(),http.Response())
        with patch.object(type(self.receipts),"record_delivery",side_effect=TelegramDeliveryStateError("PRIVATE")),patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        self.assertEqual(len(self.telegram_session.calls),2)
        self.assertTrue(all(self.receipts.get_receipt(e.event_id) is None for e in self.events()))

    def test_blocked_telegram_queue_overflow_and_drain_timeout_do_not_block_cycles(self):
        entered,release = Event(),Event()
        transport = self.transport(http.Response(),http.Response())
        real_post = self.telegram_session.post
        def post(*args,**kwargs):
            entered.set()
            release.wait(5)
            return real_post(*args,**kwargs)
        self.stop.steps = [self.stop.elapsed_wait]*4
        def first_cycle():
            self.assertTrue(entered.wait(2))
            return self.result()
        self.effects = [first_cycle]
        workers = []
        real_worker = integration._sink_worker
        def worker(*args):
            workers.append(current_thread())
            real_worker(*args)
        try:
            with patch.object(self.telegram_session,"post",side_effect=post),patch.object(integration,"QUEUE_CAPACITY",1),\
                 patch.object(integration,"DRAIN_TIMEOUT_SECONDS",0.01),patch.object(integration,"_sink_worker",side_effect=worker),\
                 patch("sys.stderr",new_callable=io.StringIO) as stderr:
                result = self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
                self.assertTrue(workers[0].is_alive())
                self.assertEqual(result.cycle_count,5)
                self.assertEqual(self.times,[12*HOUR+37*60000,13*HOUR,14*HOUR,15*HOUR,16*HOUR])
                self.assertIn("Runtime observability degraded.",stderr.getvalue())
                self.assertNotIn("PRIVATE",stderr.getvalue())
                self.assert_quiet_authority()
        finally:
            release.set()
            for worker in workers:
                worker.join(3)
                self.assertFalse(worker.is_alive())

    def test_telegram_failure_latch_is_visible_to_later_health(self):
        known = Event()
        transport = self.transport(http.Response(401),http.Response())
        real = integration.deliver_telegram_event
        def deliver(*args,**kwargs):
            result = real(*args,**kwargs)
            return result
        def cycle():
            self.assertTrue(known.wait(2))
            return self.result()
        real_degrade = integration._degrade
        def degrade(flag):
            real_degrade(flag)
            known.set()
        self.effects = [cycle]
        with patch.object(integration,"deliver_telegram_event",side_effect=deliver),patch.object(integration,"_degrade",side_effect=degrade),\
             patch("sys.stderr",new_callable=io.StringIO):
            self.assert_failed_sink_keeps_trading(telegram_transport=transport,telegram_receipts=self.receipts)
        self.assertEqual(self.output.read_health().observability_status,"DEGRADED")

    def test_scheduler_exception_uses_cached_context_and_never_reads_store_afterward(self):
        original = RuntimeError("PRIVATE_SECRET_EXCEPTION")
        failed,after_reads = Event(),[]
        originals = {name:getattr(RuntimeStore,name) for name in dir(RuntimeStore)
                     if name.startswith(("get_","list_")) and callable(getattr(RuntimeStore,name))}
        def guard(name,method):
            def call(store,*args,**kwargs):
                if failed.is_set():
                    after_reads.append(name)
                    raise AssertionError("Store read after scheduler failure")
                return method(store,*args,**kwargs)
            return call
        def fail():
            failed.set()
            raise original
        self.effects = [fail]
        with ExitStack() as stack:
            for name,method in originals.items():
                stack.enter_context(patch.object(RuntimeStore,name,guard(name,method)))
            with self.assertRaises(RuntimeError) as caught:
                self.observed()
        self.assertIs(caught.exception,original)
        self.assertEqual(after_reads,[])
        events = self.events()
        self.assertEqual(sum(e.event_type is T.CRITICAL_FAILURE for e in events),1)
        self.assertFalse({T.SCHEDULER_EXITED,T.PROCESS_STOPPED,T.CYCLE_COMPLETED} & {e.event_type for e in events})
        self.assertNotIn("PRIVATE_SECRET",b"".join(e.to_json() for e in events).decode())
        self.assert_quiet_authority()

    def test_failed_critical_capture_and_failed_stderr_preserve_original_exception(self):
        original = RuntimeError("PRIVATE")
        self.effects = [Mock(side_effect=original)]
        with patch.object(integration,"critical_failure",side_effect=ValueError("PRIVATE")),\
             patch("sys.stderr",Mock(write=Mock(side_effect=OSError("PRIVATE")))):
            with self.assertRaises(RuntimeError) as caught:
                self.observed()
        self.assertIs(caught.exception,original)


class ThreadBoundaryTests(AutomaticCase):
    def test_store_and_sink_calls_are_on_opposite_threads_and_worker_has_no_authority(self):
        violations,sink_threads = [],[]
        with ExitStack() as stack:
            for name in dir(RuntimeStore):
                method = getattr(RuntimeStore,name)
                if name.startswith(("get_","list_","save_","commit_","record_")) and callable(method):
                    def call(store,*args,_method=method,_name=name,**kwargs):
                        if current_thread() is not main_thread():
                            violations.append(_name)
                        return _method(store,*args,**kwargs)
                    stack.enter_context(patch.object(RuntimeStore,name,call))
            for name in ("append_event","write_health"):
                method = getattr(type(self.output),name)
                def sink(storage,*args,_method=method,**kwargs):
                    sink_threads.append(current_thread())
                    return _method(storage,*args,**kwargs)
                stack.enter_context(patch.object(type(self.output),name,sink))
            self.observed()
            self.assertEqual(len(set(sink_threads)),1)
            sink_threads.clear()
            # Exercise real strategy/planner/risk and broker methods, not only
            # no-op mocks. Every guarded authority call must remain main-thread.
            other = ObservedGoldenCase()
            other.setUp()
            from trading_lab.runtime import cycle as cycle_module
            from trading_lab.runtime import store as store_module
            from trading_lab.risk import runtime_risk as policy
            calls = []
            def authority(method,name):
                def call(*args,**kwargs):
                    calls.append(name)
                    if current_thread() is not main_thread():
                        violations.append(name)
                    return method(*args,**kwargs)
                return call
            try:
                for owner,name in ((cycle_module,"generate_ema_signals"),(cycle_module,"plan_action"),
                                   (policy,"evaluate_risk"),(store_module,"evaluate_risk")):
                    stack.enter_context(patch.object(owner,name,authority(getattr(owner,name),name)))
                for owner in (type(other.broker),type(other.adapter),type(other.market)):
                    for name in dir(owner):
                        method = getattr(owner,name)
                        if callable(method) and not name.startswith("_"):
                            stack.enter_context(patch.object(owner,name,authority(method,name)))
                other.golden()
            finally:
                other.doCleanups()
            expected = {"generate_ema_signals","plan_action","evaluate_risk","place_market_order","get_account_state"}
            self.assertTrue(expected <= set(calls),expected-set(calls))
        self.assertEqual(violations,[])
        self.assertTrue(sink_threads)
        self.assertEqual(len(set(sink_threads)),2)  # Golden includes a second process invocation.
        self.assertTrue(all(t.daemon and t is not main_thread() for t in sink_threads))
        self.assert_quiet_authority()
        self.assertEqual(integration._sink_worker.__closure__,None)
        tree = ast.parse(inspect.getsource(integration._sink_worker))
        names = {node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        self.assertFalse(names & {"store","broker","market_reader","order_adapter","strategy","planner","risk"})


class ExactRiskPipelineTests(consumers.Consumers,risk.LocalRearmCase):
    def observed(self, **changes):
        clock = clocks.FakeClock(self.at)
        stop = clocks.FakeStop(clock)
        quiet = Mock(spec=[])
        with patch.object(scheduler,"run_single_cycle",side_effect=lambda *a,**kw:SingleCycleResult(self.store.get_checkpoint(),CycleOutcome.NOOP)):
            return integration.run_observed_hourly_scheduler(self.store,quiet,quiet,quiet,stop,
                storage=self.output,utc_now=clock.utc,monotonic=clock.monotonic,
                observability_now_ms=lambda:self.at,run_id=RUN,**changes)

    def test_high_precision_automatic_risk_json_health_telegram_and_dashboard(self):
        fee = "0.000012345678901234567890123456789"
        self.long_activation(fee=fee,currency="USDT",close="100",
            cfg=journal.risk_configuration(max_daily_loss_fraction=D("0.01")))
        row,_ = self.live("80")
        truth = self.truth()
        transport = self.transport(http.Response(),http.Response(),http.Response())
        self.observed(telegram_transport=transport,telegram_receipts=self.receipts)
        events = self.read_events().events
        trip = next(e for e in events if e.event_type is T.RISK_TRIPPED)
        execution = next(e for e in events if e.event_type is T.OWNED_EXECUTION_DISCOVERED)
        self.assertEqual(dict(execution.details)["execution_fee"],D(fee))
        self.assertEqual(dict(trip.details)["risk_equity"],row.risk_equity)
        model = self.load()
        self.assertEqual(model.health.risk_equity,row.risk_equity)
        with localcontext() as context:
            context.prec = 200
            self.assertEqual(model.performance.net_pnl_quote,row.risk_equity-D(1000))
            self.assertEqual(model.performance.return_percent,(row.risk_equity-D(1000))/10)
        self.assertEqual(performance_series(model),((row.valued_at_ms,model.performance.return_percent),))
        text = "\n".join(call[1]["json"]["text"] for call in self.telegram_session.calls)
        self.assertIn(format_value(row.risk_equity),text)
        self.assertIn(('"risk_equity":"'+format_value(row.risk_equity)+'"').encode(),trip.to_json())
        self.assertEqual(self.truth()[2:],truth[2:])  # Only scheduler's normal STOPPING checkpoint changed.

    def test_current_return_is_not_fabricated_into_historical_graph(self):
        self.activate(close="100")
        self.live("120")
        self.observed()
        model = self.load()
        self.assertIsNotNone(model.performance.return_percent)
        self.assertEqual(performance_series(model),())
        self.assertFalse(any(e.event_type.value == "PERFORMANCE_SNAPSHOT" for e in model.events))


class ObservedGoldenCase(consumers.Consumers,golden.IntegrationCase):
    def scheduler(self,events=()):
        self.stop = golden.Stop(self,events)
        self.at = self.clock.ms
        with patch.object(scheduler,"run_single_cycle",side_effect=self.activated_cycle):
            result = integration.run_observed_hourly_scheduler(self.store,self.market,self.broker,self.adapter,self.stop,
                storage=self.output,utc_now=self.clock.now,monotonic=lambda:self.clock.elapsed,
                observability_now_ms=lambda:self.clock.ms,run_id=RUN if not getattr(self,"invocations",0) else SECOND_RUN,
                **getattr(self,"observation_options",{}))
        self.invocations = getattr(self,"invocations",0)+1
        self.scheduler_results = getattr(self,"scheduler_results",[])+[(result,self.stop.waits[:])]
        self.at = self.clock.ms
        self.capture()
        return result


class ObservedGoldenTests(ObservedGoldenCase):
    def test_automatic_golden_preserves_exact_ids_economics_and_restart(self):
        history,actions,fills,_ = self.golden()
        self.assertEqual((len(history),len(self.sends),len(fills),len(self.cancels),
                          self.store.get_current_risk_epoch().epoch_sequence),(54,2,2,0,1))
        model = self.load()
        self.assertEqual([e.event_type for e in model.events].count(T.CYCLE_COMPLETED),6)
        self.assertEqual(len([e for e in model.events if e.event_type is T.OWNED_EXECUTION_DISCOVERED]),2)
        self.assertEqual(model.trades,())  # Whole cycles skip versions: transitions stay honest gaps.
        self.assertEqual(self.output.read_health().risk_equity,self.store.get_latest_risk_valuation().risk_equity)

    def test_deleting_automatic_artifacts_cannot_change_next_logical_behavior(self):
        self.golden()
        truth = self.truth()
        control = self.cycle()
        shutil.rmtree(self.root)
        self.assertEqual(self.truth(),truth)
        following = self.cycle()
        self.assertEqual(control,following)
        self.assertEqual((len(self.sends),len(self.cancels)),(2,0))

    def test_sink_failures_preserve_complete_golden_trading_truth_and_timing(self):
        expected_golden = self.golden()
        expected = (expected_golden,self.store.get_checkpoint(),self.store.list_risk_valuations(),
                    self.store.list_risk_verdicts(),self.sends,self.cancels,self.trace,self.scheduler_results)
        for failure in ("jsonl","health","timeout","429","503","receipt","queue-drain"):
            with self.subTest(failure=failure):
                other = ObservedGoldenCase()
                other.setUp()
                release,workers = Event(),[]
                try:
                    with ExitStack() as stack:
                        stack.enter_context(patch("sys.stderr",new_callable=io.StringIO))
                        if failure in ("jsonl","health"):
                            name = "append_event" if failure == "jsonl" else "write_health"
                            stack.enter_context(patch.object(type(other.output),name,side_effect=ObservabilityStorageError("PRIVATE")))
                        elif failure == "queue-drain":
                            real_worker = integration._sink_worker
                            def blocked_worker(*args):
                                workers.append(current_thread())
                                release.wait()  # Test-only block; always released in finally.
                                real_worker(*args)
                            stack.enter_context(patch.object(integration,"_sink_worker",side_effect=blocked_worker))
                            stack.enter_context(patch.object(integration,"QUEUE_CAPACITY",1))
                            stack.enter_context(patch.object(integration,"DRAIN_TIMEOUT_SECONDS",0.01))
                        else:
                            if failure == "timeout":
                                responses = [requests.Timeout("PRIVATE") for _ in range(10)]
                            elif failure in ("429","503"):
                                responses = [http.Response(int(failure)) for _ in range(20)]
                            else:
                                responses = [http.Response() for _ in range(10)]
                            transport = other.transport(*responses)
                            stack.enter_context(patch.object(transport,"_sleeper",side_effect=lambda _:None))
                            other.observation_options = dict(telegram_transport=transport,telegram_receipts=other.receipts)
                            if failure == "receipt":
                                stack.enter_context(patch.object(type(other.receipts),"record_delivery",side_effect=TelegramDeliveryStateError("PRIVATE")))
                        actual_golden = other.golden()
                        if failure == "queue-drain":
                            self.assertEqual(len(workers),2)
                            self.assertTrue(all(worker.is_alive() for worker in workers))
                    self.assertEqual((actual_golden,other.store.get_checkpoint(),other.store.list_risk_valuations(),
                        other.store.list_risk_verdicts(),other.sends,other.cancels,other.trace,other.scheduler_results),expected)
                finally:
                    release.set()
                    for worker in workers:
                        worker.join(3)
                        self.assertFalse(worker.is_alive())
                    other.doCleanups()


class ObserverEconomicEquivalenceTests(golden.IntegrationCase):
    def test_raising_observer_matches_unobserved_golden_trading_truth_exactly(self):
        # Both fixtures use the full real offline cycle and exact golden assertions.
        baseline = self.golden()
        expected = (baseline,self.store.get_checkpoint(),self.store.list_risk_valuations(),
                    self.store.list_risk_verdicts(),self.sends,self.cancels,self.trace)
        other = golden.IntegrationCase()
        other.setUp()
        raw = golden.run_hourly_scheduler
        def observed(*args,**kwargs):
            return raw(*args,**kwargs,cycle_observer=Mock(side_effect=RuntimeError("PRIVATE")))
        try:
            with patch.object(golden,"run_hourly_scheduler",side_effect=observed),patch("sys.stderr",new_callable=io.StringIO):
                actual = other.golden()
            self.assertEqual((actual,other.store.get_checkpoint(),other.store.list_risk_valuations(),
                other.store.list_risk_verdicts(),other.sends,other.cancels,other.trace),expected)
        finally:
            other.doCleanups()
