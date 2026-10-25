"""Explicit accepted commits, generic compatibility and real offline lifecycle.

No manufactured execution history or source of trading authority is introduced.
Pure projector examples complement actual temporary journal/broker scenarios.
"""

import ast
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal as D
import inspect
import io
from threading import Event
import unittest
from unittest.mock import Mock, patch

import requests

from trading_lab.observability import ObservabilityProjectionError, ObservabilityEventType as T
from trading_lab.observability import projection as projector, runtime_integration as integration
from trading_lab.runtime import reconciliation, cycle, scheduler
from trading_lab.runtime.state import RuntimeState as S, PositionEvidence as P, RuntimeStateSnapshot
from trading_lab.runtime.store import RuntimeCheckpoint, RuntimeStore, RuntimeStoreError
from tests import test_runtime_store as journal
from tests import test_observability_projection as projections
from tests import test_runtime_reconciliation as rounds
from tests import test_runtime_integration_regression as golden
from tests import test_observability_runtime_integration as observed
from tests import test_observability_telegram as http

RUN = "4"*32
POSITION_TYPES = {T.POSITION_OPEN_CONFIRMED,T.POSITION_CLOSE_CONFIRMED,T.POSITION_QUANTITY_CHANGED}


def last_known(quantity, *, sequence=1, at=10):
    return RuntimeCheckpoint(sequence,RuntimeStateSnapshot(S.SYNCHRONIZING,D(quantity),P.LAST_KNOWN,int(bool(D(quantity)))),
                             last_reconciled_at_ms=at,observed_at_ms=at)


class AcceptedProjectorTests(unittest.TestCase):
    def project(self,before,after,**changes):
        return projector.project_checkpoint_transition(journal.configuration(),before,after,
            **{**dict(run_id=RUN,observed_at_ms=100,contributing_execution_ids=("exec-1",),accepted_reconciliation=True),**changes})

    def test_same_timestamp_last_known_zero_to_positive_opens(self):
        before,after = last_known(0),projections.confirmed("0.04995",2)
        events = self.project(before,after)
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED,T.POSITION_OPEN_CONFIRMED])
        self.assertEqual([e.occurred_at_ms for e in events],[10,10])
        self.assertEqual(dict(events[1].details)["contributing_execution_ids"],("exec-1",))

    def test_same_timestamp_positive_to_exact_zero_closes(self):
        events = self.project(last_known("0.04995"),projections.confirmed(0,2))
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED,T.POSITION_CLOSE_CONFIRMED])
        self.assertEqual(dict(events[-1].details)["owned_base_quantity"],D(0))

    def test_positive_to_positive_changes_quantity_without_rounding_dust(self):
        tiny = "0.00000000000000000000000000000000001"
        events = self.project(last_known(1),projections.confirmed(tiny,2))
        self.assertIs(events[-1].event_type,T.POSITION_QUANTITY_CHANGED)
        self.assertEqual(dict(events[-1].details)["owned_base_quantity"],D(tiny))

    def test_same_positive_quantity_restores_certainty_without_position_event(self):
        events = self.project(last_known("0.05"),projections.confirmed("0.05",2))
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED])

    def test_same_zero_restores_certainty_without_position_event(self):
        events = self.project(last_known(0),projections.confirmed(0,2))
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED])

    def test_unknown_to_positive_is_current_confirmation_not_historical_open(self):
        before = RuntimeCheckpoint(1,RuntimeStateSnapshot())
        events = self.project(before,projections.confirmed(1,2))
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED])

    def test_missing_execution_evidence_never_relaxes_last_known_position(self):
        for old,new in ((0,1),(1,0),(1,2)):
            with self.subTest(old=old,new=new):
                events = self.project(last_known(old),projections.confirmed(new,2),contributing_execution_ids=())
                self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED])

    def test_generic_last_known_mode_is_unchanged_even_with_new_execution_ids(self):
        parameter=inspect.signature(projector.project_checkpoint_transition).parameters["accepted_reconciliation"]
        self.assertIs(parameter.kind,inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default,False)
        for time in (10,11):
            with self.subTest(time=time):
                events = self.project(last_known(0),projections.confirmed(1,2,reconciled=time),accepted_reconciliation=False)
                self.assertFalse(POSITION_TYPES & {e.event_type for e in events})
                self.assertEqual(len(events),int(time!=10))

    def test_generic_confirmed_mode_still_requires_timestamp_change(self):
        before = projections.confirmed(0,1)
        self.assertEqual(self.project(before,projections.confirmed(1,2),accepted_reconciliation=False),())
        events = self.project(before,projections.confirmed(1,2,reconciled=11),accepted_reconciliation=False)
        self.assertIs(events[-1].event_type,T.POSITION_OPEN_CONFIRMED)

    def test_accepted_boundary_rejects_gap_equal_sequence_or_regressed_time(self):
        before = last_known(0)
        for after in (projections.confirmed(1,1),projections.confirmed(1,3),projections.confirmed(1,2,reconciled=9)):
            with self.subTest(after=after),self.assertRaises(ObservabilityProjectionError):
                self.project(before,after)

    def test_accepted_boundary_requires_confirmed_quantity_and_matching_observation_time(self):
        before = last_known(0)
        valid = projections.confirmed(1,2)
        for after in (last_known(1,sequence=2),RuntimeCheckpoint(2,RuntimeStateSnapshot()),
                      replace(valid,last_reconciled_at_ms=None),replace(valid,observed_at_ms=None),
                      replace(valid,observed_at_ms=11)):
            with self.subTest(after=after),self.assertRaises(ObservabilityProjectionError):
                self.project(before,after)

    def test_accepted_mode_and_execution_ids_are_explicit_bounded_unique_safe_values(self):
        for flag in (None,1,0,"True"):
            with self.subTest(flag=flag),self.assertRaises(ObservabilityProjectionError):
                self.project(last_known(0),projections.confirmed(1,2),accepted_reconciliation=flag)
        bad = (None,[],["exec-1"],("",),("exec-1","exec-1"),("PRIVATE secret",),tuple("e"+str(n) for n in range(257)))
        for ids in bad:
            with self.subTest(ids=ids),self.assertRaises(ObservabilityProjectionError):
                self.project(last_known(0),projections.confirmed(1,2),contributing_execution_ids=ids)

    def test_accepted_transition_identity_ignores_run_and_observation_clock(self):
        before,after = last_known(0),projections.confirmed(1,2)
        first = self.project(before,after)
        later = self.project(before,after,run_id="5"*32,observed_at_ms=200)
        self.assertEqual([e.event_id for e in first],[e.event_id for e in later])
        self.assertEqual(dict(first[-1].details),dict(later[-1].details))


