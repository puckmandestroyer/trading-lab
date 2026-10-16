"""Stage 11.7: long offline paths through the frozen runtime and real adapters.

Only external transport evidence and explicitly labelled crash/corruption seams
are synthetic. Every ordinary decision runs the real EMA/planner/gate/store/
cycle/reconciler. SQLite files and account locks belong to temporary fixtures.
"""

import ast
from collections import Counter
from dataclasses import replace
from decimal import Decimal as D, localcontext
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from trading_lab.risk.runtime_risk import RiskActionKind, RiskBook, RiskReason, RiskVerdict
import trading_lab.runtime.cycle as cycle_module
import trading_lab.runtime.reconciliation as reconciliation_module
import trading_lab.runtime.recovery as recovery_module
import trading_lab.runtime.scheduler as scheduler_module
from trading_lab.runtime.cycle import CycleOutcome, run_single_cycle
from trading_lab.runtime.locking import RuntimeAccountLock
from trading_lab.runtime.scheduler import SchedulerExit, run_hourly_scheduler
from trading_lab.runtime.state import PositionEvidence, RuntimeReason, RuntimeState
from trading_lab.runtime.store import (
    ActionPhase, DecisionDisposition, JournalActionKind, OwnedFillRecord,
    RiskValuationMode, RuntimeStore, RuntimeStoreConflictError, RuntimeStoreError,
)
from tests import test_runtime_integration_regression as fixtures
from tests.test_runtime_store import risk_configuration

HOUR, DAY = 3_600_000, 86_400_000


class ProcessDeath(BaseException):
    """A test-only process stop, outside the cycle's broker-error handlers."""


