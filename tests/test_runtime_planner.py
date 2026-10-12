"""Offline authorization, golden identities and frozen state/store compatibility."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import inspect
import json
import unittest
from unittest.mock import patch

from trading_lab.exchange.order_actions import SpotMarketOrderRequest
from trading_lab.exchange.bybit_spot_rules import (
    BybitSpotInstrumentRules, normalize_spot_market_buy_quote_amount,
    normalize_spot_market_sell_base_quantity,
)
from trading_lab.runtime.planner import (
    ActionPlan, CanonicalDecision, DecisionMode, PlanKind, PlannerError, plan_action,
)
import trading_lab.runtime.planner as module
from trading_lab.runtime.state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeEventType,
    RuntimeReason, RuntimeState, RuntimeStateSnapshot, transition_runtime_state,
)
from trading_lab.runtime.store import (
    ActionPhase, ActionRecord, DecisionDisposition, JournalActionKind, RuntimeCheckpoint, RuntimeStore,
)
from tests.test_runtime_store import ACTION_ID, D, HOUR, StoreCase, candle, configuration, fill


def canonical(signal="LONG_ENTRY", desired=1, time=0):
    return CanonicalDecision("BTCUSDT", "60", time, "d" * 64, signal, desired, time + HOUR)


def checkpoint(state=RuntimeState.FLAT, *, now=HOUR, quantity="0.123456789", **changes):
    if state in (RuntimeState.STARTING, RuntimeState.SYNCHRONIZING, RuntimeState.UNCERTAIN):
        snapshot = RuntimeStateSnapshot(state, reason=RuntimeReason.EVIDENCE_MISSING if state == RuntimeState.UNCERTAIN else None)
    elif state == RuntimeState.HALTED:
        snapshot = RuntimeStateSnapshot(state, reason=RuntimeReason.OWNERSHIP_CONFLICT)
    elif state == RuntimeState.STOPPING:
        snapshot = RuntimeStateSnapshot(state, D("0"), PositionEvidence.LAST_KNOWN, stopped_from=RuntimeState.FLAT)
    else:
        pending = PendingAction(ACTION_ID, PendingActionKind.ENTRY) if state == RuntimeState.ORDER_PENDING else None
        snapshot = RuntimeStateSnapshot(state, D("0") if state == RuntimeState.FLAT else D(quantity),
                                        PositionEvidence.CONFIRMED, 0, pending)
    return replace(RuntimeCheckpoint(7, snapshot, last_reconciled_at_ms=now, observed_at_ms=now,
                                     halted_at_ms=now if state == RuntimeState.HALTED else None,
                                     shutdown_at_ms=now if state == RuntimeState.STOPPING else None), **changes)


def proposed_snapshot(snapshot, result):
    for event in result.events:
        snapshot = transition_runtime_state(snapshot, event)
    return snapshot


def plan(decision=None, cp=None, config=None, *, now=HOUR, mode=DecisionMode.LIVE, history=()):
    return plan_action(config or configuration(), cp or checkpoint(), decision or canonical(),
                       evaluated_at_ms=now, mode=mode, action_history=history)


class PlannerMatrixTests(unittest.TestCase):
    """Every runtime state and valid signal/intent pair is counted separately."""


_INTENTS = (("HOLD", 0), ("HOLD", 1), ("LONG_ENTRY", 1), ("LONG_EXIT", 0))
_EXPECTED = {
    RuntimeState.FLAT: (PlanKind.NOOP, PlanKind.HALT, PlanKind.PLACE_BUY, PlanKind.NOOP),
    RuntimeState.LONG: (PlanKind.HALT, PlanKind.NOOP, PlanKind.NOOP, PlanKind.PLACE_SELL),
    RuntimeState.ORDER_PENDING: (PlanKind.WAIT,) * 4,
    RuntimeState.STARTING: (PlanKind.RECONCILE,) * 4,
    RuntimeState.SYNCHRONIZING: (PlanKind.RECONCILE,) * 4,
    RuntimeState.UNCERTAIN: (PlanKind.RECONCILE,) * 4,
    RuntimeState.HALTED: (PlanKind.HALT,) * 4,
    RuntimeState.STOPPING: (PlanKind.HALT,) * 4,
}


def matrix_case(state, signal, desired, expected):
    def test(self):
        cp, decision = checkpoint(state), canonical(signal, desired)
        before = deepcopy((cp, decision))
        result = plan(decision, cp)
        self.assertIs(result.kind, expected)
        self.assertEqual((cp, decision), before)
        if expected not in (PlanKind.PLACE_BUY, PlanKind.PLACE_SELL):
            self.assertIsNone(result.action)
        if expected == PlanKind.WAIT:
            self.assertIs(result.decision.disposition, DecisionDisposition.WAIT)
            proposed = proposed_snapshot(cp.snapshot, result)
            self.assertEqual(proposed.pending_action, cp.snapshot.pending_action)
            self.assertIs(proposed.state, RuntimeState.ORDER_PENDING)
    return test


for _state in RuntimeState:
    for _index, (_signal, _desired) in enumerate(_INTENTS):
        setattr(PlannerMatrixTests, f"test_{_state.value.lower()}_{_signal.lower()}_{_desired}",
                matrix_case(_state, _signal, _desired, _EXPECTED[_state][_index]))


class PlannerTests(unittest.TestCase):
    def test_exact_public_outcome_and_mode_values(self):
        self.assertEqual([kind.value for kind in PlanKind], ["NOOP", "PLACE_BUY", "PLACE_SELL", "WAIT", "RECONCILE", "HALT"])
        self.assertEqual([mode.value for mode in DecisionMode], ["LIVE", "BOOTSTRAP", "REPLAY_ONLY"])

    def test_buy_is_exact_fixed_quote_authorization(self):
        config = configuration()
        result = plan(config=config)
        self.assertEqual(result.action.authorized_amount, config.buy_quote_budget)
        self.assertEqual((result.action.side, result.action.amount_unit, result.action.currency), ("BUY", "QUOTE", "USDT"))
        self.assertIs(result.action.kind, JournalActionKind.ENTRY)
        self.assertIs(result.decision.disposition, DecisionDisposition.ACTION)
        self.assertEqual(result.decision.action_id, result.action.logical_action_id)

    def test_sell_is_exact_owned_base_without_fee_reserve(self):
        cp = checkpoint(RuntimeState.LONG, quantity="0.123456789123456789")
        result = plan(canonical("LONG_EXIT", 0), cp)
        self.assertEqual(result.action.authorized_amount, cp.snapshot.owned_base_quantity)
        self.assertEqual((result.action.side, result.action.amount_unit, result.action.currency), ("SELL", "BASE", "BTC"))
        self.assertIs(result.action.kind, JournalActionKind.EXIT)

    def test_plans_are_prepared_only_without_fabricated_broker_evidence(self):
        for result in (plan(), plan(canonical("LONG_EXIT", 0), checkpoint(RuntimeState.LONG))):
            with self.subTest(kind=result.kind):
                self.assertIs(result.action.phase, ActionPhase.PREPARED)
                self.assertEqual(result.action.attempt_count, 0)
                for name in ("broker_order_id", "submitted_amount", "acknowledgement_broker_ms", "acknowledgement_observed_ms",
                             "observed_at_ms", "order_status", "external_status", "terminal_at_ms"):
                    self.assertIsNone(getattr(result.action, name))

    def test_recovery_budget_and_deadline_are_exact_configuration_values(self):
        config = configuration()
        action = plan(config=config).action
        self.assertEqual(action.remaining_reconciliation_rounds, config.reconciliation_round_limit)
        self.assertEqual(action.remaining_read_attempts, config.read_attempt_limit)
        self.assertEqual(action.reconciliation_deadline_ms, HOUR + config.reconciliation_timeout_ms)

    def test_stage9_downward_normalization_does_not_replace_authorization(self):
        rules = BybitSpotInstrumentRules("BTCUSDT", "BTC", "USDT", "Trading", D("0.00000001"),
                                         D("0.0000001"), D("1"), D("10"), D("0.01"))
        buy = plan().action
        sell = plan(canonical("LONG_EXIT", 0), checkpoint(RuntimeState.LONG)).action
        for action, normalize in ((buy, normalize_spot_market_buy_quote_amount), (sell, normalize_spot_market_sell_base_quantity)):
            request = SpotMarketOrderRequest(action.symbol, action.side, action.authorized_amount, action.amount_unit, action.order_link_id)
            preview = D(normalize(rules, request.authorized_amount))
            self.assertLess(preview, action.authorized_amount)
            self.assertIsNone(action.submitted_amount)
        self.assertEqual(buy.authorized_amount, D("10.123456789"))
        self.assertEqual(sell.authorized_amount, D("0.123456789"))

    def test_golden_canonical_json_bytes_sha256_and_link(self):
        expected = (b'{"action_kind":"ENTRY","authorized_amount":"10.123456789","candle_open_ms":0,"configuration_digest":"'
                    + b'b' * 64
                    + b'","instance_key":{"account_binding":"research","bot_id":"bot1","broker_id":"bybit-demo"},"runtime_contract_version":1,"side":"BUY","unit":"QUOTE"}')
        self.assertEqual(module._canonical_intent(configuration(), canonical(), JournalActionKind.ENTRY, D("10.123456789")), expected)
        action = plan().action
        self.assertEqual(action.logical_action_id, "7ad9ceb690c4a52e25b96d6c3408489f66924eb1ed05e002e9f1358e8c216b20")
        self.assertEqual(action.order_link_id, "bot1-7ad9ceb690c4a52e25b96d6")

    def test_exit_payload_has_exact_base_policy_and_no_observation_fields(self):
        payload = json.loads(module._canonical_intent(configuration(), canonical("LONG_EXIT", 0), JournalActionKind.EXIT, D("0.123456789")))
        self.assertEqual(set(payload), {"action_kind", "authorized_amount", "candle_open_ms", "configuration_digest", "instance_key", "runtime_contract_version", "side", "unit"})
        self.assertEqual((payload["action_kind"], payload["side"], payload["unit"], payload["authorized_amount"]), ("EXIT", "SELL", "BASE", "0.123456789"))

    def test_identical_inputs_and_later_evaluation_have_identical_records(self):
        self.assertEqual(plan(), plan())
        self.assertEqual(plan(now=HOUR + 1), plan(now=HOUR + 1000))

    def test_identity_changes_only_for_canonical_intent_changes(self):
        initial = plan().action.logical_action_id
        variants = (
            plan(canonical(time=HOUR), checkpoint(now=2 * HOUR, last_processed_candle_ms=0), now=2 * HOUR),
            plan(config=replace(configuration(), buy_quote_budget=D("20"))),
            plan(canonical("LONG_EXIT", 0), checkpoint(RuntimeState.LONG, quantity="10.123456789")),
            plan(config=replace(configuration(), configuration_digest="e" * 64)),
            plan(config=replace(configuration(), account_binding="other-profile")),
            plan(config=replace(configuration(), bot_id="otherbot")),
        )
        self.assertEqual(len({initial, *(result.action.logical_action_id for result in variants)}), 7)

    def test_maximum_bot_id_produces_36_character_link(self):
        config = replace(configuration(), bot_id="abcdefghijkl")
        action = plan(config=config).action
        self.assertEqual(len(action.order_link_id), 36)
        self.assertEqual(action.order_link_id, config.bot_id + "-" + action.logical_action_id[:23])

    def test_canonical_decimal_equivalence_and_small_context(self):
        with localcontext() as context:
            context.prec = 2
            first = plan(config=replace(configuration(), buy_quote_budget=D("10.123456789000")))
            second = plan()
            self.assertEqual(first, second)
            self.assertEqual(first.action.authorized_amount, D("10.123456789"))
        plain = module._canonical_intent(configuration(), canonical(), JournalActionKind.ENTRY, D("1E+3"))
        self.assertIn(b'"authorized_amount":"1000"', plain)

    def test_decision_availability_boundary_is_inclusive(self):
        self.assertIs(plan(now=HOUR).kind, PlanKind.PLACE_BUY)
        result = plan(cp=checkpoint(now=HOUR - 1), now=HOUR - 1)
        self.assertIs(result.kind, PlanKind.WAIT)
        self.assertIsNone(result.action)
        self.assertIsNone(result.decision)

    def test_decision_age_boundary_and_stale_entry_refusal(self):
        maximum = configuration().decision_max_age_ms
        self.assertIs(plan(cp=checkpoint(now=HOUR + maximum), now=HOUR + maximum).kind, PlanKind.PLACE_BUY)
        stale = plan(cp=checkpoint(now=HOUR + maximum + 1), now=HOUR + maximum + 1)
        self.assertIs(stale.kind, PlanKind.HALT)
        self.assertIsNone(stale.action)
        self.assertIs(stale.decision.disposition, DecisionDisposition.HALT)

    def test_stale_satisfied_decision_is_replay_only_not_placement(self):
        now = HOUR + configuration().decision_max_age_ms + 1
        result = plan(canonical("HOLD", 0), checkpoint(now=now), now=now)
        self.assertIs(result.kind, PlanKind.NOOP)
        self.assertIs(result.decision.disposition, DecisionDisposition.REPLAY_ONLY)

    def test_missing_reconciliation_or_observation_requests_reconcile(self):
        for name in ("last_reconciled_at_ms", "observed_at_ms"):
            with self.subTest(name=name):
                result = plan(cp=replace(checkpoint(), **{name: None}))
                self.assertIs(result.kind, PlanKind.RECONCILE)
                self.assertIsNone(result.action)
                self.assertIsNone(result.decision)

    def test_reconciliation_and_observation_age_boundaries(self):
        maximum = configuration().observation_max_age_ms
        for name in ("last_reconciled_at_ms", "observed_at_ms"):
            with self.subTest(name=name):
                self.assertIs(plan(cp=replace(checkpoint(), **{name: HOUR - maximum})).kind, PlanKind.PLACE_BUY)
                result = plan(cp=replace(checkpoint(), **{name: HOUR - maximum - 1}))
                self.assertIs(result.kind, PlanKind.RECONCILE)
                self.assertIsNone(result.action)

    def test_future_reconciliation_or_observation_halts(self):
        for name in ("last_reconciled_at_ms", "observed_at_ms"):
            with self.subTest(name=name):
                result = plan(cp=replace(checkpoint(), **{name: HOUR + 1}))
                self.assertIs(result.kind, PlanKind.HALT)
                self.assertIs(result.reason, RuntimeReason.INVALID_CONFIGURATION)
                self.assertIsNone(result.action)

    def test_stale_reconciliation_overrides_satisfied_hold(self):
        self.assertIs(plan(canonical("HOLD", 0), replace(checkpoint(), observed_at_ms=None)).kind, PlanKind.RECONCILE)

    def test_recovery_deadline_is_exclusive_even_with_longer_decision_freshness(self):
        config = replace(configuration(), reconciliation_timeout_ms=1000, decision_max_age_ms=10000)
        self.assertIs(plan(cp=checkpoint(now=HOUR + 999), config=config, now=HOUR + 999).kind, PlanKind.PLACE_BUY)
        result = plan(cp=checkpoint(now=HOUR + 1000), config=config, now=HOUR + 1000)
        self.assertIs(result.kind, PlanKind.HALT)
        self.assertIs(result.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        self.assertIsNone(result.action)

    def test_historical_modes_never_authorize_despite_desired_mismatch(self):
        for mode, disposition in ((DecisionMode.BOOTSTRAP, DecisionDisposition.BOOTSTRAP), (DecisionMode.REPLAY_ONLY, DecisionDisposition.REPLAY_ONLY)):
            for state in (RuntimeState.FLAT, RuntimeState.LONG):
                for signal, desired in _INTENTS:
                    with self.subTest(mode=mode, state=state, signal=signal, desired=desired):
                        cp = checkpoint(state)
                        result = plan(canonical(signal, desired), cp, mode=mode)
                        self.assertIs(result.kind, PlanKind.NOOP)
                        self.assertIsNone(result.action)
                        self.assertIs(result.decision.disposition, disposition)
                        proposed = proposed_snapshot(cp.snapshot, result)
                        self.assertIs(proposed.state, state)
                        self.assertEqual(proposed.owned_base_quantity, cp.snapshot.owned_base_quantity)
                        self.assertEqual(proposed.desired_position, desired)

    def test_pending_historical_modes_preserve_dispositions_and_original_lifecycle(self):
        cp = checkpoint(RuntimeState.ORDER_PENDING)
        for mode in (DecisionMode.BOOTSTRAP, DecisionMode.REPLAY_ONLY):
            result = plan(canonical("LONG_EXIT", 0), cp, mode=mode)
            self.assertIs(result.kind, PlanKind.WAIT)
            self.assertEqual(result.decision.disposition.value, mode.value)
            self.assertEqual(proposed_snapshot(cp.snapshot, result).pending_action, cp.snapshot.pending_action)
            self.assertIsNone(result.action)

    def test_historical_mode_does_not_bypass_reconciliation_guard(self):
        for mode in (DecisionMode.BOOTSTRAP, DecisionMode.REPLAY_ONLY):
            result = plan(cp=replace(checkpoint(), last_reconciled_at_ms=None), mode=mode)
            self.assertIs(result.kind, PlanKind.RECONCILE)
            self.assertIsNone(result.action)
            self.assertIsNone(result.decision)

    def test_live_cannot_override_durable_bootstrap_or_replay_cutoff(self):
        for name in ("bootstrap_until_ms", "replay_until_ms"):
            with self.subTest(name=name):
                self.assertIs(plan(cp=replace(checkpoint(), **{name: 0})).kind, PlanKind.HALT)

    def test_pending_opposite_intent_does_not_replace_or_cancel(self):
        cp = checkpoint(RuntimeState.ORDER_PENDING)
        result = plan(canonical("LONG_EXIT", 0), cp)
        self.assertIs(result.kind, PlanKind.WAIT)
        self.assertIs(result.decision.disposition, DecisionDisposition.WAIT)
        proposed = proposed_snapshot(cp.snapshot, result)
        self.assertEqual(proposed.pending_action, cp.snapshot.pending_action)
        self.assertEqual(proposed.owned_base_quantity, cp.snapshot.owned_base_quantity)

    def test_prepared_events_are_accepted_by_frozen_state_machine(self):
        for cp, decision, event in ((checkpoint(), canonical(), RuntimeEventType.ENTRY_PREPARED),
                                     (checkpoint(RuntimeState.LONG), canonical("LONG_EXIT", 0), RuntimeEventType.EXIT_PREPARED)):
            result = plan(decision, cp)
            self.assertIs(result.events[0].kind, event)
            proposed = proposed_snapshot(cp.snapshot, result)
            self.assertIs(proposed.state, RuntimeState.ORDER_PENDING)
            self.assertEqual(proposed.pending_action.logical_action_id, result.action.logical_action_id)
            self.assertEqual(proposed.owned_base_quantity, cp.snapshot.owned_base_quantity)

    def test_noop_and_reconcile_events_are_valid_without_mutating_checkpoint(self):
        for state, desired in ((RuntimeState.FLAT, 0), (RuntimeState.LONG, 1)):
            cp = checkpoint(state)
            result = plan(canonical("HOLD", desired), cp)
            self.assertEqual(proposed_snapshot(cp.snapshot, result).state, state)
            stale = plan(cp=replace(cp, observed_at_ms=None))
            self.assertIs(proposed_snapshot(cp.snapshot, stale).state, RuntimeState.SYNCHRONIZING)

    def test_halt_refusal_does_not_unlatch_or_construct_forbidden_event(self):
        for state in (RuntimeState.HALTED, RuntimeState.STOPPING):
            cp = checkpoint(state)
            result = plan(cp=cp)
            self.assertIs(result.kind, PlanKind.HALT)
            self.assertIsNone(result.action)
            self.assertIsNone(result.decision)
            self.assertEqual(result.events, ())

    def test_identical_consumed_history_is_compatible_without_new_authorization(self):
        action = plan().action
        variants = (action,
                    replace(action, phase=ActionPhase.UNKNOWN_OUTCOME, attempt_count=1, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN),
                    replace(action, phase=ActionPhase.TERMINAL_CONFIRMED, attempt_count=1, broker_order_id="order-1", order_status="FILLED", observed_at_ms=HOUR, terminal_at_ms=HOUR))
        for previous in variants:
            with self.subTest(phase=previous.phase):
                result = plan(history=(previous,))
                self.assertIs(result.kind, PlanKind.WAIT)
                self.assertIsNone(result.action)
                self.assertIsNone(result.decision)

    def test_same_id_with_incompatible_authorization_or_deadline_halts(self):
        action = plan().action
        for previous in (replace(action, authorized_amount=D("20")), replace(action, reconciliation_deadline_ms=action.reconciliation_deadline_ms + 1)):
            self.assertIs(plan(history=(previous,)).kind, PlanKind.HALT)

    def test_truncated_link_collision_never_generates_replacement(self):
        action = plan().action
        other_id = action.logical_action_id[:23] + "f" * 41
        other = replace(action, logical_action_id=other_id)
        result = plan(history=(other,))
        self.assertIs(result.kind, PlanKind.HALT)
        self.assertIs(result.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertIsNone(result.action)

    def test_consumed_cancellation_id_cannot_be_reused_for_placement(self):
        action = plan().action
        control = ActionRecord(action.logical_action_id, JournalActionKind.CANCEL, "BTCUSDT",
                               HOUR + 600000, 5, 3, control_id="operator-1",
                               parent_action_id="e" * 64, target_broker_order_id="order-1")
        result = plan(history=(control,))
        self.assertIs(result.kind, PlanKind.HALT)
        self.assertIs(result.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertIsNone(result.action)

    def test_same_candle_different_placement_and_conflicting_history_halt(self):
        action = plan().action
        other = plan(config=replace(configuration(), buy_quote_budget=D("20"))).action
        for history in ((other,), (action, other), (action, replace(action, authorized_amount=D("20")))):
            self.assertIs(plan(history=history).kind, PlanKind.HALT)

    def test_unresolved_other_action_cannot_authorize_a_second_order(self):
        old = plan().action
        decision = canonical(time=HOUR)
        cp = checkpoint(now=2 * HOUR, last_processed_candle_ms=0)
        result = plan(decision, cp, now=2 * HOUR, history=(old,))
        self.assertIs(result.kind, PlanKind.HALT)
        self.assertIsNone(result.action)

    def test_already_handled_candle_and_history_gap_never_authorize(self):
        self.assertIs(plan(cp=checkpoint(last_processed_candle_ms=0)).kind, PlanKind.WAIT)
        missing = plan(canonical(time=HOUR), checkpoint(now=2 * HOUR), now=2 * HOUR)
        self.assertIs(missing.kind, PlanKind.RECONCILE)
        self.assertIsNone(missing.decision)

    def test_wrong_symbol_and_pre_anchor_decision_fail_closed(self):
        self.assertIs(plan(replace(canonical(), symbol="ETHUSDT")).kind, PlanKind.HALT)
        self.assertIs(plan(config=replace(configuration(), history_anchor_ms=HOUR)).kind, PlanKind.HALT)

    def test_invalid_canonical_fields_are_rejected_without_coercion(self):
        variants = ({"timeframe": "5"}, {"candle_open_ms": 1}, {"available_at_ms": HOUR + 1},
                    {"signal": "BUY"}, {"signal": "LONG_ENTRY", "desired_position": 0},
                    {"signal": "LONG_EXIT", "desired_position": 1}, {"desired_position": True},
                    {"desired_position": 1.0}, {"input_fingerprint": "bad"})
        for values in variants:
            with self.subTest(values=values), self.assertRaises(PlannerError):
                replace(canonical(), **values)

    def test_invalid_explicit_time_and_input_record_types_fail_closed(self):
        for now in (True, -1, 1.0, "private-value", None, float("nan"), 2**63):
            with self.subTest(type=type(now)), self.assertRaises(PlannerError) as error:
                plan(now=now)
            self.assertNotIn("private-value", str(error.exception))
        arguments = dict(config=configuration(), checkpoint=checkpoint(), decision=canonical(),
                         evaluated_at_ms=HOUR, mode=DecisionMode.LIVE, action_history=())
        for name, value in (("config", {}), ("checkpoint", {}), ("decision", {}), ("mode", "LIVE"), ("action_history", []), ("action_history", ({},))):
            with self.subTest(name=name), self.assertRaises(PlannerError):
                plan_action(**{**arguments, name: value})

    def test_bypassed_invalid_money_and_snapshot_constructors_are_rejected(self):
        for value in (True, 10.0, D("0"), D("NaN"), D("Infinity"), D("-1")):
            config = configuration()
            object.__setattr__(config, "buy_quote_budget", value)
            with self.subTest(value=value), self.assertRaises(PlannerError):
                plan(config=config)
        for name, value in (("owned_base_quantity", D("1")), ("pending_action", PendingAction(ACTION_ID, PendingActionKind.ENTRY))):
            cp = checkpoint()
            object.__setattr__(cp.snapshot, name, value)
            with self.subTest(name=name), self.assertRaises(PlannerError):
                plan(cp=cp)
        cp = checkpoint()
        object.__setattr__(cp, "snapshot", {})
        with self.assertRaises(PlannerError):
            plan(cp=cp)

    def test_deadline_overflow_fails_without_authorization(self):
        with self.assertRaises(PlannerError):
            plan(config=replace(configuration(), reconciliation_timeout_ms=2**63 - 1))

    def test_result_records_are_frozen_slotted_and_nonplacement_cannot_carry_action(self):
        result, decision = plan(), canonical()
        for record, field, value in ((result, "action", None), (decision, "signal", "HOLD")):
            self.assertFalse(hasattr(record, "__dict__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(record, field, value)
        with self.assertRaises(PlannerError):
            ActionPlan(PlanKind.NOOP, action=result.action)
        with self.assertRaises(PlannerError):
            replace(result, events=())
        with self.assertRaises(PlannerError):
            ActionPlan(PlanKind.NOOP, events=result.events)
        with self.assertRaises(PlannerError):
            replace(result, decision=replace(result.decision, symbol="ETHUSDT"))
        with self.assertRaises(PlannerError):
            replace(result, decision=replace(result.decision, signal="HOLD"))

    def test_input_checkpoint_history_and_configuration_are_preserved(self):
        config, cp, decision = configuration(), checkpoint(), canonical()
        history = (plan().action,)
        before = deepcopy((config, cp, decision, history))
        plan_action(config, cp, decision, evaluated_at_ms=HOUR, mode=DecisionMode.LIVE, action_history=history)
        self.assertEqual((config, cp, decision, history), before)
        self.assertEqual(cp.sequence, 7)
        self.assertIsNone(cp.last_processed_candle_ms)

    def test_structural_boundary_contains_only_pure_record_and_identity_dependencies(self):
        tree = ast.parse(inspect.getsource(module))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertEqual(imports, {"dataclasses", "enum", "hashlib", "json", "state", "store"})
        forbidden = {"RuntimeStore", "ReadOnlyBroker", "AccountState", "CurrencyBalance", "BybitDemoOrderAdapter",
                     "BybitDemoReadOnlyAdapter", "generate_ema_signals", "calculate_position_budget", "position_fraction"}
        self.assertFalse(any(isinstance(node, ast.Name) and node.id in forbidden for node in ast.walk(tree)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"open", "connect", "getenv", "environ", "now", "sleep", "time", "_connection",
                                             "get_account_state", "place_order", "cancel_order", "commit_decision", "start_attempt"})
            self.assertNotIsInstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await))

    def test_planning_performs_no_io_clock_environment_or_store_operation(self):
        calls = ("builtins.open", "os.getenv", "time.time", "time.sleep", "socket.create_connection", "sqlite3.connect")
        for name in calls:
            self.enterContext(patch(name, side_effect=AssertionError("Forbidden external operation")))
        for name in ("get_checkpoint", "get_configuration", "list_actions", "list_fills", "save_checkpoint", "commit_decision", "record_observation", "start_attempt"):
            self.enterContext(patch.object(RuntimeStore, name, side_effect=AssertionError("No store operations")))
        self.assertIs(plan().kind, PlanKind.PLACE_BUY)
        self.assertIs(plan(canonical("LONG_EXIT", 0), checkpoint(RuntimeState.LONG)).kind, PlanKind.PLACE_SELL)
        self.assertEqual(plan(), plan())


class PlannerStoreCompatibilityTests(StoreCase):
    def test_fatal_live_mismatch_records_intent_then_halt_in_one_checkpoint(self):
        self.flat()
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(last_reconciled_at_ms=HOUR, observed_at_ms=HOUR), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        result = plan(canonical("HOLD", 1), current, self.config, history=self.store.list_actions())
        self.assertIs(result.kind, PlanKind.HALT)
        self.assertEqual(tuple(event.kind for event in result.events), (RuntimeEventType.NO_CHANGE, RuntimeEventType.FATAL_INCONSISTENCY))
        snapshot = proposed_snapshot(current.snapshot, result)
        self.assertIs(snapshot.state, RuntimeState.HALTED)
        self.assertEqual(snapshot.desired_position, result.decision.desired_position)
        proposed = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=0,
                           snapshot=snapshot, halted_at_ms=HOUR)
        self.store.commit_decision(candle(), result.decision, proposed, expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), proposed)
        self.assertEqual(self.store.get_decision(0), result.decision)
        self.assertEqual(self.store.list_actions(), ())

    def test_generated_buy_commits_and_reopens_through_frozen_public_apis(self):
        self.flat()
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(last_reconciled_at_ms=HOUR, observed_at_ms=HOUR), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        result = plan(canonical(), current, self.config, history=self.store.list_actions())
        self.assertEqual(self.store.get_checkpoint(), current)  # Planner has no durable effect.
        self.assertEqual(self.store.list_actions(), ())
        proposed = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=0,
                           snapshot=proposed_snapshot(current.snapshot, result))
        self.assertTrue(self.store.commit_decision(candle(), result.decision, proposed, expected_sequence=current.sequence, action=result.action))
        self.assertFalse(self.store.commit_decision(candle(), result.decision, proposed, expected_sequence=current.sequence, action=result.action))
        self.reopen()
        self.assertEqual(self.store.get_action(result.action.logical_action_id), result.action)
        self.assertEqual(self.store.get_decision(0), result.decision)
        self.assertEqual(self.store.get_checkpoint(), proposed)

    def test_generated_sell_preserves_owned_quantity_and_roundtrips(self):
        self.settle(self.acknowledge(), fill())
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(last_reconciled_at_ms=2 * HOUR, observed_at_ms=2 * HOUR), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        result = plan(canonical("LONG_EXIT", 0, HOUR), current, self.config, now=2 * HOUR, history=self.store.list_actions())
        self.assertEqual(result.action.authorized_amount, current.snapshot.owned_base_quantity)
        proposed = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=HOUR,
                           snapshot=proposed_snapshot(current.snapshot, result))
        self.store.commit_decision(candle(HOUR), result.decision, proposed, expected_sequence=current.sequence, action=result.action)
        self.reopen()
        self.assertEqual(self.store.get_action(result.action.logical_action_id), result.action)
        self.assertEqual(self.store.get_decision(HOUR), result.decision)
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, current.snapshot.owned_base_quantity)


if __name__ == "__main__":
    unittest.main()