class ReconciliationCase(journal.StoreCase):
    known = rounds.ReconciliationTests.known
    cancel_control = rounds.ReconciliationTests.cancel_control
    sell = rounds.ReconciliationTests.sell

    def setUp(self):
        super().setUp()
        self.broker = rounds.FakeReadOnlyBroker(self.store)
        self.now_ms = rounds.NOW_MS
        for target in ("requests.Session.send","socket.create_connection","socket.socket.connect","os.getenv"):
            self.enterContext(patch(target,side_effect=AssertionError("Offline only")))

    def round(self,observer=None):
        return reconciliation.reconcile_startup(self.store,self.broker,utc_now=lambda:rounds.utc(self.now_ms),
                                                monotonic=lambda:1.0,reconciliation_observer=observer)

    def filled(self):
        self.known(rounds.OrderStatus.FILLED,"0.05")
        self.broker.executions = (rounds.execution(),)


class ReconciliationCallbackTests(ReconciliationCase):
    def callback(self,records):
        def capture(before,after,ids):
            self.assertFalse(self.store._connection.in_transaction)
            self.assertEqual(after,self.store.get_checkpoint())
            self.assertEqual(after.sequence,before.sequence+1)
            self.assertIs(after.snapshot.position_evidence,P.CONFIRMED)
            records.append((before,after,ids))
        return capture

    def test_no_placement_callback_runs_only_after_reconciled_commit(self):
        records=[]
        result=self.round(self.callback(records))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0][1],result.checkpoint)
        self.assertEqual(records[0][2],())
        self.assertEqual(len(self.broker.calls),3)

    def test_placement_callback_receives_only_newly_committed_execution_ids(self):
        self.filled()
        records=[]
        result=self.round(self.callback(records))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0][2],("exec-1",))
        self.assertEqual(records[0][1],result.checkpoint)
        self.assertIs(records[0][0].snapshot.position_evidence,P.LAST_KNOWN)
        self.round(self.callback(records))
        self.assertEqual(records[-1][2],())

    def test_cancellation_intermediate_is_not_observed_and_final_pair_is_adjacent(self):
        self.known()
        self.cancel_control()
        self.broker.order=rounds.order(rounds.OrderStatus.FILLED,quantity="0.05")
        self.broker.executions=(rounds.execution(),)
        records=[]
        result=self.round(self.callback(records))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0][1],result.checkpoint)
        self.assertEqual(records[0][0].sequence,result.checkpoint.sequence-1)
        self.assertIs(result.cancellation.phase,journal.ActionPhase.TERMINAL_CONFIRMED)

    def test_failed_reconciled_save_does_not_invoke_observer(self):
        observer=Mock()
        original=self.store.save_checkpoint
        def fail(cp,**kwargs):
            if cp.snapshot.position_evidence is P.CONFIRMED:
                raise RuntimeStoreError("PRIVATE")
            return original(cp,**kwargs)
        with patch.object(self.store,"save_checkpoint",side_effect=fail),self.assertRaises(RuntimeStoreError):
            self.round(observer)
        observer.assert_not_called()

    def test_failed_reconciled_observation_does_not_invoke_observer(self):
        self.filled()
        observer=Mock()
        original=self.store.record_observation
        def fail(action,cp,**kwargs):
            if cp.snapshot.position_evidence is P.CONFIRMED:
                raise RuntimeStoreError("PRIVATE")
            return original(action,cp,**kwargs)
        with patch.object(self.store,"record_observation",side_effect=fail),self.assertRaises(RuntimeStoreError):
            self.round(observer)
        observer.assert_not_called()

    def test_lost_return_after_real_commit_does_not_invoke_observer(self):
        for placement in (False,True):
            # Separate real stores; never repair an indeterminate commit.
            other=ReconciliationCase(); other.setUp()
            try:
                if placement: other.filled()
                name="record_observation" if placement else "save_checkpoint"
                original=getattr(other.store,name)
                def lost(*args,**kwargs):
                    result=original(*args,**kwargs)
                    cp=args[1] if placement else args[0]
                    if cp.snapshot.position_evidence is P.CONFIRMED:
                        raise RuntimeStoreError("PRIVATE lost return")
                    return result
                observer=Mock()
                with patch.object(other.store,name,side_effect=lost),self.assertRaises(RuntimeStoreError):
                    other.round(observer)
                observer.assert_not_called()
            finally: other.doCleanups()

    def test_callback_return_value_is_ignored(self):
        result=self.round(Mock(return_value=S.HALTED))
        self.assertIs(result.checkpoint.snapshot.state,S.FLAT)

    def test_callback_adds_no_control_clock_store_or_broker_reads(self):
        results=[]
        for observer in (None,Mock(side_effect=RuntimeError("PRIVATE"))):
            other=ReconciliationCase(); other.setUp()
            try:
                other.filled()
                utc,monotonic=Mock(return_value=rounds.utc()),Mock(return_value=1.0)
                with ExitStack() as stack:
                    reads={name:stack.enter_context(patch.object(other.store,name,wraps=getattr(other.store,name)))
                           for name in ("get_configuration","get_checkpoint","list_actions","list_fills","get_action")}
                    stack.enter_context(patch("sys.stderr",new_callable=io.StringIO))
                    result=reconciliation.reconcile_startup(other.store,other.broker,utc_now=utc,monotonic=monotonic,
                                                             reconciliation_observer=observer)
                    results.append((result,utc.call_count,monotonic.call_count,
                                    {name:read.call_count for name,read in reads.items()},other.broker.calls))
            finally: other.doCleanups()
        self.assertEqual(results[0],results[1])

    def test_callback_exception_and_stderr_failure_leave_accepted_result_unchanged(self):
        observer=Mock(side_effect=RuntimeError("PRIVATE_TOKEN"))
        with patch("sys.stderr",new_callable=io.StringIO) as stderr:
            result=self.round(observer)
        self.assertIs(result.checkpoint.snapshot.state,S.FLAT)
        self.assertEqual(stderr.getvalue(),"Runtime reconciliation observation failed.\n")
        with patch("sys.stderr",Mock(write=Mock(side_effect=OSError("PRIVATE")))):
            self.assertIs(self.round(observer).checkpoint.snapshot.state,S.FLAT)

    def test_fatal_or_uncertain_evidence_never_announces_successful_reconciliation(self):
        for error in (rounds.BrokerReadError(rounds.BrokerReadFailureKind.TRANSIENT),RuntimeError("PRIVATE")):
            other=ReconciliationCase(); other.setUp()
            try:
                other.broker.errors["get_account_state"]=error
                observer=Mock()
                result=other.round(observer)
                self.assertIn(result.checkpoint.snapshot.state,(S.UNCERTAIN,S.HALTED))
                observer.assert_not_called()
            finally: other.doCleanups()


