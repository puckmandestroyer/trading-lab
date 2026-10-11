"""Decision 017 finite-state contract, normalized evidence and purity guards."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import inspect
import unittest
from unittest.mock import patch

import numpy as np

import trading_lab.runtime as runtime
from trading_lab.runtime import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeEvent,
    RuntimeEventType, RuntimeEvidence, RuntimeReason, RuntimeState,
    RuntimeStateError, RuntimeStateSnapshot, transition_runtime_state,
)
import trading_lab.runtime.state as state_module


S, E, P, R = RuntimeState, RuntimeEventType, PositionEvidence, RuntimeReason
ENTRY = PendingAction("a" * 64, PendingActionKind.ENTRY)
EXIT = PendingAction("b" * 64, PendingActionKind.EXIT)
OTHER_ENTRY = PendingAction("c" * 64, PendingActionKind.ENTRY)


def snapshot(state):
    """Fixtures include retained pending work during boot, uncertainty and HALT."""
    if state == S.STARTING:
        return RuntimeStateSnapshot(state, Decimal("0.25"), P.LAST_KNOWN, 1, ENTRY)
    if state == S.SYNCHRONIZING:
        return RuntimeStateSnapshot(state, Decimal("0.25"), P.LAST_KNOWN, 1, ENTRY)
    if state == S.FLAT:
        return RuntimeStateSnapshot(state, Decimal("0"), P.CONFIRMED, 0)
    if state == S.LONG:
        return RuntimeStateSnapshot(state, Decimal("0.25"), P.CONFIRMED, 1)
    if state == S.ORDER_PENDING:
        return RuntimeStateSnapshot(state, Decimal("0.125"), P.CONFIRMED, 1, ENTRY)
    if state in (S.UNCERTAIN, S.HALTED):
        return RuntimeStateSnapshot(state, Decimal("0.125"), P.LAST_KNOWN, 1, ENTRY, R.EVIDENCE_MISSING)
    return RuntimeStateSnapshot(state, Decimal("0.125"), P.LAST_KNOWN, 1, ENTRY, stopped_from=S.ORDER_PENDING)


def event(kind, current):
    """Supply coherent normalized fixtures, independent of the production table."""
    if kind in (E.RECONCILED_FLAT, E.RECONCILED_LONG):
        quantity = Decimal("0") if kind == E.RECONCILED_FLAT else Decimal("0.25")
        terminal = current.pending_action.logical_action_id if current.pending_action else None
        return RuntimeEvent(kind, evidence=RuntimeEvidence(quantity, terminal_action_id=terminal))
    if kind in (E.RECONCILED_PENDING, E.RECOVERY_VALIDATED):
        pending = current.pending_action or ENTRY
        return RuntimeEvent(kind, evidence=RuntimeEvidence(Decimal("0.125"), pending))
    if kind == E.ENTRY_PREPARED:
        return RuntimeEvent(kind, pending_action=OTHER_ENTRY, desired_position=1)
    if kind == E.EXIT_PREPARED:
        return RuntimeEvent(kind, pending_action=EXIT, desired_position=0)
    if kind in (E.PLACEMENT_ACKNOWLEDGED, E.CANCELLATION_ACKNOWLEDGED):
        return RuntimeEvent(kind, pending_action=current.pending_action or ENTRY)
    if kind == E.UNCERTAINTY_DETECTED:
        return RuntimeEvent(kind, reason=R.ACTION_OUTCOME_UNKNOWN)
    if kind == E.FATAL_INCONSISTENCY:
        return RuntimeEvent(kind, reason=R.INCONSISTENT_EVIDENCE)
    return RuntimeEvent(kind)


# Independently specified Decision 017 rows. Acknowledgements are nonterminal
# observations only; STOPPING has no event that can resume the current process.
EXPECTED = {
    S.STARTING: {
        E.STARTUP_VALIDATED: S.SYNCHRONIZING, E.FATAL_INCONSISTENCY: S.HALTED,
        E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.SYNCHRONIZING: {
        E.RECONCILED_FLAT: S.FLAT, E.RECONCILED_LONG: S.LONG,
        E.RECONCILED_PENDING: S.ORDER_PENDING, E.UNCERTAINTY_DETECTED: S.UNCERTAIN,
        E.FATAL_INCONSISTENCY: S.HALTED, E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.FLAT: {
        E.NO_CHANGE: S.FLAT, E.ENTRY_PREPARED: S.ORDER_PENDING,
        E.FRESHNESS_LOST: S.SYNCHRONIZING, E.UNCERTAINTY_DETECTED: S.UNCERTAIN,
        E.FATAL_INCONSISTENCY: S.HALTED, E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.LONG: {
        E.NO_CHANGE: S.LONG, E.EXIT_PREPARED: S.ORDER_PENDING,
        E.FRESHNESS_LOST: S.SYNCHRONIZING, E.UNCERTAINTY_DETECTED: S.UNCERTAIN,
        E.FATAL_INCONSISTENCY: S.HALTED, E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.ORDER_PENDING: {
        E.NO_CHANGE: S.ORDER_PENDING, E.RECONCILED_PENDING: S.ORDER_PENDING,
        E.RECONCILED_FLAT: S.FLAT, E.RECONCILED_LONG: S.LONG,
        E.PLACEMENT_ACKNOWLEDGED: S.ORDER_PENDING, E.CANCELLATION_ACKNOWLEDGED: S.ORDER_PENDING,
        E.UNCERTAINTY_DETECTED: S.UNCERTAIN, E.FATAL_INCONSISTENCY: S.HALTED,
        E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.UNCERTAIN: {
        E.RECOVERY_VALIDATED: S.SYNCHRONIZING, E.RECONCILED_FLAT: S.FLAT,
        E.RECONCILED_LONG: S.LONG, E.RECONCILED_PENDING: S.ORDER_PENDING,
        E.PLACEMENT_ACKNOWLEDGED: S.UNCERTAIN, E.CANCELLATION_ACKNOWLEDGED: S.UNCERTAIN,
        E.UNCERTAINTY_DETECTED: S.UNCERTAIN, E.FATAL_INCONSISTENCY: S.HALTED,
        E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.HALTED: {
        E.NO_CHANGE: S.HALTED, E.OPERATOR_REARMED: S.SYNCHRONIZING,
        E.SHUTDOWN_REQUESTED: S.STOPPING,
    },
    S.STOPPING: {},
}


class RuntimeTransitionMatrixTests(unittest.TestCase):
    """Each of the 8 × 15 pairs is a separately counted unittest."""


def matrix_case(source, kind):
    def test(self):
        current = snapshot(source)
        fact = event(kind, current)
        before = deepcopy((current, fact))
        expected = EXPECTED[source].get(kind)
        if expected is None:
            with self.assertRaises(RuntimeStateError):
                transition_runtime_state(current, fact)
        else:
            result = transition_runtime_state(current, fact)
            self.assertIs(result.state, expected)
            self.assertIsNot(result, current)
            self.assertEqual(result, transition_runtime_state(current, fact))
        self.assertEqual((current, fact), before)
    return test


for source in S:
    for kind in E:
        setattr(RuntimeTransitionMatrixTests, f"test_{source.value.lower()}__{kind.value.lower()}", matrix_case(source, kind))


class RuntimeRecordTests(unittest.TestCase):
    def test_exact_operational_states(self):
        self.assertEqual([state.value for state in S], [
            "STARTING", "SYNCHRONIZING", "FLAT", "LONG", "ORDER_PENDING",
            "UNCERTAIN", "HALTED", "STOPPING",
        ])

    def test_default_startup_quantity_is_unknown_not_zero(self):
        current = RuntimeStateSnapshot()
        self.assertIs(current.state, S.STARTING)
        self.assertIs(current.position_evidence, P.UNKNOWN)
        self.assertIsNone(current.owned_base_quantity)
        self.assertIsNone(current.desired_position)

    def test_all_records_are_frozen_and_slotted(self):
        records = [ENTRY, RuntimeEvidence(Decimal("0")), RuntimeStateSnapshot(), RuntimeEvent(E.NO_CHANGE)]
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
                field = next(iter(record.__dataclass_fields__))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, field, None)

    def test_positive_quantity_cannot_be_flat(self):
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.FLAT), owned_base_quantity=Decimal("0.01"))

    def test_zero_quantity_cannot_be_long(self):
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.LONG), owned_base_quantity=Decimal("0"))

    def test_quantity_requires_decimal_without_coercion(self):
        for quantity in (None, True, False, 0, 1, 0.25, "0.25", complex(1), [], np.float64(.25)):
            with self.subTest(quantity=quantity), self.assertRaises(RuntimeStateError):
                RuntimeEvidence(quantity)
            with self.subTest(snapshot_quantity=quantity), self.assertRaises(RuntimeStateError):
                replace(snapshot(S.LONG), owned_base_quantity=quantity)

    def test_negative_and_nonfinite_quantities_fail(self):
        for quantity in map(Decimal, ("-1", "NaN", "sNaN", "Infinity", "-Infinity")):
            with self.subTest(quantity=str(quantity)), self.assertRaises(RuntimeStateError):
                RuntimeEvidence(quantity)

    def test_exact_genuine_zero_is_accepted(self):
        for quantity in (Decimal("0"), Decimal("-0"), Decimal("0.000")):
            with self.subTest(quantity=quantity):
                self.assertEqual(replace(snapshot(S.FLAT), owned_base_quantity=quantity).owned_base_quantity, 0)

    def test_tiny_positive_quantity_is_not_rounded_to_flat(self):
        tiny = Decimal("1e-1000")
        with localcontext() as context:
            context.prec = 2
            current = replace(snapshot(S.LONG), owned_base_quantity=tiny)
            result = transition_runtime_state(current, RuntimeEvent(E.NO_CHANGE))
        self.assertEqual(result.owned_base_quantity, tiny)
        self.assertIs(result.state, S.LONG)

    def test_quantity_precision_survives_small_decimal_context(self):
        quantity = Decimal("0.12345678901234567890123456789")
        with localcontext() as context:
            context.prec = 2
            result = transition_runtime_state(snapshot(S.SYNCHRONIZING), RuntimeEvent(
                E.RECONCILED_LONG, evidence=RuntimeEvidence(quantity, terminal_action_id=ENTRY.logical_action_id),
            ))
        self.assertEqual(result.owned_base_quantity.as_tuple(), quantity.as_tuple())

    def test_unknown_evidence_requires_none_quantity(self):
        with self.assertRaises(RuntimeStateError):
            RuntimeStateSnapshot(owned_base_quantity=Decimal("0"))
        with self.assertRaises(RuntimeStateError):
            RuntimeStateSnapshot(position_evidence=P.LAST_KNOWN)

    def test_confirmed_evidence_required_for_operational_positions(self):
        for state in (S.FLAT, S.LONG, S.ORDER_PENDING):
            with self.subTest(state=state), self.assertRaises(RuntimeStateError):
                replace(snapshot(state), position_evidence=P.LAST_KNOWN)

    def test_nonoperational_states_cannot_claim_confirmed_current_quantity(self):
        for state in (S.STARTING, S.SYNCHRONIZING, S.UNCERTAIN, S.HALTED, S.STOPPING):
            with self.subTest(state=state), self.assertRaises(RuntimeStateError):
                replace(snapshot(state), position_evidence=P.CONFIRMED)

    def test_flat_and_long_cannot_retain_pending_work(self):
        for state in (S.FLAT, S.LONG):
            with self.subTest(state=state), self.assertRaises(RuntimeStateError):
                replace(snapshot(state), pending_action=ENTRY)

    def test_pending_requires_one_explicit_action(self):
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.ORDER_PENDING), pending_action=None)
        for pending in ([ENTRY], (ENTRY, EXIT), {"id": "a" * 64}, "a" * 64):
            with self.subTest(pending=pending), self.assertRaises(RuntimeStateError):
                replace(snapshot(S.ORDER_PENDING), pending_action=pending)

    def test_pending_supports_zero_and_partial_exposure(self):
        for quantity in (Decimal("0"), Decimal("0.000125")):
            with self.subTest(quantity=quantity):
                self.assertEqual(replace(snapshot(S.ORDER_PENDING), owned_base_quantity=quantity).owned_base_quantity, quantity)

    def test_logical_id_is_validated_but_never_generated(self):
        for value in (None, 1, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + "a" * 63):
            with self.subTest(value=value), self.assertRaises(RuntimeStateError):
                PendingAction(value, PendingActionKind.ENTRY)
        self.assertEqual(ENTRY.logical_action_id, "a" * 64)

    def test_enum_strings_and_other_enums_are_rejected(self):
        constructors = [
            lambda: RuntimeStateSnapshot(state="STARTING"),
            lambda: RuntimeStateSnapshot(state=E.STARTUP_VALIDATED),
            lambda: RuntimeStateSnapshot(position_evidence="UNKNOWN"),
            lambda: PendingAction("a" * 64, "ENTRY"),
            lambda: RuntimeEvent("NO_CHANGE"),
            lambda: replace(snapshot(S.UNCERTAIN), reason="EVIDENCE_MISSING"),
        ]
        for constructor in constructors:
            with self.subTest(constructor=constructor), self.assertRaises(RuntimeStateError):
                constructor()

    def test_desired_position_rejects_bool_float_and_arbitrary_values(self):
        for value in (True, False, np.bool_(True), 1.0, "1", -1, 2, [], Decimal("1")):
            with self.subTest(value=value), self.assertRaises(RuntimeStateError):
                RuntimeStateSnapshot(desired_position=value)
            with self.subTest(event_value=value), self.assertRaises(RuntimeStateError):
                RuntimeEvent(E.NO_CHANGE, desired_position=value)

    def test_desired_position_accepts_unknown_and_existing_integer_convention(self):
        for value in (None, 0, 1, np.int64(1)):
            with self.subTest(value=value):
                self.assertEqual(RuntimeStateSnapshot(desired_position=value).desired_position, value)

    def test_uncertainty_and_halt_require_reason_codes(self):
        for state in (S.UNCERTAIN, S.HALTED):
            with self.subTest(state=state), self.assertRaises(RuntimeStateError):
                replace(snapshot(state), reason=None)

    def test_reasons_are_not_allowed_on_safe_states(self):
        for state in (S.STARTING, S.SYNCHRONIZING, S.FLAT, S.LONG, S.ORDER_PENDING):
            with self.subTest(state=state), self.assertRaises(RuntimeStateError):
                replace(snapshot(state), reason=R.ACTION_OUTCOME_UNKNOWN)

    def test_reason_errors_do_not_echo_arbitrary_sensitive_text(self):
        private = "synthetic-private-sdk-response"
        with self.assertRaises(RuntimeStateError) as caught:
            RuntimeEvent(E.UNCERTAINTY_DETECTED, reason=private)
        self.assertNotIn(private, str(caught.exception))

    def test_stopping_requires_prior_state(self):
        for prior in (None, "LONG", S.STOPPING):
            with self.subTest(prior=prior), self.assertRaises(RuntimeStateError):
                replace(snapshot(S.STOPPING), stopped_from=prior)

    def test_prior_state_belongs_only_to_stopping(self):
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.LONG), stopped_from=S.LONG)

    def test_stopping_cannot_drop_pending_work_or_halt_reason(self):
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.STOPPING), pending_action=None)
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.STOPPING), owned_base_quantity=None, position_evidence=P.UNKNOWN)
        with self.assertRaises(RuntimeStateError):
            RuntimeStateSnapshot(S.STOPPING, stopped_from=S.HALTED)
        with self.assertRaises(RuntimeStateError):
            replace(snapshot(S.STOPPING), reason=R.ACTION_OUTCOME_UNKNOWN)

    def test_stopping_quantity_must_match_prior_flat_or_long(self):
        for prior, quantity in ((S.FLAT, Decimal("1")), (S.LONG, Decimal("0")), (S.LONG, None)):
            evidence = P.UNKNOWN if quantity is None else P.LAST_KNOWN
            with self.subTest(prior=prior, quantity=quantity), self.assertRaises(RuntimeStateError):
                RuntimeStateSnapshot(S.STOPPING, quantity, evidence, stopped_from=prior)

    def test_evidence_cannot_retain_and_terminate_same_lifecycle(self):
        with self.assertRaises(RuntimeStateError):
            RuntimeEvidence(Decimal("0"), ENTRY, ENTRY.logical_action_id)

    def test_event_required_payload_is_explicit(self):
        for kind in (E.RECONCILED_FLAT, E.RECONCILED_LONG, E.RECONCILED_PENDING,
                     E.RECOVERY_VALIDATED, E.ENTRY_PREPARED, E.EXIT_PREPARED,
                     E.PLACEMENT_ACKNOWLEDGED, E.CANCELLATION_ACKNOWLEDGED,
                     E.UNCERTAINTY_DETECTED, E.FATAL_INCONSISTENCY):
            with self.subTest(kind=kind), self.assertRaises(RuntimeStateError):
                RuntimeEvent(kind)

    def test_event_rejects_unrelated_payload(self):
        constructors = [
            lambda: RuntimeEvent(E.SHUTDOWN_REQUESTED, desired_position=0),
            lambda: RuntimeEvent(E.NO_CHANGE, pending_action=ENTRY),
            lambda: RuntimeEvent(E.STARTUP_VALIDATED, evidence=RuntimeEvidence(Decimal("0"))),
            lambda: RuntimeEvent(E.PLACEMENT_ACKNOWLEDGED, pending_action=ENTRY, evidence=RuntimeEvidence(Decimal("1"))),
            lambda: RuntimeEvent(E.OPERATOR_REARMED, reason=R.EVIDENCE_MISSING),
        ]
        for constructor in constructors:
            with self.subTest(constructor=constructor), self.assertRaises(RuntimeStateError):
                constructor()

    def test_prepared_action_requires_matching_kind_and_canonical_intent(self):
        for kind, pending, desired in (
            (E.ENTRY_PREPARED, EXIT, 1), (E.EXIT_PREPARED, ENTRY, 0),
            (E.ENTRY_PREPARED, ENTRY, 0), (E.EXIT_PREPARED, EXIT, 1),
            (E.ENTRY_PREPARED, ENTRY, None), (E.EXIT_PREPARED, EXIT, None),
        ):
            with self.subTest(kind=kind, pending=pending, desired=desired), self.assertRaises(RuntimeStateError):
                RuntimeEvent(kind, pending_action=pending, desired_position=desired)

    def test_raw_mapping_is_not_reconciliation_evidence(self):
        with self.assertRaises(RuntimeStateError):
            RuntimeEvent(E.RECONCILED_FLAT, evidence={"qty": "0", "status": "Filled"})


class RuntimeEvidenceTransitionTests(unittest.TestCase):
    def test_desired_long_does_not_establish_owned_long(self):
        result = transition_runtime_state(snapshot(S.FLAT), RuntimeEvent(E.NO_CHANGE, desired_position=1))
        self.assertIs(result.state, S.FLAT)
        self.assertEqual((result.desired_position, result.owned_base_quantity), (1, Decimal("0")))

    def test_desired_flat_does_not_liquidate_owned_long(self):
        result = transition_runtime_state(snapshot(S.LONG), RuntimeEvent(E.NO_CHANGE, desired_position=0))
        self.assertIs(result.state, S.LONG)
        self.assertEqual((result.desired_position, result.owned_base_quantity), (0, Decimal("0.25")))

    def test_prepared_entry_is_pending_without_a_fill(self):
        result = transition_runtime_state(snapshot(S.FLAT), RuntimeEvent(E.ENTRY_PREPARED, pending_action=ENTRY, desired_position=1))
        self.assertIs(result.state, S.ORDER_PENDING)
        self.assertEqual(result.owned_base_quantity, 0)
        self.assertEqual(result.pending_action, ENTRY)

    def test_prepared_exit_keeps_owned_quantity(self):
        result = transition_runtime_state(snapshot(S.LONG), RuntimeEvent(E.EXIT_PREPARED, pending_action=EXIT, desired_position=0))
        self.assertIs(result.state, S.ORDER_PENDING)
        self.assertEqual(result.owned_base_quantity, Decimal("0.25"))
        self.assertEqual(result.pending_action, EXIT)

    def test_placement_acknowledgement_does_not_establish_long(self):
        current = replace(snapshot(S.ORDER_PENDING), owned_base_quantity=Decimal("0"))
        result = transition_runtime_state(current, RuntimeEvent(E.PLACEMENT_ACKNOWLEDGED, pending_action=ENTRY))
        self.assertEqual(result, current)
        self.assertIs(result.state, S.ORDER_PENDING)

    def test_cancel_acknowledgement_does_not_establish_flat_or_clear_work(self):
        current = snapshot(S.ORDER_PENDING)
        result = transition_runtime_state(current, RuntimeEvent(E.CANCELLATION_ACKNOWLEDGED, pending_action=ENTRY))
        self.assertEqual(result, current)
        self.assertIsNotNone(result.pending_action)

    def test_acknowledgement_does_not_recover_uncertainty(self):
        for kind in (E.PLACEMENT_ACKNOWLEDGED, E.CANCELLATION_ACKNOWLEDGED):
            with self.subTest(kind=kind):
                current = snapshot(S.UNCERTAIN)
                self.assertEqual(transition_runtime_state(current, RuntimeEvent(kind, pending_action=ENTRY)), current)

    def test_acknowledgement_cannot_adopt_an_unknown_or_different_action(self):
        for current in (snapshot(S.ORDER_PENDING), replace(snapshot(S.UNCERTAIN), pending_action=None)):
            with self.subTest(current=current), self.assertRaises(RuntimeStateError):
                transition_runtime_state(current, RuntimeEvent(E.PLACEMENT_ACKNOWLEDGED, pending_action=OTHER_ENTRY))

    def test_pending_intent_change_does_not_queue_replacement(self):
        current = snapshot(S.ORDER_PENDING)
        result = transition_runtime_state(current, RuntimeEvent(E.NO_CHANGE, desired_position=0))
        self.assertIs(result.state, S.ORDER_PENDING)
        self.assertEqual(result.pending_action, current.pending_action)
        self.assertEqual(result.owned_base_quantity, current.owned_base_quantity)
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(result, RuntimeEvent(E.EXIT_PREPARED, pending_action=EXIT, desired_position=0))

    def test_same_action_cannot_be_prepared_twice_while_pending(self):
        current = transition_runtime_state(snapshot(S.FLAT), RuntimeEvent(E.ENTRY_PREPARED, pending_action=ENTRY, desired_position=1))
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(current, RuntimeEvent(E.ENTRY_PREPARED, pending_action=ENTRY, desired_position=1))

    def test_partial_fill_updates_exposure_but_retains_pending_identity(self):
        result = transition_runtime_state(snapshot(S.ORDER_PENDING), RuntimeEvent(
            E.RECONCILED_PENDING, evidence=RuntimeEvidence(Decimal("0.000123"), ENTRY),
        ))
        self.assertIs(result.state, S.ORDER_PENDING)
        self.assertEqual((result.owned_base_quantity, result.pending_action), (Decimal("0.000123"), ENTRY))

    def test_terminal_partial_buy_establishes_smaller_long(self):
        result = transition_runtime_state(snapshot(S.ORDER_PENDING), RuntimeEvent(
            E.RECONCILED_LONG, evidence=RuntimeEvidence(Decimal("0.000123"), terminal_action_id=ENTRY.logical_action_id),
        ))
        self.assertIs(result.state, S.LONG)
        self.assertIsNone(result.pending_action)
        self.assertEqual(result.owned_base_quantity, Decimal("0.000123"))

    def test_terminal_partial_sell_retains_long_remainder(self):
        current = replace(snapshot(S.ORDER_PENDING), pending_action=EXIT, desired_position=0)
        result = transition_runtime_state(current, RuntimeEvent(
            E.RECONCILED_LONG, evidence=RuntimeEvidence(Decimal("0.000001"), terminal_action_id=EXIT.logical_action_id),
        ))
        self.assertIs(result.state, S.LONG)
        self.assertEqual(result.owned_base_quantity, Decimal("0.000001"))
        self.assertEqual(result.desired_position, 0)

    def test_terminal_sell_establishes_flat_only_with_exact_zero(self):
        current = replace(snapshot(S.ORDER_PENDING), pending_action=EXIT)
        result = transition_runtime_state(current, RuntimeEvent(
            E.RECONCILED_FLAT, evidence=RuntimeEvidence(Decimal("0"), terminal_action_id=EXIT.logical_action_id),
        ))
        self.assertIs(result.state, S.FLAT)
        self.assertIsNone(result.pending_action)

    def test_clearing_pending_requires_its_exact_terminal_identity(self):
        for state in (S.SYNCHRONIZING, S.ORDER_PENDING, S.UNCERTAIN):
            for terminal in (None, OTHER_ENTRY.logical_action_id):
                with self.subTest(state=state, terminal=terminal), self.assertRaises(RuntimeStateError):
                    transition_runtime_state(snapshot(state), RuntimeEvent(
                        E.RECONCILED_FLAT, evidence=RuntimeEvidence(Decimal("0"), terminal_action_id=terminal),
                    ))

    def test_terminal_identity_cannot_claim_an_untracked_action(self):
        current = RuntimeStateSnapshot(S.SYNCHRONIZING)
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(current, RuntimeEvent(
                E.RECONCILED_FLAT, evidence=RuntimeEvidence(Decimal("0"), terminal_action_id=ENTRY.logical_action_id),
            ))

    def test_recovery_cannot_replace_pending_identity_or_kind(self):
        for pending in (OTHER_ENTRY, PendingAction(ENTRY.logical_action_id, PendingActionKind.EXIT)):
            for kind in (E.RECONCILED_PENDING, E.RECOVERY_VALIDATED):
                with self.subTest(pending=pending, kind=kind), self.assertRaises(RuntimeStateError):
                    transition_runtime_state(snapshot(S.UNCERTAIN), RuntimeEvent(kind, evidence=RuntimeEvidence(Decimal("0.1"), pending)))

    def test_pending_reconciliation_cannot_omit_action(self):
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(RuntimeStateSnapshot(S.SYNCHRONIZING), RuntimeEvent(
                E.RECONCILED_PENDING, evidence=RuntimeEvidence(Decimal("0")),
            ))

    def test_terminal_event_cannot_retain_pending_action(self):
        for kind in (E.RECONCILED_FLAT, E.RECONCILED_LONG):
            with self.subTest(kind=kind), self.assertRaises(RuntimeStateError):
                transition_runtime_state(snapshot(S.ORDER_PENDING), RuntimeEvent(kind, evidence=RuntimeEvidence(Decimal("0.1"), ENTRY)))

    def test_confirmed_event_and_quantity_must_agree(self):
        for kind, quantity in ((E.RECONCILED_FLAT, Decimal("0.1")), (E.RECONCILED_LONG, Decimal("0"))):
            with self.subTest(kind=kind), self.assertRaises(RuntimeStateError):
                transition_runtime_state(RuntimeStateSnapshot(S.SYNCHRONIZING), RuntimeEvent(kind, evidence=RuntimeEvidence(quantity)))

    def test_complete_evidence_recovers_previously_unknown_quantity(self):
        current = RuntimeStateSnapshot(S.UNCERTAIN, reason=R.EVIDENCE_MISSING)
        for kind, evidence, target in (
            (E.RECONCILED_FLAT, RuntimeEvidence(Decimal("0")), S.FLAT),
            (E.RECONCILED_LONG, RuntimeEvidence(Decimal("0.1")), S.LONG),
            (E.RECONCILED_PENDING, RuntimeEvidence(Decimal("0"), ENTRY), S.ORDER_PENDING),
        ):
            with self.subTest(kind=kind):
                result = transition_runtime_state(current, RuntimeEvent(kind, evidence=evidence))
                self.assertIs(result.state, target)
                self.assertIs(result.position_evidence, P.CONFIRMED)
                self.assertIsNone(result.reason)

    def test_recovery_to_synchronization_still_requires_complete_evidence(self):
        result = transition_runtime_state(snapshot(S.UNCERTAIN), RuntimeEvent(
            E.RECOVERY_VALIDATED, evidence=RuntimeEvidence(Decimal("0.1"), ENTRY),
        ))
        self.assertIs(result.state, S.SYNCHRONIZING)
        self.assertIs(result.position_evidence, P.LAST_KNOWN)
        self.assertEqual(result.pending_action, ENTRY)
        self.assertIsNone(result.reason)

    def test_uncertainty_retains_quantity_only_as_last_known(self):
        current = snapshot(S.ORDER_PENDING)
        result = transition_runtime_state(current, RuntimeEvent(E.UNCERTAINTY_DETECTED, reason=R.ACTION_OUTCOME_UNKNOWN))
        self.assertIs(result.position_evidence, P.LAST_KNOWN)
        self.assertEqual((result.owned_base_quantity, result.pending_action), (current.owned_base_quantity, ENTRY))

    def test_freshness_loss_demotes_confirmed_exposure(self):
        result = transition_runtime_state(snapshot(S.LONG), RuntimeEvent(E.FRESHNESS_LOST))
        self.assertIs(result.state, S.SYNCHRONIZING)
        self.assertIs(result.position_evidence, P.LAST_KNOWN)
        self.assertEqual(result.owned_base_quantity, Decimal("0.25"))

    def test_exhausted_recovery_is_explicit_halt_not_an_implicit_clock(self):
        result = transition_runtime_state(snapshot(S.UNCERTAIN), RuntimeEvent(E.FATAL_INCONSISTENCY, reason=R.RECOVERY_EXHAUSTED))
        self.assertIs(result.state, S.HALTED)
        self.assertIs(result.reason, R.RECOVERY_EXHAUSTED)
        self.assertEqual(result.pending_action, ENTRY)

    def test_halt_remains_latched(self):
        current = snapshot(S.HALTED)
        self.assertEqual(transition_runtime_state(current, RuntimeEvent(E.NO_CHANGE)), current)
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(current, RuntimeEvent(E.NO_CHANGE, desired_position=1))

    def test_explicit_rearm_only_enters_synchronization_and_keeps_work(self):
        current = snapshot(S.HALTED)
        result = transition_runtime_state(current, RuntimeEvent(E.OPERATOR_REARMED))
        self.assertIs(result.state, S.SYNCHRONIZING)
        self.assertEqual(result.pending_action, current.pending_action)
        self.assertEqual(result.owned_base_quantity, current.owned_base_quantity)
        self.assertIs(result.position_evidence, P.LAST_KNOWN)
        self.assertIsNone(result.reason)

    def test_shutdown_preserves_prior_state_reason_quantity_and_work(self):
        for source in S:
            if source == S.STOPPING:
                continue
            with self.subTest(source=source):
                current = snapshot(source)
                result = transition_runtime_state(current, RuntimeEvent(E.SHUTDOWN_REQUESTED))
                self.assertIs(result.state, S.STOPPING)
                self.assertIs(result.stopped_from, source)
                self.assertEqual((result.owned_base_quantity, result.pending_action, result.reason, result.desired_position),
                                 (current.owned_base_quantity, current.pending_action, current.reason, current.desired_position))
                self.assertIs(result.position_evidence, P.LAST_KNOWN)

    def test_shutdown_preserves_unknown_quantity_without_inventing_zero(self):
        result = transition_runtime_state(RuntimeStateSnapshot(), RuntimeEvent(E.SHUTDOWN_REQUESTED))
        self.assertIsNone(result.owned_base_quantity)
        self.assertIs(result.position_evidence, P.UNKNOWN)

    def test_bootstrap_claim_cannot_skip_synchronization(self):
        current = snapshot(S.STARTING)
        result = transition_runtime_state(current, RuntimeEvent(E.STARTUP_VALIDATED))
        self.assertIs(result.state, S.SYNCHRONIZING)
        self.assertIs(result.position_evidence, P.LAST_KNOWN)
        with self.assertRaises(RuntimeStateError):
            transition_runtime_state(current, event(E.RECONCILED_LONG, current))

    def test_closed_lifecycle_sequence_uses_evidence_not_receipts(self):
        current = transition_runtime_state(RuntimeStateSnapshot(), RuntimeEvent(E.STARTUP_VALIDATED))
        current = transition_runtime_state(current, RuntimeEvent(E.RECONCILED_FLAT, evidence=RuntimeEvidence(Decimal("0"))))
        current = transition_runtime_state(current, RuntimeEvent(E.ENTRY_PREPARED, pending_action=ENTRY, desired_position=1))
        current = transition_runtime_state(current, RuntimeEvent(E.PLACEMENT_ACKNOWLEDGED, pending_action=ENTRY))
        self.assertEqual(current.owned_base_quantity, 0)
        current = transition_runtime_state(current, RuntimeEvent(E.RECONCILED_LONG, evidence=RuntimeEvidence(Decimal("0.123"), terminal_action_id=ENTRY.logical_action_id)))
        current = transition_runtime_state(current, RuntimeEvent(E.EXIT_PREPARED, pending_action=EXIT, desired_position=0))
        current = transition_runtime_state(current, RuntimeEvent(E.CANCELLATION_ACKNOWLEDGED, pending_action=EXIT))
        self.assertEqual(current.owned_base_quantity, Decimal("0.123"))
        current = transition_runtime_state(current, RuntimeEvent(E.RECONCILED_FLAT, evidence=RuntimeEvidence(Decimal("0"), terminal_action_id=EXIT.logical_action_id)))
        self.assertIs(current.state, S.FLAT)
        self.assertIsNone(current.pending_action)

    def test_invalid_function_inputs_raise_explicit_errors(self):
        for current, fact in ((S.FLAT, RuntimeEvent(E.NO_CHANGE)), (snapshot(S.FLAT), "NO_CHANGE"), (None, None)):
            with self.subTest(current=current, fact=fact), self.assertRaises(RuntimeStateError):
                transition_runtime_state(current, fact)


class RuntimePurityTests(unittest.TestCase):
    def test_only_lightweight_stdlib_imports_and_local_state_exports(self):
        tree = ast.parse(inspect.getsource(state_module))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"dataclasses", "decimal", "enum", "numbers", "types"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        package = ast.parse(inspect.getsource(runtime))
        self.assertEqual([(node.module, node.level) for node in ast.walk(package) if isinstance(node, ast.ImportFrom)], [("state", 1)])

    def test_no_external_dispatch_clock_execution_or_persistence_calls(self):
        tree = ast.parse(inspect.getsource(state_module))
        # Attribute calls are Decimal validation, read-only mapping lookup, or
        # adding a field name to a local validation set; never external dispatch.
        forbidden = {"open", "exec", "eval", "__import__", "print", "input", "compile"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "add":
                        self.assertIsInstance(node.func.value, ast.Name)
                        self.assertEqual(node.func.value.id, "allowed")
                    else:
                        self.assertIn(node.func.attr, {"is_finite", "get"})
                elif isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden)
            self.assertNotIsInstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await))

    def test_normal_transitions_do_not_touch_io_environment_or_clock(self):
        current = snapshot(S.FLAT)
        fact = RuntimeEvent(E.ENTRY_PREPARED, pending_action=ENTRY, desired_position=1)
        calls = ["builtins.open", "os.getenv", "time.time", "time.sleep", "socket.create_connection", "sqlite3.connect"]
        with self.subTest(operation="pure entry"):
            for name in calls:
                self.enterContext(patch(name, side_effect=AssertionError("Forbidden external operation")))
            result = transition_runtime_state(current, fact)
            self.assertIs(result.state, S.ORDER_PENDING)
            self.assertEqual(result, transition_runtime_state(current, fact))

    def test_public_api_contains_records_events_and_transition_only(self):
        self.assertEqual(set(runtime.__all__), {
            "PendingAction", "PendingActionKind", "PositionEvidence", "RuntimeEvent", "RuntimeEventType",
            "RuntimeEvidence", "RuntimeReason", "RuntimeState", "RuntimeStateError",
            "RuntimeStateSnapshot", "transition_runtime_state",
        })
        self.assertFalse(any(name in vars(state_module) for name in (
            "ActionPhase", "OrderStatus", "place_order", "cancel_order", "RuntimeActionPlanner", "sqlite3", "pybit",
        )))


if __name__ == "__main__":
    unittest.main()