class RiskE2ECase(fixtures.IntegrationCase):
    def setUp(self):
        super().setUp()
        self.simple_economics = True
        self.buy_fee, self.sell_fee = D(0), D(0)
        self.results, self.boundaries, self.evidence = [], [], []
        self.cycle_calls, self.scheduled, self.restarts = [], [], []
        self.adapter_invocations = []
        self.crash_at_adapter_entry = False
        self.operator_calls = []
        self.operator_active = False
        # Observe the actual public controls on every reopened store. Any call
        # outside an explicit operator test step is a regression, not a mock rearm.
        for name in ("rearm_runtime_halt", "rearm_risk_epoch"):
            original = getattr(RuntimeStore, name)

            def guarded(store, *, _name=name, _original=original, **kwargs):
                self.assertTrue(self.operator_active, "Automatic operator control: " + _name)
                self.operator_calls.append((_name, dict(kwargs)))
                return _original(store, **kwargs)

            self.enterContext(patch.object(RuntimeStore, name, guarded))
        adapter_type = type(self.adapter)
        original_placement = adapter_type.place_market_order

        def placement(adapter, request, **kwargs):
            self.adapter_invocations.append(request.order_link_id)
            self.assertEqual(self.adapter_invocations.count(request.order_link_id), 1)
            self.assertFalse(self.store._connection.in_transaction)
            cp = self.store.get_checkpoint()
            action = self.store.get_action(cp.snapshot.pending_action.logical_action_id)
            verdict = self.store.get_risk_verdict(action.candle_open_ms)
            self.assertEqual((action.phase, verdict.verdict, verdict.action_id),
                             (ActionPhase.PREPARED, RiskVerdict.ALLOW, action.logical_action_id))
            self.boundaries.append(("adapter", action.logical_action_id, action.phase, action.attempt_count))
            if self.crash_at_adapter_entry:
                raise ProcessDeath()
            return original_placement(adapter, request, **kwargs)

        self.enterContext(patch.object(adapter_type, "place_market_order", placement))
        for module in (cycle_module, reconciliation_module, recovery_module, scheduler_module):
            tree = ast.parse(Path(module.__file__).read_text())
            calls = {node.func.attr for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
            self.assertFalse(calls & {"rearm_runtime_halt", "rearm_risk_epoch"})
        forbidden = {"pause_risk", "manual_trip", "kill_switch", "force_flat", "liquidate",
                     "cancel_all", "clear_trip", "edit_risk_config", "stop_loss", "take_profit", "trailing_stop"}
        self.assertFalse(set(vars(RuntimeStore)) & forbidden)

    def add_execution(self, order_id, quantity, execution_id, *, status="Filled", fee=None):
        # Extend only the fake broker's evidence: later round trips need unique
        # execution IDs. The first golden BUY/SELL retain their original IDs.
        if any(row["execId"] == execution_id for row in self.remote_fills):
            execution_id += "-" + str(len(self.remote_fills) + 1)
        if self.simple_economics and fee is None:
            fee = self.buy_fee if self.remote_orders[order_id]["side"] == "Buy" else self.sell_fee
        super().add_execution(order_id, quantity, execution_id, status=status, fee=fee)
        if self.simple_economics:
            # Explicit synthetic $100 fills make inclusive breaker boundaries
            # finite exact Decimals. Parsing, accounting and policy stay real.
            self.remote_fills[-1]["execPrice"] = "100"
            rows = [row for row in self.remote_fills if row["orderId"] == order_id]
            with localcontext() as context:
                context.prec = 80
                base = sum((D(row["execQty"]) for row in rows), D(0))
                quote = sum((D(row["execQty"]) * D(row["execPrice"]) for row in rows), D(0))
                self.remote_orders[order_id].update(cumExecValue=str(quote), avgPrice=str(quote / base))

    def external(self, name, params):
        super().external(name, params)
        if name in ("metadata", "place"):
            cp = self.store.get_checkpoint()
            action = self.store.get_action(cp.snapshot.pending_action.logical_action_id)
            verdict = self.store.get_risk_verdict(action.candle_open_ms)
            valuation = next(row for row in self.store.list_risk_valuations(verdict.epoch_id)
                             if row.candle_open_ms == action.candle_open_ms)
            self.assertEqual((verdict.verdict, verdict.action_id, valuation.mode),
                             (RiskVerdict.ALLOW, action.logical_action_id, RiskValuationMode.LIVE))
            self.assertEqual((action.phase, action.attempt_count),
                             (ActionPhase.PREPARED, 0) if name == "metadata" else (ActionPhase.ATTEMPT_STARTED, 1))
            self.boundaries.append((name, action.logical_action_id, action.phase, action.attempt_count))

    def rows(self, store=None):
        store = store or self.store
        names = [row[0] for row in store._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: tuple(tuple(row) for row in store._connection.execute(
            "SELECT * FROM " + name + " ORDER BY rowid")) for name in names}

    def verify(self, label):
        """Audit authorization cardinality and independently reopened truth."""
        cp = self.store.get_checkpoint()
        actions, fills = self.store.list_actions(), self.store.list_fills()
        valuations, verdicts = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        history = self.logical_history() if cp.last_processed_candle_ms is not None else ()
        decisions = {decision.candle_open_ms: decision for _, decision in history}
        self.assertEqual(len(decisions), len(history))
        live = {row.candle_open_ms: row for row in valuations if row.mode is RiskValuationMode.LIVE}
        by_candle = {row.candle_open_ms: row for row in verdicts}
        self.assertEqual(len(live), sum(row.mode is RiskValuationMode.LIVE for row in valuations))
        self.assertEqual(len(by_candle), len(verdicts))
        self.assertEqual(set(live), set(by_candle))
        by_action = {action.logical_action_id: action for action in actions}
        for at, valuation in live.items():
            verdict, decision = by_candle[at], decisions[at]
            self.assertEqual((verdict.epoch_id, verdict.valued_at_ms, verdict.action_id),
                             (valuation.epoch_id, valuation.valued_at_ms, decision.action_id))
            if verdict.proposal_kind is not None and verdict.verdict is RiskVerdict.ALLOW:
                action = by_action[verdict.action_id]
                self.assertEqual((action.kind.value, action.authorized_amount, action.candle_open_ms),
                                 (verdict.proposal_kind.value, verdict.authorized_amount, at))
            else:
                self.assertIsNone(verdict.action_id)
                self.assertFalse(any(action.candle_open_ms == at for action in actions))
        for action in actions:
            self.assertIsNot(action.kind, JournalActionKind.CANCEL)
            self.assertLessEqual(action.attempt_count, 1)
            verdict = by_candle[action.candle_open_ms]
            self.assertEqual((verdict.verdict, verdict.action_id), (RiskVerdict.ALLOW, action.logical_action_id))
        for row in valuations:
            consumed = sum(v.verdict is RiskVerdict.ALLOW and v.proposal_kind is RiskActionKind.ENTRY
                           and v.evaluated_at_ms // DAY * DAY == row.utc_day_start_ms
                           and v.valued_at_ms <= row.valued_at_ms for v in verdicts)
            self.assertEqual(row.entries_this_utc_day, consumed)
        self.assertEqual(len({fill.broker_execution_id for fill in fills}), len(fills))
        for record, names in [(action, ("authorized_amount", "submitted_amount")) for action in actions] + [
            (fill, ("executed_quantity", "execution_price", "execution_fee")) for fill in fills] + [
            (row, ("virtual_quote_cash", "owned_base_quantity", "risk_equity", "mark_price")) for row in valuations]:
            for name in names:
                value = getattr(record, name)
                if value is not None:
                    self.assertIs(type(value), D)
        for send in self.sends:
            matching = [action for action in actions if action.order_link_id == send["orderLinkId"]]
            self.assertEqual(len(matching), 1)
            action = matching[0]
            self.assertIn(("place", action.logical_action_id, ActionPhase.ATTEMPT_STARTED, 1), self.boundaries)
            self.assertLessEqual(D(send["qty"]), action.authorized_amount)
        self.assertTrue(all(count == 1 for count in Counter(send["orderLinkId"] for send in self.sends).values()))
        self.assertTrue(all(count == 1 for count in Counter(self.adapter_invocations).values()))
        for link in self.adapter_invocations:
            self.assertEqual(sum(action.order_link_id == link for action in actions), 1)
        self.assertEqual(self.cancels, [])
        durable = self.rows()
        other = RuntimeStore.open(self.lock, self.config)
        try:
            self.assertEqual(other.get_checkpoint(), cp)
            self.assertEqual(self.rows(other), durable)
            self.assertEqual(other.list_risk_valuations(), valuations)
            self.assertEqual(other.list_risk_verdicts(), verdicts)
        finally:
            other.close()
        self.evidence.append(dict(label=label, checkpoint=cp, decisions=len(decisions),
            valuations=valuations, verdicts=verdicts, actions=actions, fills=fills,
            attempts=sum(action.attempt_count for action in actions), broker_calls=len(self.trace),
            placements=len(self.sends), epochs=durable["risk_epochs"],
            adapter_invocations=len(self.adapter_invocations),
            cycle_calls=len(self.cycle_calls), returned_cycles=len(self.results),
            scheduler_wakes=sum(result.wake_count for result, _ in self.scheduled),
            restarts=tuple(self.restarts)))
        return cp

    def assert_book(self, row=None):
        """Independent exact economics from one capital anchor and unique fills.

        Called at complete ordinary boundaries, never to reinterpret accepted
        historical snapshots after an intentionally late-evidence injection.
        """
        row = row or self.store.get_latest_risk_valuation()
        cfg = self.store.get_risk_configuration().configuration
        with localcontext() as context:
            context.prec = 80
            cash, base = cfg.risk_capital_quote, D(0)
            for fill in self.store.list_fills():
                if fill.executed_at_ms > row.valued_at_ms:
                    continue
                sign = D(1) if fill.side == "BUY" else D(-1)
                cash -= sign * fill.executed_quantity * fill.execution_price
                base += sign * fill.executed_quantity
                if fill.fee_currency == cfg.quote_currency:
                    cash -= fill.execution_fee
                elif fill.fee_currency == cfg.base_currency:
                    base -= fill.execution_fee
            self.assertEqual(row.book, RiskBook(cash, base))
            self.assertEqual(row.risk_equity, cash + base * row.mark_price)
        return row

    def observe_cycle(self, *args, **kwargs):
        call = dict(at_ms=self.clock.ms, checkpoint=self.store.get_checkpoint())
        self.cycle_calls.append(call)
        try:
            result = run_single_cycle(*(args or (self.store, self.market, self.broker, self.adapter)),
                **(kwargs or dict(utc_now=self.clock.now, monotonic=lambda: self.clock.elapsed)))
        except BaseException as error:
            call["failure_type"] = type(error).__name__
            raise
        call["result"] = result
        self.assertEqual(result.checkpoint, self.store.get_checkpoint())
        self.results.append(result)
        self.verify(result.outcome.value)
        return result

    def cycle(self):
        return self.observe_cycle()

    def step(self, price, *, hours=1):
        self.wake(price, hours=hours)(0)
        return self.cycle()

    def bootstrap(self, **changes):
        self.assertIs(self.cycle().outcome, CycleOutcome.BOOTSTRAP)
        # Activation needs a durable candle and confirmed exposure. This is an
        # explicit operator fixture step, never a cycle/scheduler fallback.
        row = self.store.initialize_risk_journal(risk_configuration(**changes),
            candle_open_ms=self.store.get_checkpoint().last_processed_candle_ms)
        self.verify("explicit activation")
        return row

    def scheduler(self, events=()):
        self.stop = fixtures.Stop(self, events)
        # Observation-only wrapper: call the actual frozen cycle, record its
        # returned result and audit durability. No synthetic outcomes/activation.
        with patch.object(scheduler_module, "run_single_cycle", side_effect=self.observe_cycle):
            result = run_hourly_scheduler(self.store, self.market, self.broker, self.adapter, self.stop,
                utc_now=self.clock.now, monotonic=lambda: self.clock.elapsed)
        self.assertEqual(result.checkpoint, self.store.get_checkpoint())
        self.assertNotIn(1.0, self.stop.waits)
        self.assertNotIn(2.0, self.stop.waits)
        self.scheduled.append((result, tuple(self.stop.waits)))
        self.verify("scheduler " + result.exit_reason.value)
        return result

    def restart(self):
        before = self.rows()
        normalized = self.reopen()  # Real close, new lock/store, frozen process-entry normalization.
        self.assertEqual(normalized, self.store.get_checkpoint())
        self.restarts.append(normalized)
        self.assertEqual(self.rows()["risk_epochs"], before["risk_epochs"])
        self.assertEqual(self.rows()["risk_valuations"], before["risk_valuations"])
        self.assertEqual(self.rows()["risk_verdicts"], before["risk_verdicts"])
        self.verify("restart normalized")
        return normalized

    def control(self, name):
        before = len(self.trace), len(self.sends), len(self.cancels)
        self.operator_active = True
        try:
            if name == "rearm_runtime_halt":
                result = self.store.rearm_runtime_halt(expected_sequence=self.store.get_checkpoint().sequence,
                                                       operator_at_ms=self.clock.ms)
            else:
                result = self.store.rearm_risk_epoch(expected_epoch_id=self.store.get_current_risk_epoch().epoch_id,
                                                    operator_at_ms=self.clock.ms)
        finally:
            self.operator_active = False
            self.assertEqual((len(self.trace), len(self.sends), len(self.cancels)), before)
            self.assert_guards()
        self.verify(name)
        return result

    def fork_journal(self):
        """Adversarial variants affect a copied TEMP fixture, never its source."""
        registry = Path(self.directory) / "variant"
        registry.mkdir(mode=0o700)
        source = self.lock.database_path
        self.store.close()
        self.lock.release()
        original = source.read_bytes()
        self.lock = RuntimeAccountLock(registry, "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        with sqlite3.connect(source) as connection:
            connection.backup(self.store._connection)
        self.clients()
        self.verify("copied fixture")
        return source, original


class RuntimeRiskIntegrationE2ETests(RiskE2ECase):
    def test_a_healthy_exact_lifecycle_long_restart_and_scheduler_exit(self):
        self.simple_economics = False  # Original frozen fractional fills/fees.
        commit = self.store.commit_decision

        def first_durable_candle(*args, **kwargs):
            commit(*args, **kwargs)
            raise ProcessDeath()

        # Activation requires at least one accepted candle. Stop after that
        # primer, explicitly activate, then finish the reserved bootstrap.
        with patch.object(self.store, "commit_decision", side_effect=first_durable_candle), self.assertRaises(ProcessDeath):
            self.cycle()
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 0)
        self.store.initialize_risk_journal(risk_configuration(max_entries_per_utc_day=10), candle_open_ms=0)
        self.verify("activation before remaining bootstrap")
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.BOOTSTRAP)
        entry = self.step("110")
        self.assertIs(entry.outcome, CycleOutcome.OBSERVED)
        self.assertEqual(entry.logical_action_id, fixtures.ENTRY_ID)
        self.assert_owned(RuntimeState.LONG, "0.04995")
        self.step("110")
        before = self.assert_book()
        epoch = self.store.get_current_risk_epoch()
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.NO_NEW_DATA)
        self.assertEqual(self.store.get_current_risk_epoch(), epoch)
        self.assertEqual(self.store.get_latest_risk_valuation(), before)
        self.step("110")
        result = self.scheduler([self.wake("60"), self.wake("60")])
        self.assertEqual((result.cycle_count, result.wake_count, result.exit_reason), (3, 2, SchedulerExit.STOP_REQUESTED))
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.FLAT)
        self.assertEqual((len(self.sends), len(self.cancels), len(self.store.list_fills())), (2, 0, 2))
        actions = sorted(self.store.list_actions(), key=lambda action: action.candle_open_ms)
        self.assertEqual([action.logical_action_id for action in actions], [fixtures.ENTRY_ID, fixtures.EXIT_ID])
        self.assertEqual([action.authorized_amount for action in actions], [D("10.123456789"), D("0.04995")])
        self.assertEqual([action.submitted_amount for action in actions], [D("10.1234567"), D("0.04995")])
        self.assertEqual([action.order_link_id for action in actions], ["bot1-" + action.logical_action_id[:23] for action in actions])
        self.assertTrue(all(action.phase is ActionPhase.TERMINAL_CONFIRMED for action in actions))
        self.assertEqual([fill.execution_price for fill in self.store.list_fills()], [D("100.123456789"), D("111.123456789")])
        self.assertEqual([fill.execution_fee for fill in self.store.list_fills()], [D("0.00005"), D("0.01")])
        self.assert_book()
        self.assertEqual(epoch.epoch_sequence, 1)
        self.assertEqual(self.operator_calls, [])
        self.restart()
        self.assertIs(self.cycle().checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(len(self.sends), 2)

    def test_b_d_e_prepared_crash_consumed_slot_block_hold_and_broken_copy(self):
        self.bootstrap(max_entries_per_utc_day=1)
        self.wake("110")(0)
        with patch.object(self, "crash_at_adapter_entry", True), self.assertRaises(ProcessDeath):
            self.cycle()
        action = self.store.list_actions()[0]
        self.assertEqual((action.phase, action.attempt_count, len(self.sends)), (ActionPhase.PREPARED, 0, 0))
        self.verify("crash before attempt")
        self.restart()
        self.cycle()
        self.assertIs(self.store.get_action(action.logical_action_id).phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertIs(self.store.get_risk_verdict(action.candle_open_ms).verdict, RiskVerdict.ALLOW)
        self.step("80")  # Genuine EXIT intent aligns still-FLAT exposure; no sale.
        result = self.scheduler([self.wake("110"), self.wake("110"), self.wake("110"), self.wake("110")])
        self.assertEqual((result.cycle_count, result.wake_count), (5, 4))
        blocked = next(result for result in self.results if result.outcome is CycleOutcome.RISK_BLOCKED)
        self.assertEqual((blocked.risk_verdict, blocked.risk_reason), (RiskVerdict.BLOCK, RiskReason.ENTRY_COUNT_LIMIT))
        at = blocked.processed_candle_open_ms[-1]
        decision = self.store.get_decision(at)
        self.assertEqual((decision.disposition, decision.desired_position, decision.action_id), (DecisionDisposition.WAIT, 1, None))
        self.assertEqual(len(self.store.list_actions()), 1)
        self.assertEqual(self.sends, [])
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.NO_NEW_DATA)
        self.assertEqual(self.store.get_risk_verdict(at).reason, RiskReason.ENTRY_COUNT_LIMIT)
        self.assert_owned(RuntimeState.FLAT, "0")
        source, original = self.fork_journal()
        latest = self.store.get_latest_risk_valuation()
        # Deliberately insert a valid historical boundary in the COPY: remove
        # only its last HOLD's LIVE provenance, with no later links to corrupt.
        with self.store._transaction(validate=False):
            self.store._connection.execute("DELETE FROM risk_verdicts WHERE candle_open_ms=?", (latest.candle_open_ms,))
            self.store._connection.execute("UPDATE risk_valuations SET mode='REPLAY_ONLY' WHERE epoch_id=? AND valued_at_ms=?",
                                           (latest.epoch_id, latest.valued_at_ms))
            self.store._connection.execute("UPDATE decisions SET disposition='REPLAY_ONLY' WHERE candle_open_ms=?", (latest.candle_open_ms,))
        self.verify("broken refusal provenance copy")
        rejected = self.step("110")
        self.assertIs(rejected.outcome, CycleOutcome.HALTED)
        self.assertIs(rejected.reason, RuntimeReason.INCONSISTENT_EVIDENCE)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.operator_calls, [])

    def test_c_lost_ack_partial_trip_terminal_recovery_exit_and_latch_block(self):
        self.bootstrap(max_daily_loss_fraction=D("0.00004"), max_drawdown_fraction=D(1))
        self.status = "PartiallyFilled"
        original = self.store.record_observation

        def lose_ack(action, *args, **kwargs):
            if action.phase is ActionPhase.ACKNOWLEDGED:
                raise ProcessDeath()
            return original(action, *args, **kwargs)

        self.wake("110")(0)
        with patch.object(self.store, "record_observation", side_effect=lose_ack), self.assertRaises(ProcessDeath):
            self.cycle()
        action = self.store.list_actions()[0]
        self.assertEqual((action.phase, action.attempt_count, action.broker_order_id), (ActionPhase.ATTEMPT_STARTED, 1, None))
        self.assertEqual((len(self.sends), self.store.list_fills()), (1, ()))
        self.verify("mutation happened; receipt lost")
        self.restart()
        self.cycle()
        action = self.store.get_action(action.logical_action_id)
        self.assertEqual(action.broker_order_id, "order-1")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0.02")
        tripped = self.step("98")
        self.assertEqual((tripped.outcome, tripped.risk_reason), (CycleOutcome.RISK_TRIPPED, RiskReason.DAILY_LOSS_LIMIT))
        self.assert_owned(RuntimeState.ORDER_PENDING, "0.02")
        self.assertEqual(self.assert_book().book, RiskBook(D(998), D("0.02")))
        self.assertEqual((len(self.sends), len(self.store.list_actions())), (1, 1))
        self.clock.advance(1)
        self.add_execution("order-1", D("0.03"), "remaining-buy", status="Filled")
        self.round()
        self.assert_owned(RuntimeState.LONG, "0.05")
        self.assertEqual(len(self.store.list_fills()), 2)
        self.status = "Filled"
        self.step("110")
        self.assertEqual(self.assert_book().book, RiskBook(D(995), D("0.05")))
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        exit_result = self.step("80")
        self.assertIs(exit_result.risk_verdict, RiskVerdict.ALLOW)
        self.assert_owned(RuntimeState.FLAT, "0")
        blocked = self.step("110")
        self.assertEqual((blocked.outcome, blocked.risk_reason), (CycleOutcome.RISK_BLOCKED, RiskReason.RISK_LATCH_ACTIVE))
        self.assertEqual((len(self.sends), len(self.cancels)), (2, 0))
        self.assertEqual([send["side"] for send in self.sends], ["Buy", "Sell"])
        self.restart()
        self.cycle()
        self.assertEqual(len(self.sends), 2)
        self.assertEqual(self.operator_calls, [])

    def test_f_m_n_o_both_latches_child_restart_exit_count_and_midnight(self):
        self.buy_fee, self.sell_fee = D("0.00005"), D("0.01")
        self.bootstrap(max_daily_loss_fraction=D("0.0001"), max_drawdown_fraction=D(1), max_entries_per_utc_day=1)
        self.wallet_btc = "999999999"  # Unrelated holdings never enter the book or SELL.
        self.step("110")
        self.step("110")
        tripped = self.step("98")
        parent_row = self.assert_book()
        self.assertEqual((tripped.outcome, tripped.risk_reason, parent_row.risk_equity),
                         (CycleOutcome.RISK_TRIPPED, RiskReason.DAILY_LOSS_LIMIT, D("999.8951")))
        self.assert_owned(RuntimeState.LONG, "0.04995")
        self.assertEqual((len(self.sends), len(self.cancels)), (1, 0))
        with self.public_time_failure({"retCode": 987654, "result": {}}):
            halted = self.cycle()
        self.assertIs(halted.outcome, CycleOutcome.HALTED)
        risk_rows = {name: rows for name, rows in self.rows().items() if name.startswith("risk_")}
        with self.assertRaises(RuntimeStoreConflictError):
            self.control("rearm_risk_epoch")
        self.clock.advance(1)
        rearmed = self.control("rearm_runtime_halt")
        self.assertIs(rearmed.snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertIs(rearmed.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual({name: rows for name, rows in self.rows().items() if name.startswith("risk_")}, risk_rows)
        with self.assertRaises(RuntimeStoreConflictError):
            self.control("rearm_risk_epoch")
        self.round()  # Separate real frozen broker reads, never inside either control.
        self.assert_owned(RuntimeState.LONG, "0.04995")
        parent = self.store.get_current_risk_epoch()
        configuration = self.store.get_risk_configuration()
        checkpoint = self.store.get_checkpoint()
        child_row = self.control("rearm_risk_epoch")
        child = self.store.get_current_risk_epoch()
        self.assertEqual((child.epoch_sequence, child.parent_epoch_id, child.started_at_ms),
                         (2, parent.epoch_id, parent_row.valued_at_ms))
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertEqual(self.store.get_risk_configuration(), configuration)
        self.assertEqual((child_row.book, child_row.fill_evidence_count, child_row.fill_evidence_digest,
                          child_row.valued_at_ms, child_row.entries_this_utc_day),
                         (parent_row.book, parent_row.fill_evidence_count, parent_row.fill_evidence_digest,
                          parent_row.valued_at_ms, 1))
        self.assertEqual((child_row.risk_equity, child_row.peak_risk_equity,
                          child_row.utc_day_start_risk_equity, child_row.daily_pnl),
                         (D("999.8951"), D("999.8951"), D("999.8951"), D(0)))
        self.assertIsNone(child_row.trip_reason)
        parent_history = self.store.list_risk_valuations(parent.epoch_id), self.store.list_risk_verdicts(parent.epoch_id)
        self.assert_book(child_row)
        self.restart()
        self.cycle()
        self.assertEqual(self.store.get_current_risk_epoch(), child)
        self.assertEqual(self.store.get_latest_risk_valuation(), child_row)
        self.step("98")
        self.assertEqual(self.store.get_latest_risk_valuation().valued_at_ms, child_row.valued_at_ms + HOUR)
        self.assertEqual(self.store.get_latest_risk_valuation().epoch_id, child.epoch_id)
        for _ in range(20):
            result = self.step("98")
            if result.checkpoint.snapshot.state is RuntimeState.FLAT:
                break
        else:
            self.fail("Synthetic EMA path did not produce a bounded genuine EXIT.")
        self.assertEqual([send["side"] for send in self.sends], ["Buy", "Sell"])
        self.assertEqual(self.sends[-1]["qty"], "0.04995")
        self.assertIs(self.store.list_risk_verdicts()[-1].verdict, RiskVerdict.ALLOW)
        blocked = self.step("110")
        self.assertEqual((blocked.outcome, blocked.risk_reason), (CycleOutcome.RISK_BLOCKED, RiskReason.ENTRY_COUNT_LIMIT))
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        until_midnight = 72 - self.clock.ms // HOUR
        self.assertGreater(until_midnight, 0)
        observed_counts = []

        def remember_count():
            observed_counts.append(self.store.get_latest_risk_valuation().entries_this_utc_day)

        events = [self.wake("110", before=remember_count) for _ in range(until_midnight + 1)]
        scheduled = self.scheduler(events)
        self.assertEqual(scheduled.wake_count, until_midnight + 1)
        self.assertTrue(all(count == 1 for count in observed_counts[:until_midnight]))
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 0)
        self.assertEqual(len(self.sends), 2)  # Free capacity at midnight cannot resurrect a refused HOLD BUY.
        self.assertEqual(self.store.get_current_risk_epoch(), child)
        self.assertEqual((self.store.list_risk_valuations(parent.epoch_id), self.store.list_risk_verdicts(parent.epoch_id)), parent_history)
        self.assert_book()
        self.restart()
        self.cycle()
        self.assertEqual(self.store.get_current_risk_epoch(), child)

    def test_g_new_peak_exact_drawdown_restart_and_recovery_do_not_rearm(self):
        self.bootstrap(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.001"))
        self.step("110")
        self.step("300")
        peak = self.assert_book()
        self.assertEqual(peak.peak_risk_equity, D(1010))
        result = self.step("279.8")
        tripped = self.assert_book()
        self.assertEqual((result.outcome, result.risk_reason, tripped.risk_equity),
                         (CycleOutcome.RISK_TRIPPED, RiskReason.MAX_DRAWDOWN, D("1008.99")))
        self.assertEqual(peak.peak_risk_equity - tripped.risk_equity, peak.peak_risk_equity * D("0.001"))
        self.restart()
        self.cycle()
        self.step("1000")
        latest = self.assert_book()
        self.assertEqual((latest.trip_reason, latest.tripped_at_ms), (RiskReason.MAX_DRAWDOWN, tripped.valued_at_ms))
        self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 1)
        self.assert_owned(RuntimeState.LONG, "0.05")
        self.assertEqual((len(self.sends), self.cancels, self.operator_calls), (1, [], []))

    def test_h_outgoing_midnight_loss_precedes_rollover_and_survives_restart(self):
        self.prices = ["100"] * 69
        self.clock.advance(19 * HOUR)
        self.bootstrap(max_daily_loss_fraction=D("0.0001"), max_drawdown_fraction=D(1))
        self.step("110")  # 22:00 accepted boundary.
        self.assertEqual(self.store.get_latest_risk_valuation().valued_at_ms, 70 * HOUR)
        self.step("110")  # 23:00: filled book and consumed entry.
        before = self.assert_book()
        result = self.step("98")  # 00:00 closes the outgoing daily loss.
        row = self.assert_book()
        self.assertEqual((result.outcome, row.trip_reason, row.tripped_at_ms),
                         (CycleOutcome.RISK_TRIPPED, RiskReason.DAILY_LOSS_LIMIT, 72 * HOUR))
        self.assertEqual((row.utc_day_start_ms, row.utc_day_start_risk_equity, row.daily_pnl,
                          row.entries_this_utc_day, row.peak_risk_equity),
                         (72 * HOUR, D("999.9"), D(0), 0, before.peak_risk_equity))
        self.assertEqual(before.entries_this_utc_day, 1)
        self.step("110")  # 01:00 recovery cannot clear the outgoing breach.
        self.restart()
        self.cycle()
        self.assertEqual(self.store.get_latest_risk_valuation().trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual((self.store.get_current_risk_epoch().epoch_sequence, len(self.sends), self.operator_calls), (1, 1, []))

    def test_i_j_downtime_missed_breach_interrupted_catchup_and_restart(self):
        self.bootstrap(max_daily_loss_fraction=D("0.0001"), max_drawdown_fraction=D(1))
        self.step("110")
        self.step("110")
        previous = self.assert_book()
        self.wake("98")(0)
        self.wake("130")(0)
        self.wake("130")(0)
        self.assertIs(self.cycle().outcome, CycleOutcome.REPLAY_ONLY)
        self.assertEqual(self.store.get_latest_risk_valuation(), previous)
        self.wake("130")(0)
        append = self.store.append_risk_replay_valuation
        appended = []

        def crash_after_two(**kwargs):
            append(**kwargs)
            appended.append(kwargs["candle_open_ms"])
            if len(appended) == 2:
                raise ProcessDeath()

        with patch.object(self.store, "append_risk_replay_valuation", side_effect=crash_after_two), self.assertRaises(ProcessDeath):
            self.cycle()
        partial = self.store.get_latest_risk_valuation()
        missed, recovered = self.store.list_risk_valuations()[-2:]
        self.assertEqual((missed.mode, recovered.mode), (RiskValuationMode.REPLAY_ONLY, RiskValuationMode.REPLAY_ONLY))
        self.assertEqual(missed.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertGreater(recovered.risk_equity, D(1000))
        self.assertTrue(recovered.trip_pending_report)
        self.verify("interrupted catch-up")
        self.restart()
        append = self.store.append_risk_replay_valuation
        with patch.object(self.store, "append_risk_replay_valuation", wraps=append) as resumed:
            result = self.cycle()
        self.assertEqual([call.kwargs["candle_open_ms"] for call in resumed.call_args_list], [partial.candle_open_ms + HOUR])
        latest = self.assert_book()
        self.assertEqual((result.outcome, latest.trip_reason, latest.tripped_at_ms),
                         (CycleOutcome.RISK_TRIPPED, RiskReason.DAILY_LOSS_LIMIT, missed.valued_at_ms))
        self.assertFalse(latest.trip_pending_report)
        rows = self.store.list_risk_valuations()
        self.assertEqual([row.valued_at_ms for row in rows], list(range(rows[0].valued_at_ms, rows[-1].valued_at_ms + HOUR, HOUR)))
        self.assertEqual((len(self.sends), self.cancels, self.operator_calls), (1, [], []))
        self.restart()
        self.cycle()

    def test_k_late_execution_blocks_successor_live_without_rewriting_history(self):
        self.bootstrap()
        self.status = "New"
        self.step("110")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0")
        self.assertEqual(self.store.list_fills(), ())  # ACK is not an owned fill.
        self.step("110")
        previous = self.assert_book()
        retained = self.rows()
        self.add_execution("order-1", D("0.02"), "late-at-boundary", status="PartiallyFilled")
        self.remote_fills[-1]["execTime"] = str(previous.valued_at_ms)
        self.wake("110")(0)
        with self.assertRaisesRegex(RuntimeStoreConflictError, "Predecessor owned-fill evidence changed"):
            self.cycle()
        after = self.rows()
        for name in ("candles", "decisions", "risk_epochs", "risk_valuations", "risk_verdicts"):
            self.assertEqual(after[name], retained[name], name)
        self.assertEqual((len(self.store.list_actions()), len(self.sends)), (1, 1))
        self.assertEqual(self.store.list_fills()[0].executed_at_ms, previous.valued_at_ms)
        self.assertEqual(self.store.get_latest_risk_valuation(), previous)
        self.assert_owned(RuntimeState.ORDER_PENDING, "0.02")
        self.verify("late evidence refused successor")
        self.restart()
        self.assertEqual(self.store.get_latest_risk_valuation(), previous)

    def test_l_copied_post_boundary_buy_sell_net_same_book_cannot_rearm(self):
        self.bootstrap(max_daily_loss_fraction=D("0.001"), max_drawdown_fraction=D(1), max_entries_per_utc_day=5)
        self.step("110")
        self.step("90")  # First round trip stays below the configured loss limit.
        self.step("110")
        self.step("110")
        self.step("80")  # Genuine EXIT also latches the later exact daily loss.
        self.step("80")  # Accept that EXIT's fills at the next boundary, safely FLAT/0.
        parent = self.assert_book()
        self.assertIs(parent.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        source, original = self.fork_journal()
        before = self.rows()
        buys = [a for a in self.store.list_actions() if a.kind is JournalActionKind.ENTRY]
        sell = next(a for a in self.store.list_actions() if a.kind is JournalActionKind.EXIT)
        # Adversarial retained-evidence copy ONLY: additional observations for
        # known owned terminal IDs. Ordinary reconciliation does not append to
        # terminal evidence. This tests the stronger two-sided post-T guard,
        # without fabricating an ALLOW or sending/authorizing another action.
        extra = []
        for action, price, fee in ((buys[0], "100", "0"), (sell, "101", "0.01")):
            extra.append(OwnedFillRecord("bybit-demo", "research", "post-" + action.side,
                action.logical_action_id, action.broker_order_id, action.order_link_id, action.symbol,
                action.side, D("0.01"), D(price), D(fee), "USDT", parent.valued_at_ms + 1, self.clock.ms))
        import trading_lab.runtime.store as store_records
        with self.store._transaction(validate=False):
            for fill in extra:
                self.store._insert("fills", store_records._encode(fill))
        self.verify("post-boundary adversarial copied evidence")
        with localcontext() as context:
            context.prec = 80
            self.assertEqual(extra[0].executed_quantity - extra[1].executed_quantity, 0)
            self.assertEqual(extra[1].executed_quantity * extra[1].execution_price - extra[1].execution_fee,
                             extra[0].executed_quantity * extra[0].execution_price)
        with self.assertRaisesRegex(RuntimeStoreConflictError, "boundary precedes retained owned executions"):
            self.control("rearm_risk_epoch")
        after = self.rows()
        for name in before.keys() - {"fills"}:
            self.assertEqual(after[name], before[name], name)
        self.assertEqual(self.store.get_latest_risk_valuation(), parent)
        self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 1)
        self.assertEqual(source.read_bytes(), original)

    def test_atomic_authorization_fault_rolls_back_then_safe_restart_authorizes_once(self):
        self.bootstrap()
        before = self.rows()
        insert = self.store._insert

        def disk_fault(table, values):
            if table == "risk_verdicts":
                raise sqlite3.OperationalError("Synthetic failure before atomic authorization commit")
            return insert(table, values)

        self.wake("110")(0)
        with patch.object(self.store, "_insert", side_effect=disk_fault), self.assertRaises(RuntimeStoreError):
            self.cycle()
        after = self.rows()
        for name in before.keys() - {"checkpoint"}:
            self.assertEqual(after[name], before[name], name)
        self.assertEqual((self.sends, self.store.list_actions()), ([], ()))
        self.verify("rolled-back atomic ALLOW transaction")
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.OBSERVED)
        self.assertEqual((len(self.sends), len(self.store.list_actions()), self.store.get_latest_risk_valuation().entries_this_utc_day), (1, 1, 1))
        self.step("110")
        self.step("80")
        self.assert_owned(RuntimeState.FLAT, "0")
        self.assertEqual(len(self.sends), 2)
        self.restart()
        self.cycle()
        self.assertEqual(len(self.sends), 2)

    def test_not_ready_scheduler_explicit_activation_and_healthy_risk_halt_precedence(self):
        self.assertIs(self.cycle().outcome, CycleOutcome.BOOTSTRAP)
        frontier = self.store.get_checkpoint().last_processed_candle_ms
        scheduled = self.scheduler([self.wake("110")])
        self.assertEqual((scheduled.cycle_count, scheduled.wake_count), (2, 1))
        self.assertIs(scheduled.last_cycle.outcome, CycleOutcome.RISK_NOT_READY)
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, frontier)
        self.assertIsNone(self.store.get_decision(frontier + HOUR))
        self.assertEqual((self.store.list_actions(), self.store.list_risk_valuations(), self.sends), ((), (), []))
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.RISK_NOT_READY)
        self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=frontier)
        result = self.cycle()  # Same unconsumed LIVE candle, now explicitly active.
        self.assertIs(result.outcome, CycleOutcome.OBSERVED)
        self.assertEqual(len(self.sends), 1)
        self.assertIsNone(self.store.get_latest_risk_valuation().trip_reason)
        before = self.rows()
        with self.public_time_failure({"retCode": 987654, "result": {}}):
            halted = self.cycle()
        self.assertEqual((halted.outcome, halted.reason), (CycleOutcome.HALTED, RuntimeReason.INCONSISTENT_EVIDENCE))
        for name in ("risk_epochs", "risk_valuations", "risk_verdicts", "actions", "fills"):
            self.assertEqual(self.rows()[name], before[name], name)
        self.restart()
        self.assertIs(self.cycle().outcome, CycleOutcome.HALTED)
        self.assertEqual((len(self.sends), self.cancels, self.operator_calls), (1, [], []))


if __name__ == "__main__":
    unittest.main()