class SessionBoundaryTests(unittest.TestCase):
    def session(self):
        session=object.__new__(integration._RuntimeObservationSession)
        session.configuration=journal.configuration()
        session.run_id=RUN
        session.now_ms=lambda:100
        session.started_at_ms=0
        session.degraded=Event()
        session.store=Mock(spec=RuntimeStore)
        session._health=Mock(side_effect=AssertionError("No health at reconciliation boundary"))
        session._enqueue=Mock()
        return session

    def test_reconciliation_capture_uses_only_arguments_and_existing_enqueue(self):
        session=self.session()
        before,after=last_known(0),projections.confirmed(1,2)
        session.observe_reconciliation(before,after,("exec-1",))
        session.store.assert_not_called()
        self.assertEqual(session.store.mock_calls,[])
        session._health.assert_not_called()
        self.assertEqual(session.last_observed_checkpoint,after)
        events,=session._enqueue.call_args.args
        self.assertIs(type(events),tuple)
        self.assertEqual([e.event_type for e in events],[T.RECONCILIATION_CONFIRMED,T.POSITION_OPEN_CONFIRMED])

    def test_failed_reconciliation_capture_latches_degradation_and_advances_frontier(self):
        session=self.session()
        after=projections.confirmed(1,2)
        with patch.object(integration,"project_checkpoint_transition",side_effect=ValueError("PRIVATE")),patch("sys.stderr",new_callable=io.StringIO):
            session.observe_reconciliation(last_known(0),after,("exec-1",))
        self.assertTrue(session.degraded.is_set())
        self.assertEqual(session.last_observed_checkpoint,after)
        session._enqueue.assert_not_called()

    def test_authority_imports_and_send_boundary_are_unchanged_except_generic_plumbing(self):
        for module in (reconciliation,cycle,scheduler):
            function=getattr(module,{reconciliation:"reconcile_startup",cycle:"run_single_cycle",scheduler:"run_hourly_scheduler"}[module])
            parameter=inspect.signature(function).parameters["reconciliation_observer"]
            self.assertIs(parameter.kind,inspect.Parameter.KEYWORD_ONLY)
            self.assertIsNone(parameter.default)
            tree=ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse({"observability","telegram","dashboard"} & set((node.module or "").split(".")))
        tree=ast.parse(inspect.getsource(cycle))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        start=next(n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=="start_attempt")
        place=next(n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=="place_market_order")
        forbidden={"cycle_observer","reconciliation_observer","project_checkpoint_transition","observability","telegram"}
        between=[n for n in ast.walk(tree) if hasattr(n,"lineno") and start.lineno<=n.lineno<=place.lineno]
        self.assertFalse({n.id for n in between if isinstance(n,ast.Name)} & forbidden)
        callback=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=="before_submit")
        after_start=[n for n in ast.walk(callback) if isinstance(n,ast.Call) and n.lineno>start.lineno]
        self.assertEqual(after_start,[])
        wrapper=ast.parse(inspect.getsource(integration))
        opted_in=[n for n in ast.walk(wrapper) if isinstance(n,ast.Call)
                  and any(k.arg=="accepted_reconciliation" and isinstance(k.value,ast.Constant)
                          and k.value.value is True for k in n.keywords)]
        self.assertEqual(len(opted_in),1)
        handler=next(n for n in ast.walk(wrapper) if isinstance(n,ast.FunctionDef) and n.name=="observe_reconciliation")
        self.assertIn(opted_in[0],list(ast.walk(handler)))


