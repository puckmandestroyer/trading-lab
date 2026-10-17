"""Closed schemas and deterministic exact encodings; no credentials or network."""

import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import unittest

from trading_lab.observability import *
from trading_lab.observability import model as m
from trading_lab.runtime.store import ActionPhase, JournalActionKind
from trading_lab.runtime.state import RuntimeState as S, RuntimeReason as R, PositionEvidence as P
from trading_lab.risk.runtime_risk import RiskReason, RiskVerdict
from tests import test_runtime_store as fixtures

T = ObservabilityEventType
RUN = "0" * 32
ACTION = "c" * 64
EPOCH = "a" * 64


def sample(kind=T.PROCESS_STARTED, **changes):
    args = dict(run_id=RUN, observed_at_ms=100, details=())
    if kind in m.PROCESS_TYPES:
        args["occurrence_reference"] = "sample"
    details = {
        T.PROCESS_STARTED: (("process_started_at_ms", 0),),
        T.PROCESS_STOPPED: (("process_started_at_ms", 0), ("process_stopped_at_ms", 100), ("stop_reason", "NORMAL")),
        T.SCHEDULER_STARTED: (("scheduler_started_at_ms", 0),),
        T.SCHEDULER_EXITED: (("scheduler_exit_reason", "STOP_REQUESTED"), ("cycle_count", 0), ("wake_count", 0)),
        T.CYCLE_COMPLETED: (("cycle_outcome", "OBSERVED"), ("processed_candle_count", 0), ("processed_candle_open_ms", ()), ("new_execution_ids", ())),
        T.CRITICAL_FAILURE: (("operation", "READ"), ("failure_kind", "IO"), ("exception_type", "OSError")),
        T.OBSERVABILITY_DEGRADED: (("sink", "JSONL"), ("operation", "APPEND"), ("failure_kind", "IO"), ("exception_type", "OSError")),
        T.MARKET_DATA_STALE: (("evidence_kind", "MISSING"),),
        T.RECONCILIATION_DEGRADED: (("evidence_kind", "MISSING"),),
        T.RISK_NOT_READY: (("risk_active", False), ("cycle_outcome", "RISK_NOT_READY")),
        T.RECONCILIATION_CONFIRMED: (("position_evidence", P.CONFIRMED), ("owned_base_quantity", D(0)), ("last_reconciled_at_ms", 1)),
        T.OWNED_EXECUTION_DISCOVERED: (("broker_execution_id", "fill-1"), ("side", "BUY"), ("executed_quantity", D("0.1")), ("execution_price", D(100)), ("execution_fee", D("-0.001")), ("executed_at_ms", 1), ("first_observed_at_ms", 2)),
        T.POSITION_OPEN_CONFIRMED: (("position_evidence", P.CONFIRMED), ("previous_owned_base_quantity", D(0)), ("owned_base_quantity", D("0.1"))),
        T.POSITION_CLOSE_CONFIRMED: (("position_evidence", P.CONFIRMED), ("previous_owned_base_quantity", D("0.1")), ("owned_base_quantity", D(0))),
        T.POSITION_QUANTITY_CHANGED: (("position_evidence", P.CONFIRMED), ("previous_owned_base_quantity", D("0.1")), ("owned_base_quantity", D("0.2"))),
        T.RISK_BLOCKED: (("risk_verdict", RiskVerdict.BLOCK), ("risk_reason", RiskReason.ENTRY_COUNT_LIMIT)),
        T.RISK_TRIPPED: (("tripped_at_ms", 1),),
        T.RISK_REARMED: (("parent_epoch_id", "b"*64), ("child_epoch_id", EPOCH), ("accepted_boundary_ms", 1), ("risk_configuration_digest", "d"*64)),
        T.RUNTIME_HALTED: (("halted_at_ms", 1),),
        T.RUNTIME_UNCERTAIN: (),
        T.RUNTIME_REARMED: (("rearmed_at_ms", 2), ("previous_runtime_state", S.HALTED), ("reconciliation_required", True)),
    }
    if kind in m.ACTION_TYPES:
        phase = m.ACTION_TYPES[kind]
        args.update(action_id=ACTION)
        args["details"] = (("action_kind", JournalActionKind.ENTRY), ("action_phase", phase),
                           ("attempt_count", int(phase not in (ActionPhase.PREPARED, ActionPhase.ABANDONED_UNSENT))),
                           ("side", "BUY"), ("amount_unit", "QUOTE"), ("currency", "USDT"),
                           ("authorized_amount", D(10)), ("order_link_id", "bot1-"+ACTION[:23]))
        if phase is ActionPhase.ACKNOWLEDGED:
            args["broker_order_id"] = "order-1"
            args["details"] += (("submitted_amount", D(10)), ("acknowledgement_broker_ms", 1), ("acknowledgement_observed_ms", 2))
        if phase in (ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT):
            args["details"] += (("terminal_at_ms", 3),)
        if phase is ActionPhase.TERMINAL_CONFIRMED:
            args["broker_order_id"] = "order-1"
            args["details"] += (("order_status", "FILLED"),)
        if phase is ActionPhase.REJECTED:
            args["details"] += (("rejection_code", 10001),)
        if phase is ActionPhase.UNKNOWN_OUTCOME:
            args["details"] += (("safe_reason", R.ACTION_OUTCOME_UNKNOWN),)
    else:
        args["details"] = details[kind]
    if kind in m.POSITION_TYPES or kind in (T.RECONCILIATION_CONFIRMED, T.RUNTIME_UNCERTAIN):
        args["checkpoint_sequence"] = 1
    if kind is T.OWNED_EXECUTION_DISCOVERED:
        args.update(action_id=ACTION, broker_order_id="order-1")
    if kind in (T.RISK_BLOCKED, T.RISK_TRIPPED, T.RISK_REARMED):
        args.update(risk_epoch_id=EPOCH, risk_epoch_sequence=2)
    if kind is T.RISK_BLOCKED:
        args["candle_open_ms"] = 0
    if kind is T.RISK_TRIPPED:
        args["risk_trip_reason"] = RiskReason.DAILY_LOSS_LIMIT
    if kind in (T.RUNTIME_HALTED, T.RUNTIME_UNCERTAIN):
        args.update(runtime_state=S.HALTED if kind is T.RUNTIME_HALTED else S.UNCERTAIN, runtime_reason=R.INCONSISTENT_EVIDENCE)
    if kind is T.RUNTIME_REARMED:
        args["runtime_state"] = S.SYNCHRONIZING
    args.update(changes)
    return make_event(fixtures.configuration(), kind, **args)