class CallbackGoldenEquivalenceTests(golden.IntegrationCase):
    def test_raising_reconciliation_observer_preserves_all_golden_authority_results(self):
        raw=golden.run_hourly_scheduler
        baseline_results=[]
        cycles,reconciliations=[],[]
        raw_cycle,raw_reconciliation=golden.run_single_cycle,cycle.reconcile_startup
        def capture_cycle(*args,**kwargs):
            result=raw_cycle(*args,**kwargs)
            cycles.append(result)
            return result
        def capture_reconciliation(*args,**kwargs):
            result=raw_reconciliation(*args,**kwargs)
            reconciliations.append(result)
            return result
        def control(*args,**kwargs):
            result=raw(*args,**kwargs)
            baseline_results.append(result)
            return result
        with patch.object(golden,"run_hourly_scheduler",side_effect=control),\
             patch.object(golden,"run_single_cycle",side_effect=capture_cycle),\
             patch.object(cycle,"reconcile_startup",side_effect=capture_reconciliation):
            expected=self.golden()
        expected_cycles,expected_reconciliations=cycles[:],reconciliations[:]
        cycles.clear(); reconciliations.clear()
        facts=(expected,self.store.get_checkpoint(),self.store.list_risk_valuations(),
               self.store.list_risk_verdicts(),self.sends,self.cancels,self.trace)
        other=golden.IntegrationCase(); other.setUp()
        results=[]
        observer=Mock(side_effect=RuntimeError("PRIVATE_TOKEN"))
        def raising(*args,**kwargs):
            result=raw(*args,**kwargs,reconciliation_observer=observer)
            results.append(result)
            return result
        try:
            with patch.object(golden,"run_hourly_scheduler",side_effect=raising),\
                 patch.object(golden,"run_single_cycle",side_effect=capture_cycle),\
                 patch.object(cycle,"reconcile_startup",side_effect=capture_reconciliation),\
                 patch("sys.stderr",new_callable=io.StringIO) as stderr:
                actual=other.golden()
            self.assertEqual((actual,other.store.get_checkpoint(),other.store.list_risk_valuations(),
                other.store.list_risk_verdicts(),other.sends,other.cancels,other.trace),facts)
            self.assertEqual(results,baseline_results)
            self.assertEqual(cycles,expected_cycles)
            self.assertEqual(reconciliations,expected_reconciliations)
            self.assertEqual(stderr.getvalue(),"Runtime reconciliation observation failed.\n"*observer.call_count)
            self.assertEqual(observer.call_count,8)
        finally: other.doCleanups()


class RealObservedLifecycleTests(observed.ObservedGoldenCase):
    def test_real_partial_buy_growth_partial_sell_and_zero_have_no_duplicate_boundaries(self):
        self.status="PartiallyFilled"
        def grow():
            order_id=next(key for key,value in self.remote_orders.items() if value["side"]=="Buy")
            self.add_execution(order_id,D("0.03"),"exec-buy-2",status="Filled")
        def close():
            order_id=next(key for key,value in self.remote_orders.items() if value["side"]=="Sell")
            self.add_execution(order_id,D("0.02990"),"exec-sell-2",status="Filled")
        result=self.scheduler([self.wake("110"),self.wake("110",before=grow),self.wake("60"),self.wake("60",before=close)])
        model=self.load()
        positions=[e for e in model.events if e.event_type in POSITION_TYPES]
        positions.sort(key=lambda e:e.checkpoint_sequence)
        self.assertEqual([e.event_type for e in positions],[T.POSITION_OPEN_CONFIRMED,T.POSITION_QUANTITY_CHANGED,
                                                         T.POSITION_QUANTITY_CHANGED,T.POSITION_CLOSE_CONFIRMED])
        self.assertEqual([dict(e.details)["owned_base_quantity"] for e in positions],
                         [D("0.01995"),D("0.04990"),D("0.02990"),D(0)])
        self.assertEqual((len(self.sends),len(self.store.list_fills()),len(self.cancels)),(2,4,0))
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity,D(0))
        self.assertEqual(len(model.trades),1)
        self.assertEqual(len(model.trades[0].executions),4)

    def test_real_ack_and_unknown_outcome_do_not_fabricate_position_lifecycle(self):
        for mode in ("normal","ambiguous_missing"):
            other=observed.ObservedGoldenCase(); other.setUp()
            try:
                other.status,other.send_mode="New",mode
                other.scheduler([other.wake("110")])
                model=other.load()
                self.assertFalse(POSITION_TYPES & {e.event_type for e in model.events})
                self.assertEqual(model.trades,())
                self.assertEqual(other.store.list_fills(),())
                self.assertEqual((len(other.sends),len(other.cancels)),(1,0))
                expected=T.ACTION_ACKNOWLEDGED if mode=="normal" else T.ACTION_UNKNOWN_OUTCOME
                self.assertIn(expected,{e.event_type for e in model.events})
            finally: other.doCleanups()

    def test_restart_after_missed_transition_does_not_invent_historical_open(self):
        self.enter()  # Real unobserved BUY; no observability transition was captured.
        self.assertEqual(len(self.sends),1)
        self.reopen()
        self.scheduler()
        model=self.load()
        self.assertEqual(model.health.owned_base_quantity,D("0.04995"))
        self.assertEqual(sum(e.event_type is T.OWNED_EXECUTION_DISCOVERED for e in model.events),1)
        self.assertFalse(POSITION_TYPES & {e.event_type for e in model.events})
        self.assertEqual(model.trades,())
        self.assertEqual(len(self.sends),1)

    def test_open_close_telegram_failures_preserve_exact_golden_trading_truth(self):
        expected_golden=self.golden()
        expected=(expected_golden,self.store.get_checkpoint(),self.store.list_risk_valuations(),
                  self.store.list_risk_verdicts(),self.sends,self.cancels,self.trace,self.scheduler_results)
        for failure in ("timeout","429","503","receipt"):
            with self.subTest(failure=failure):
                other=observed.ObservedGoldenCase(); other.setUp()
                try:
                    transport=other.transport()
                    other.observation_options=dict(telegram_transport=transport,telegram_receipts=other.receipts)
                    original_post=other.telegram_session.post
                    original_deliver=integration.deliver_telegram_event
                    original_receipt=type(other.receipts).record_delivery
                    current_event=[None]
                    outcomes=[]
                    def deliver(event,*args,**kwargs):
                        current_event[0]=event
                        result=original_deliver(event,*args,**kwargs)
                        outcomes.append((event,result))
                        return result
                    def post(*args,**kwargs):
                        text=kwargs["json"]["text"]
                        targeted="Confirmed position opened" in text or "Confirmed position closed" in text
                        reply=(requests.Timeout("PRIVATE") if failure=="timeout" else http.Response(int(failure))) \
                            if targeted and failure in ("timeout","429","503") else http.Response()
                        other.telegram_session.responses.insert(0,reply)
                        return original_post(*args,**kwargs)
                    def record(receipts,event_id,**kwargs):
                        if failure=="receipt" and current_event[0].event_type in POSITION_TYPES:
                            raise observed.TelegramDeliveryStateError("PRIVATE")
                        return original_receipt(receipts,event_id,**kwargs)
                    sleeps=[]
                    with patch.object(other.telegram_session,"post",side_effect=post),\
                         patch.object(integration,"deliver_telegram_event",side_effect=deliver),\
                         patch.object(type(other.receipts),"record_delivery",record),\
                         patch.object(transport,"_sleeper",side_effect=sleeps.append),patch("sys.stderr",new_callable=io.StringIO):
                        actual=other.golden()
                    self.assertEqual((actual,other.store.get_checkpoint(),other.store.list_risk_valuations(),
                        other.store.list_risk_verdicts(),other.sends,other.cancels,other.trace,other.scheduler_results),expected)
                    position_results=[(e,r) for e,r in outcomes if e.event_type in POSITION_TYPES]
                    self.assertEqual([e.event_type for e,r in position_results].count(T.POSITION_OPEN_CONFIRMED),1)
                    self.assertEqual([e.event_type for e,r in position_results].count(T.POSITION_CLOSE_CONFIRMED),1)
                    expected_status={"timeout":"AMBIGUOUS","429":"TRANSIENT_FAILURE","503":"TRANSIENT_FAILURE",
                                     "receipt":"DELIVERED_UNRECORDED"}[failure]
                    self.assertEqual([r.status.value for e,r in position_results],[expected_status]*2)
                    self.assertTrue(all(other.receipts.get_receipt(e.event_id) is None for e,r in position_results))
                    self.assertEqual([r.attempt_count for e,r in position_results],[3 if failure in ("429","503") else 1]*2)
                    self.assertEqual(sleeps,[1,2,1,2] if failure in ("429","503") else [])
                finally: other.doCleanups()