class EventModelTests(unittest.TestCase):
    def test_exact_28_types_and_version(self):
        self.assertEqual(len(T), 28)
        self.assertEqual(OBSERVABILITY_CONTRACT_VERSION, 1)
        self.assertEqual(set(T), set(m.PAYLOAD_FIELDS))

    def test_all_types_roundtrip_exact_envelope_allowlist(self):
        self.assertEqual(len(m.ENVELOPE_FIELDS), 24)
        for kind in T:
            with self.subTest(kind=kind):
                event = sample(kind)
                self.assertEqual(event_from_json(event.to_json()), event)
                self.assertEqual(set(event.to_dict()) - set(m.ENVELOPE_FIELDS), {name for name, _ in event.details})

    def test_generic_strategy_ids_roundtrip_process_and_durable_records(self):
        for strategy in ("ema_trend", "donchian", "donchian_breakout", "mean_reversion", "momentum_v2", "a", "x"*32):
            for kind in (T.PROCESS_STARTED, T.POSITION_OPEN_CONFIRMED):
                original = sample(kind)
                with self.subTest(strategy=strategy, kind=kind):
                    event = replace(original, strategy_id=strategy)
                    parsed = event_from_json(m.canonical_bytes({**original.to_dict(), "strategy_id": strategy}))
                    self.assertEqual(parsed, event)
                    self.assertEqual(parsed.strategy_id, strategy)
                    self.assertEqual(parsed.to_json(), event.to_json())
                    self.assertEqual(parsed.event_id, original.event_id)

    def test_unsafe_strategy_ids_rejected_by_record_and_parser(self):
        original = sample()
        for strategy in ("", "EMA Trend", "EMA", "../ema", "ema/trend", " strategy ", "x"*33,
                         "x"*10000, "1strategy", "_strategy", "mean-reversion", "mean.reversion",
                         "ema_trend\n", "ema\x00trend", "\u0435ma_trend", "\uff45ma_trend", None, True, 1, 1.0, [], {}):
            with self.subTest(strategy=strategy):
                with self.assertRaises(ObservabilityValidationError):
                    replace(original, strategy_id=strategy)
                with self.assertRaises(ObservabilityValidationError):
                    event_from_json(m.canonical_bytes({**original.to_dict(), "strategy_id": strategy}))

    def test_generic_strategy_does_not_broaden_broker_or_timeframe(self):
        original = sample()
        for field, value in (("broker_id", "bybit-live"), ("broker_id", "other-demo"),
                             ("timeframe", "5"), ("timeframe", "240")):
            changes = {"strategy_id": "donchian", field: value}
            with self.subTest(field=field, value=value):
                with self.assertRaises(ObservabilityValidationError):
                    replace(original, **changes)
                with self.assertRaises(ObservabilityValidationError):
                    event_from_json(m.canonical_bytes({**original.to_dict(), **changes}))

    def test_future_identity_uses_same_event_schema_without_future_runtime(self):
        # A parser fixture is not a new executable strategy or runtime configuration.
        current = sample()
        identity = dict(bot_id="bot2", symbol="ETHUSDT", base_currency="ETH")
        current_second = make_event(replace(fixtures.configuration(), **identity), T.PROCESS_STARTED,
            run_id=RUN, observed_at_ms=100, occurrence_reference="sample", details=(("process_started_at_ms", 0),))
        encoded = m.canonical_bytes({**current_second.to_dict(), "strategy_id": "donchian"})
        future = event_from_json(encoded)
        self.assertEqual((current.strategy_id, current.symbol, current.bot_id), ("ema_trend", "BTCUSDT", "bot1"))
        self.assertEqual((future.strategy_id, future.symbol, future.bot_id), ("donchian", "ETHUSDT", "bot2"))
        self.assertEqual(type(current), type(future))
        self.assertEqual(set(current.to_dict()), set(future.to_dict()))
        self.assertEqual(future.to_json(), encoded)

    def test_runtime_configuration_still_rejects_future_strategy(self):
        configuration = fixtures.configuration()
        self.assertEqual(configuration.strategy_id, "ema_trend")
        with self.assertRaisesRegex(m.RuntimeStoreError, "Initial runtime strategy must be ema_trend"):
            replace(configuration, strategy_id="donchian")

    def test_pre_correction_ema_event_ids_and_serialization_vectors(self):
        # Captured from frozen 557774a before changing validation, in enum order.
        events = tuple(sample(kind) for kind in T)
        self.assertEqual(tuple(event.event_id for event in events), (
            "24bafafacc84ce52d41f8584edad9f84d2bfdff17566b43ee5f73fdc7d51c922",
            "2b20b8412717ac17943895e7fa181949854c5afd86db15ee1767347661b12503",
            "8b3dcd4defe27457e0b56a0cbc631d93ac54a060768c3405a237824d53cb8be8",
            "9762e3bd0a05ce240111315be43b18a8ae07a5edca09f11c64cdbb376bc76bfd",
            "da20466b91d06c4b7af189b47db426fd707327d88d4a7bc4b7d44ec0df208bcd",
            "758b513b846047470874d2689554977125540d894696f67b716c34a0dcbf552a",
            "8cb1ff5704fe4702d82e3e97440b0fd4fb388fc929db15225e0453e6ad8add7d",
            "f3281001d28f62527acb9432a003833b1d9bd42d4db695fc95518788253af3b3",
            "cbf78faec31246124285731f54c617b4078a6ad7cc2fa98269c8eef3c1b7ea26",
            "5a44c73c9b6918e86f3bf5deba0c44d29943fc11b306b88a74fc63e04832a1e4",
            "5ccf6d603bae0b4ba174294b48cbe2a9e4570163d9d29f08b56511b032f3cf67",
            "c441b4663d52a953ade344f25b13b676bf76c85ace2ef24ba7543e43b8f73b3e",
            "8a3540d57b8b9058f8aa8bfae61643fa7e4788e74f0950221f2e81ffda95a219",
            "aef9680d268d8905ab6dc690315da94561f65bef607bb0b7b6c29f7bff53b48d",
            "11ada375f1f1a89144d36e8a7975d9f33715d4269a58ef4ed3d01b4883537e8e",
            "10a23055e94c70d764dbceb725fd7e0a00ac5e002a95cf971d5ae76b28a42e50",
            "c6f682df27d3e7d7cf536535f234edcd4c90823d4f2d0eb2bca184ad51fd048c",
            "b5bf305dcbbea5ba240a3847d269c1408ab7715615edbeb7bde25396a8a85d8d",
            "49d08474d3bc1856191418f3b03a02b07309c8f125fe0926ab5f3c1c0c36b749",
            "028868f9253bf8eeae73ee8e00874544781c3ba43c1f52375f9fccbf106f1807",
            "fdbad66aca14f48702dc85460a25d4c6363d61f128e11b9b7f91de59300c9f4f",
            "fd811b9422fc178253b21270561ae5dafb223e468877bea0bd3c4f0220bd52d2",
            "a625eaa4b2e4144de9290341da529e4dbbb14df4e93f8ffad4352b939e2e254c",
            "a202437491336710c03399ebf8422ea0c7a1ce995a5f6624aaae0e75117e4702",
            "48b379a1332069016c0a28f1ca0bc141bb0dda8e2c1e04557db7ce4d5239ebfa",
            "ca29f1e4918dd17e6f553be97fdbfb790590c49bae4d43637374663c83f0573f",
            "438cad3a5c759956b49909490d7650ab6b559e13064bfc5aa210e13e79b1dbe8",
            "55d08542e79b42b62325d3e5a60c35bd1a55e61560d169c38ff29abff2c5ffb4",
        ))
        self.assertEqual(hashlib.sha256(b"\n".join(event.to_json() for event in events)).hexdigest(),
                         "3bcf034a4417cd0bb9a432bc2fb91e3997dbecee776498669c03fb80bc8a07bb")

    def test_enums_have_frozen_values(self):
        self.assertEqual([x.value for x in ObservabilitySeverity], ["INFO", "WARNING", "ERROR", "CRITICAL"])
        self.assertEqual([x.value for x in ObservabilityHealthLevel], ["OK", "ATTENTION", "CRITICAL"])
        self.assertEqual([x.value for x in EvidenceFreshness], ["FRESH", "STALE", "UNKNOWN"])

    def test_record_immutable_and_slotted(self):
        event = sample()
        with self.assertRaises(FrozenInstanceError):
            event.summary = "changed"
        self.assertFalse(hasattr(event, "__dict__"))

    def test_exact_signed_fee_and_null_not_zero(self):
        event = sample(T.OWNED_EXECUTION_DISCOVERED)
        self.assertEqual(event.to_dict()["execution_fee"], "-0.001")
        self.assertIsNone(event.to_dict()["occurred_at_ms"])

    def test_decimal_canonical_zero_and_plain_not_exponent(self):
        fields = dict(sample(T.OWNED_EXECUTION_DISCOVERED).details)
        fields.update(execution_fee=D("-0E-10"), execution_price=D("1E3"))
        event = sample(T.OWNED_EXECUTION_DISCOVERED, details=tuple(fields.items()))
        self.assertEqual((event.to_dict()["execution_fee"], event.to_dict()["execution_price"]), ("0", "1000"))

    def test_float_bool_nan_infinite_and_unbounded_financial_rejected(self):
        for value in (1.0, True, "1", D("NaN"), D("Infinity"), D("1E10000")):
            fields = dict(sample(T.OWNED_EXECUTION_DISCOVERED).details)
            fields["execution_price"] = value
            with self.subTest(value=type(value)), self.assertRaises(ObservabilityValidationError):
                sample(T.OWNED_EXECUTION_DISCOVERED, details=tuple(fields.items()))

    def test_required_null_rejected_optional_null_preserved(self):
        with self.assertRaises(ObservabilityValidationError):
            sample(details=(("process_started_at_ms", None),))
        self.assertIsNone(sample(T.CRITICAL_FAILURE, details=(("operation", "READ"), ("failure_kind", "IO"),
            ("exception_type", "OSError"), ("safe_error_code", None))).to_dict()["safe_error_code"])

    def test_every_unsafe_key_rejected(self):
        for key in ("api_key", "api_secret", "token", "telegram_token", "authorization", "cookie", "signature",
                    "headers", "environment", "raw_request", "raw_response", "payload_dump"):
            with self.subTest(key=key), self.assertRaises(ObservabilityValidationError):
                sample(details=(("process_started_at_ms", 0), (key, "synthetic-secret")))

    def test_wrong_event_payload_rejected(self):
        with self.assertRaises(ObservabilityValidationError):
            sample(details=(("process_started_at_ms", 0), ("execution_fee", D(1))))

    def test_duplicates_rejected_in_record_and_json(self):
        with self.assertRaises(ObservabilityValidationError):
            sample(details=(("process_started_at_ms", 0), ("process_started_at_ms", 1)))
        data = sample().to_json()
        with self.assertRaises(ObservabilityValidationError):
            event_from_json(data[:-1] + b',"run_id":"00000000000000000000000000000000"}')

    def test_canonical_json_fixed_process_vector(self):
        event = sample()
        self.assertEqual(event.to_json(), json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
        self.assertEqual(event.event_id, "24bafafacc84ce52d41f8584edad9f84d2bfdff17566b43ee5f73fdc7d51c922")
        reference = {"observability_version": 1, "broker_id": "bybit-demo", "account_binding": "research", "bot_id": "bot1",
                     "event_type": "PROCESS_STARTED", "run_id": RUN, "occurrence_reference": "sample"}
        self.assertEqual(event.event_id, hashlib.sha256(json.dumps(reference, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_durable_id_fixed_vector_and_independent_clock_run(self):
        event = sample(T.ACTION_PREPARED)
        payload = {"observability_version": 1, "broker_id": "bybit-demo", "account_binding": "research", "bot_id": "bot1",
                   "event_type": "ACTION_PREPARED", "durable_reference": {"action_id": ACTION, "phase": "PREPARED"}}
        self.assertEqual(event.event_id, hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(event.event_id, sample(T.ACTION_PREPARED, run_id="1"*32, observed_at_ms=200).event_id)

    def test_process_id_scoped_by_run_and_occurrence(self):
        event = sample()
        self.assertNotEqual(event.event_id, sample(run_id="1"*32).event_id)
        self.assertNotEqual(event.event_id, sample(occurrence_reference="second").event_id)
        self.assertEqual(event.event_id, sample(observed_at_ms=101).event_id)
        self.assertRegex(new_run_id(), r"^[a-f0-9]{32}$")
        self.assertNotEqual(new_run_id(), new_run_id())

    def test_forged_durable_id_rejected(self):
        with self.assertRaises(ObservabilityValidationError):
            replace(sample(T.ACTION_PREPARED), event_id="0"*64)

    def test_invalid_reference_rejected_before_hash_encoding(self):
        for value in (object(), "x"*100000, True):
            with self.subTest(kind="action", value=type(value)), self.assertRaises(ObservabilityValidationError):
                sample(T.ACTION_PREPARED, action_id=value)
            with self.subTest(kind="checkpoint", value=type(value)), self.assertRaises(ObservabilityValidationError):
                sample(T.POSITION_OPEN_CONFIRMED, checkpoint_sequence=value)

    def test_unsafe_summary_raw_exception_not_allowed(self):
        with self.assertRaises(ObservabilityValidationError):
            replace(sample(), summary="Authorization: synthetic-secret")
        with self.assertRaises(ObservabilityValidationError):
            critical_failure(fixtures.configuration(), run_id=RUN, observed_at_ms=1, occurrence_reference="failure",
                operation="READ", failure_kind="IO", exception_type=Exception("synthetic-secret"))

    def test_safe_text_boundaries_and_secret_lookalikes(self):
        event = sample(T.CRITICAL_FAILURE, details=(("operation", "R"*64), ("failure_kind", "IO"), ("exception_type", "OSError")))
        self.assertIn("R"*64, event.to_json().decode())
        for text in ("R"*65, "Authorization: bearer synthetic", "https://synthetic.invalid/token", "line\nbreak", ""):
            with self.subTest(text=text), self.assertRaises(ObservabilityValidationError):
                sample(T.CRITICAL_FAILURE, details=(("operation", text), ("failure_kind", "IO"), ("exception_type", "OSError")))

    def test_identifiers_are_not_blanket_redacted(self):
        event = sample(T.OWNED_EXECUTION_DISCOVERED)
        for text in ("research", "bot1", ACTION, "order-1", "fill-1"):
            self.assertIn(text, event.to_json().decode())

    def test_integer_time_version_types(self):
        for value in (-1, True, 1.0, 2**63):
            with self.subTest(value=value), self.assertRaises(ObservabilityValidationError):
                sample(observed_at_ms=value)
        with self.assertRaises(ObservabilityValidationError):
            replace(sample(), observability_version=True)

    def test_candle_list_and_execution_bounds(self):
        event = sample(T.CYCLE_COMPLETED, details=(("cycle_outcome", "REPLAY_ONLY"),
            ("processed_candle_count", m.MAX_CANDLES), ("processed_candle_open_ms", tuple(range(m.MAX_CANDLES))), ("new_execution_ids", ())))
        self.assertEqual(dict(event.details)["processed_candle_count"], m.MAX_CANDLES)
        for count in (m.MAX_CANDLES+1,):
            with self.assertRaises(ObservabilityValidationError):
                sample(T.CYCLE_COMPLETED, details=(("cycle_outcome", "REPLAY_ONLY"), ("processed_candle_count", count),
                    ("processed_candle_open_ms", tuple(range(count))), ("new_execution_ids", ())))
        ids = tuple("e"+str(n) for n in range(m.MAX_EXECUTIONS))
        m.validate_value("new_execution_ids", ids)
        with self.assertRaises(ObservabilityValidationError):
            m.validate_value("new_execution_ids", ids+("extra",))

    def test_fill_list_bounds_and_closed_members(self):
        fill = (("broker_execution_id", "e1"), ("execution_fee", D("-1")))
        m.validate_value("entry_fills", (fill,)*m.MAX_FILLS)
        with self.assertRaises(ObservabilityValidationError):
            m.validate_value("entry_fills", (fill,)*(m.MAX_FILLS+1))
        with self.assertRaises(ObservabilityValidationError):
            m.validate_value("entry_fills", ((("token", "synthetic"),),))

    def test_event_byte_limit(self):
        fields = dict(sample(T.POSITION_OPEN_CONFIRMED).details)
        fields["entry_fills"] = tuple((("broker_execution_id", "e"+str(i)), ("execution_fee", D("1E1000"))) for i in range(128))
        with self.assertRaises(ObservabilityValidationError):
            sample(T.POSITION_OPEN_CONFIRMED, details=tuple(fields.items()))

    def test_malformed_missing_unknown_and_noncanonical_json(self):
        for data in (b"", b"[]", b"{", b"\xff", b"{\"bad\":NaN}", sample().to_json()+b"\n"):
            with self.subTest(data=data[:20]), self.assertRaises(ObservabilityValidationError):
                event_from_json(data)
        values = sample().to_dict()
        values["unknown"] = 1
        with self.assertRaises(ObservabilityValidationError):
            event_from_json(m.canonical_bytes(values))

    def test_action_phase_and_uncertainty_semantics(self):
        with self.assertRaises(ObservabilityValidationError):
            sample(T.ACTION_PREPARED, details=(("action_kind", JournalActionKind.ENTRY),
                ("action_phase", ActionPhase.ACKNOWLEDGED), ("attempt_count", 1)))
        self.assertIsNone(sample(T.RUNTIME_UNCERTAIN).broker_order_id)

    def test_amount_signs_distinguish_fees_from_quantities(self):
        for name in ("authorized_amount", "submitted_amount", "executed_quantity", "execution_price", "mark_price", "risk_equity"):
            for value in (D(0), D(-1)):
                with self.subTest(name=name, value=value), self.assertRaises(ObservabilityValidationError):
                    m.validate_value(name, value)
        for name in ("execution_fee", "daily_pnl", "realized_trade_pnl_quote"):
            m.validate_value(name, D(-1))
        m.validate_value("owned_base_quantity", D(0))

    def test_ack_without_receipt_and_unknown_without_reason_rejected(self):
        for kind, missing in ((T.ACTION_ACKNOWLEDGED, "acknowledgement_broker_ms"),
                              (T.ACTION_UNKNOWN_OUTCOME, "safe_reason")):
            event = sample(kind)
            with self.subTest(kind=kind), self.assertRaises(ObservabilityValidationError):
                sample(kind, details=tuple(pair for pair in event.details if pair[0] != missing))

    def test_no_network_mutations_private_store_or_object_dump_in_package(self):
        directory = Path(m.__file__).parent
        forbidden_modules = {"requests", "pybit", "socket", "urllib", "http", "streamlit", "plotly", "sqlite3"}
        forbidden_calls = {"place_order", "cancel_order", "amend_order", "replace_order", "run_single_cycle",
            "run_hourly_scheduler", "reconcile_startup", "save_checkpoint", "start_attempt", "asdict", "vars"}
        for file in directory.glob("*.py"):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({x.name.split('.')[0] for x in node.names} & forbidden_modules, file.name)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split('.')[0], forbidden_modules)
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    self.assertNotIn(name, forbidden_calls, (file.name, name))
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, {"_connection", "_transaction", "_risk_rows", "_encode"})
