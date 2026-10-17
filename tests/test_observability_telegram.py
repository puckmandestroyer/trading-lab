"""Synthetic credentials, fake HTTP only, private temporary receipt files."""

import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import errno
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import requests

from trading_lab.observability import ObservabilityStorage, process_started
from trading_lab.observability import telegram as t
from trading_lab.observability.telegram import *
from tests import test_observability_model as event_fixtures
from tests import test_runtime_store as store_fixtures
from tests import test_runtime_integration_regression as golden_fixtures

TOKEN = "123456:FAKE_SECRET_TOKEN_FOR_TESTING_ONLY"
CHAT = "-1007654321099"
RUN = "0" * 32
T = event_fixtures.T
S = TelegramDeliveryStatus


class Raw:
    def __init__(self, data):
        self.data, self.read_sizes = data, []

    def read(self, size, *, decode_content):
        self.read_sizes.append(size)
        if isinstance(self.data, BaseException):
            raise self.data
        return self.data[:size]


class Response:
    def __init__(self, status=200, body=None, *, raw=None):
        self.status_code = status
        self.raw = Raw(json.dumps({"ok": True, "result": {"message_id": 123}} if body is None else body).encode() if raw is None else raw)
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession(requests.Session):
    """Requests configuration surface, with post replaced before any send."""
    def __init__(self, *responses):
        super().__init__()
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))  # Test-only inspection of required URL/body.
        if not self.responses:
            raise AssertionError("No scripted HTTP response")
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class Crash(BaseException):
    """A process disappears; component code must not catch BaseException."""


def sample(kind=T.PROCESS_STARTED, **values):
    return event_fixtures.sample(kind, **values)


class TelegramCase(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.config = store_fixtures.configuration()
        self.storage = ObservabilityStorage(Path(self.temp).resolve()/"observability", self.config)
        self.receipts = TelegramDeliveryStore(self.storage, CHAT)
        self.sleeps = []
        # No accidental path through real requests, sockets, credentials or sleeps.
        for target in ("requests.Session.send", "socket.create_connection", "socket.socket.connect", "os.getenv", "time.sleep"):
            self.enterContext(patch(target, side_effect=AssertionError("Offline tests only")))

    def transport(self, *responses, chat=CHAT, token=TOKEN):
        self.session = self.enterContext(FakeSession(*(responses or (Response(),))))
        return TelegramHttpTransport(token, chat, session=self.session, sleeper=self.sleeps.append)

    def deliver(self, event=None, *responses, **changes):
        transport = self.transport(*responses)
        return deliver_telegram_event(event or sample(), transport, self.receipts, utc_now_ms=lambda: 4567, **changes)

    def path(self, event=None):
        return self.receipts.directory / ((event or sample()).event_id + ".json")


class PolicyAndFormatTests(unittest.TestCase):
    def test_exact_ten_default_types(self):
        expected = {T.PROCESS_STARTED, T.PROCESS_STOPPED, T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED,
            T.RISK_TRIPPED, T.RUNTIME_HALTED, T.RUNTIME_UNCERTAIN, T.RUNTIME_REARMED, T.RISK_REARMED, T.CRITICAL_FAILURE}
        self.assertEqual(TELEGRAM_ALERT_EVENT_TYPES, expected)
        self.assertIs(type(TELEGRAM_ALERT_EVENT_TYPES), frozenset)
        for kind in T:
            self.assertEqual(is_telegram_alert_event(sample(kind)), kind in expected)

    def test_exact_messages_for_all_ten_alerts(self):
        expected = {
            T.PROCESS_STARTED: ("Trading Lab started", []),
            T.PROCESS_STOPPED: ("Trading Lab stopped", ["Stop reason: NORMAL"]),
            T.POSITION_OPEN_CONFIRMED: ("Confirmed position opened", ["Previous base quantity: 0", "Owned base quantity: 0.1", "Exposure confirmed; order may still be pending."]),
            T.POSITION_CLOSE_CONFIRMED: ("Confirmed position closed", ["Previous base quantity: 0.1", "Owned base quantity: 0"]),
            T.RISK_TRIPPED: ("Risk tripped", ["Trip reason: DAILY_LOSS_LIMIT", "Risk epoch: "+"a"*64, "Trip time: 1970-01-01 00:00:00.001 UTC"]),
            T.RUNTIME_HALTED: ("Runtime halted", ["Runtime state: HALTED", "Runtime reason: INCONSISTENT_EVIDENCE", "Halt time: 1970-01-01 00:00:00.001 UTC"]),
            T.RUNTIME_UNCERTAIN: ("Runtime uncertain", ["Runtime state: UNCERTAIN", "Order/action outcome may be unknown. Operator review required.", "Runtime reason: INCONSISTENT_EVIDENCE"]),
            T.RUNTIME_REARMED: ("Runtime rearm accepted", ["Runtime state: SYNCHRONIZING", "Reconciliation still required.", "Rearm time: 1970-01-01 00:00:00.002 UTC"]),
            T.RISK_REARMED: ("Risk rearm accepted", ["Parent epoch: "+"b"*64, "Child epoch: "+"a"*64, "Accepted boundary: 1970-01-01 00:00:00.001 UTC", "Book and capital allocation are unchanged."]),
            T.CRITICAL_FAILURE: ("Critical runtime failure", ["Operation: READ", "Failure kind: IO", "Exception type: OSError"]),
        }
        for kind, (title, detail) in expected.items():
            with self.subTest(kind=kind):
                event = sample(kind)
                severity = "CRITICAL" if kind in (T.RUNTIME_HALTED,T.CRITICAL_FAILURE) else "ERROR" if kind is T.RUNTIME_UNCERTAIN else "WARNING" if kind is T.RISK_TRIPPED else "INFO"
                lines = [title, "Severity: "+severity, "Bot: bot1", "Symbol: BTCUSDT", "Event time: unavailable", "Observed: 1970-01-01 00:00:00.100 UTC", *detail, "Event: "+event.event_id[:12]]
                self.assertEqual(render_telegram_message(event), "\n".join(lines))
                self.assertNotIn(TOKEN,render_telegram_message(event))
                self.assertNotIn(CHAT,render_telegram_message(event))

    def test_occurrence_time_and_observation_are_distinct(self):
        text = render_telegram_message(sample(occurred_at_ms=1))
        self.assertIn("Event time: 1970-01-01 00:00:00.001 UTC", text)
        self.assertNotIn("Observed:", text)

    def test_close_absent_pnl_never_invented_zero(self):
        text = render_telegram_message(sample(T.POSITION_CLOSE_CONFIRMED))
        self.assertNotIn("PnL", text)
        self.assertIn("Owned base quantity: 0", text)

    def test_close_exact_pnl_and_zero_if_actually_supplied(self):
        event = sample(T.POSITION_CLOSE_CONFIRMED)
        for value, expected in ((D("-0.1234567890123456789012300"), "-0.12345678901234567890123"), (D(0), "0")):
            with self.subTest(value=value):
                rendered = render_telegram_message(sample(T.POSITION_CLOSE_CONFIRMED,
                    details=event.details+(("realized_trade_pnl_quote", value),)))
                self.assertIn("Realized trade PnL (quote): "+expected, rendered)

    def test_high_precision_quantity_and_risk_values_not_rounded(self):
        event = sample(T.POSITION_OPEN_CONFIRMED)
        values = dict(event.details)
        values["owned_base_quantity"] = D("0.049950000000000000000000000001")
        self.assertIn("0.049950000000000000000000000001", render_telegram_message(sample(T.POSITION_OPEN_CONFIRMED, details=tuple(values.items()))))
        trip = sample(T.RISK_TRIPPED)
        text = render_telegram_message(sample(T.RISK_TRIPPED, details=trip.details+(("risk_equity", D("999.8951")), ("daily_pnl", D("-0.104900")))))
        self.assertIn("Risk equity (quote): 999.8951", text)
        self.assertIn("Daily PnL (quote): -0.1049", text)
        self.assertNotIn("halted", text.lower())

    def test_halt_known_exposure_and_pending_reference(self):
        event = sample(T.RUNTIME_HALTED)
        text = render_telegram_message(sample(T.RUNTIME_HALTED, details=event.details+(
            ("owned_base_quantity", D("0.04995")), ("pending_action_id", "d"*64))))
        self.assertIn("Owned base quantity: 0.04995", text)
        self.assertIn("Pending action: "+"d"*12, text)
        self.assertNotIn("retry", text.lower())

    def test_uncertain_requires_review_not_resend(self):
        text = render_telegram_message(sample(T.RUNTIME_UNCERTAIN))
        self.assertIn("Operator review required", text)
        self.assertNotIn("retry", text.lower())
        self.assertNotIn("liquidat", text.lower())

    def test_critical_only_safe_fields(self):
        text = render_telegram_message(sample(T.CRITICAL_FAILURE, details=(("operation", "READ"),
            ("failure_kind", "IO"), ("exception_type", "OSError"), ("safe_error_code", "DISK_FULL"))))
        self.assertIn("Safe error code: DISK_FULL", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("account_binding", text)

    def test_no_ordinary_events_rendered_as_alerts(self):
        for kind in (T.CYCLE_COMPLETED, T.RISK_BLOCKED, T.OWNED_EXECUTION_DISCOVERED, T.ACTION_ACKNOWLEDGED, T.ACTION_UNKNOWN_OUTCOME):
            with self.subTest(kind=kind), self.assertRaises(TelegramError):
                render_telegram_message(sample(kind))

    def test_oversized_exact_finances_raise_without_truncation(self):
        event = sample(T.POSITION_OPEN_CONFIRMED)
        values = dict(event.details)
        values["owned_base_quantity"] = D("1E3500")
        with self.assertRaises(TelegramError):
            render_telegram_message(sample(T.POSITION_OPEN_CONFIRMED, details=tuple(values.items())))

    def test_unrenderable_utc_rejected(self):
        with self.assertRaises(TelegramError):
            render_telegram_message(sample(occurred_at_ms=2**63-1))

    def test_malformed_event_never_dumped(self):
        for value in ({"token": TOKEN}, Exception(TOKEN), None, "raw broker payload"):
            with self.subTest(value=type(value)), self.assertRaises(TelegramError) as caught:
                render_telegram_message(value)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_no_trading_dependencies_or_hidden_imports(self):
        tree = ast.parse(Path(t.__file__).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and any(part in name.split(".") for part in ("runtime", "exchange", "risk", "strategies")) for name in imports))
        forbidden = {"RuntimeStore", "place_order", "cancel_order", "reconcile_startup", "run_single_cycle", "run_hourly_scheduler",
                     "rearm_runtime_halt", "rearm_risk_epoch", "getUpdates", "setWebhook", "deleteWebhook", "answerCallbackQuery",
                     "__import__", "import_module", "eval", "exec", "float", "getenv", "vars", "asdict"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, forbidden)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden | {"environ", "_connection", "_transaction"})


class ConfigurationAndTransportTests(TelegramCase):
    def test_token_validation_finite_shape(self):
        for value in (None, True, "", "arbitrary", "0:"+"x"*20, "1:"+"x"*19, "1:"+"x"*129, "x"*100000):
            with self.subTest(value=type(value)), self.assertRaises(TelegramConfigurationError) as caught:
                self.transport(token=value)
            self.assertNotIn(TOKEN, str(caught.exception))
        self.transport(token="1:"+"x"*20)
        self.transport(token="9"*20+":"+"x"*128)

    def test_chat_validation_canonical_bounded_numeric(self):
        for value in (None, True, 123, "", "0", "-0", "+1", "01", "-01", " 1", "@alias", "１２３", str(2**63), "-"+str(2**63+1)):
            with self.subTest(value=value), self.assertRaises(TelegramConfigurationError):
                self.transport(chat=value)
        for value in ("123456789", CHAT, str(2**63-1), str(-(2**63))):
            self.transport(chat=value)

    def test_session_is_explicit_and_dedicated(self):
        with self.assertRaises(TypeError):
            TelegramHttpTransport(TOKEN, CHAT)
        session = FakeSession(Response())
        session.auth = ("synthetic-user", "synthetic-password")
        session.headers["Authorization"] = "synthetic"
        session.cookies.set("synthetic", "private")
        TelegramHttpTransport(TOKEN, CHAT, session=session, sleeper=self.sleeps.append)
        self.assertFalse(session.trust_env)
        self.assertIsNone(session.auth)
        self.assertEqual(dict(session.headers), {})
        self.assertEqual(len(session.cookies), 0)
        self.assertEqual((session.params, session.proxies, session.hooks), ({}, {}, {}))
        self.assertTrue(session.verify)
        self.assertIsNone(session.cert)

    def test_sdk_retries_rejected_for_actual_endpoint(self):
        session = FakeSession(Response())
        session.mount("https://api.telegram.org/bot", requests.adapters.HTTPAdapter(max_retries=1))
        with self.assertRaises(TelegramConfigurationError):
            TelegramHttpTransport(TOKEN, CHAT, session=session)
        self.assertEqual(session.calls, [])

    def test_fixed_origin_post_shape_and_response_close(self):
        response = Response()
        transport = self.transport(response)
        result = transport.send_message("Literal < > * _ [ ]")
        self.assertIs(result.status, S.DELIVERED)
        url, kwargs = self.session.calls[0]
        self.assertEqual(url, "https://api.telegram.org/bot"+TOKEN+"/sendMessage")
        self.assertEqual(kwargs, {"json": {"chat_id": CHAT, "text": "Literal < > * _ [ ]", "disable_web_page_preview": True},
            "timeout": (5,10), "allow_redirects": False, "stream": True})
        self.assertTrue(response.closed)
        self.assertEqual(response.raw.read_sizes, [t.MAX_TELEGRAM_RESPONSE_BYTES+1])

    def test_no_url_override(self):
        with self.assertRaises(TypeError):
            TelegramHttpTransport(TOKEN, CHAT, session=FakeSession(), base_url="https://synthetic.invalid")

    def test_repr_str_results_hide_token_and_chat(self):
        transport = self.transport()
        result = transport.send_message("safe text")
        for obj in (transport, self.receipts, result):
            for text in (repr(obj), str(obj)):
                self.assertNotIn(TOKEN, text)
                self.assertNotIn(CHAT, text)
        self.assertFalse(hasattr(transport, "__dict__"))

    def test_message_bound_and_token_refusal_before_http(self):
        transport = self.transport(Response(), Response())
        for value in ("", None, "x"*3501, TOKEN, "bad\x00text"):
            with self.subTest(value=type(value)), self.assertRaises(TelegramTransportError):
                transport.send_message(value)
        self.assertEqual(self.session.calls, [])
        self.assertIs(transport.send_message("x"*3500).status, S.DELIVERED)

    def test_confirmed_success_requires_nonbool_integer_message_id(self):
        for message_id in (None, True, "123", -1, 2**63, 1.5):
            result = self.transport(Response(body={"ok":True,"result":{"message_id":message_id}})).send_message("safe")
            self.assertIs(result.status, S.AMBIGUOUS)
            self.assertEqual(len(self.session.calls), 1)

    def test_200_false_is_explicit_failure(self):
        result = self.transport(Response(body={"ok":False,"description":TOKEN})).send_message("safe")
        self.assertIs(result.status, S.PERMANENT_FAILURE)
        self.assertNotIn(TOKEN, repr(result))

    def test_malformed_200_no_retry(self):
        for raw in (b"bad", b"[]", b"null", b'{"ok":true}', b'{"ok":1,"result":{"message_id":1}}',
                    b'{"ok":true,"ok":true,"result":{"message_id":1}}', b'{"ok":NaN}'):
            with self.subTest(raw=raw):
                result = self.transport(Response(raw=raw), Response()).send_message("safe")
                self.assertIs(result.status, S.AMBIGUOUS)
                self.assertEqual(result.attempt_count, 1)
                self.assertEqual(len(self.session.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_network_timeout_connection_and_read_error_ambiguous(self):
        for response in (requests.Timeout(TOKEN), requests.ConnectionError(TOKEN), Response(raw=requests.Timeout(TOKEN))):
            with self.subTest(response=type(response)):
                result = self.transport(response, Response()).send_message("safe")
                self.assertIs(result.status, S.AMBIGUOUS)
                self.assertEqual(len(self.session.calls), 1)
                self.assertNotIn(TOKEN, repr(result))
        self.assertEqual(self.sleeps, [])

    def test_explicit_transient_exhaustion_bounded(self):
        for code in (429, 500, 503):
            self.sleeps.clear()
            result = self.transport(*(Response(code) for _ in range(4))).send_message("safe")
            self.assertIs(result.status, S.TRANSIENT_FAILURE)
            self.assertEqual((result.attempt_count, len(self.session.calls)), (3,3))
            self.assertEqual(self.sleeps, [1,2])

    def test_transient_then_success(self):
        result = self.transport(Response(429), Response(503), Response()).send_message("safe")
        self.assertIs(result.status, S.DELIVERED)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(self.sleeps, [1,2])

    def test_transient_then_ambiguous_stops(self):
        result = self.transport(Response(500), requests.Timeout(TOKEN), Response()).send_message("safe")
        self.assertIs(result.status, S.AMBIGUOUS)
        self.assertEqual((result.attempt_count, len(self.session.calls)), (2,2))
        self.assertEqual(self.sleeps, [1])

    def test_permanent_statuses_single_attempt_no_body_parse(self):
        for code in (400,401,403,404):
            response = Response(code, raw=AssertionError("Must not read raw body"))
            result = self.transport(response, Response()).send_message("safe")
            self.assertIs(result.status, S.PERMANENT_FAILURE)
            self.assertEqual(len(self.session.calls), 1)
            self.assertTrue(response.closed)

    def test_redirect_and_unexpected_status_never_followed(self):
        for code in (301,302,201,"200",True):
            result = self.transport(Response(code), Response()).send_message("safe")
            self.assertIs(result.status, S.AMBIGUOUS)
            self.assertFalse(self.session.calls[0][1]["allow_redirects"])
            self.assertEqual(len(self.session.calls), 1)

    def test_response_size_bound(self):
        response = Response(raw=b" "*(t.MAX_TELEGRAM_RESPONSE_BYTES+1))
        result = self.transport(response).send_message("safe")
        self.assertIs(result.status, S.AMBIGUOUS)

    def test_close_failure_cannot_undo_proven_success(self):
        response = Response()
        with patch.object(response, "close", side_effect=RuntimeError(TOKEN)):
            result = self.transport(response).send_message("safe")
        self.assertIs(result.status, S.DELIVERED)

    def test_retry_sleeper_failure_safe_no_more_requests(self):
        transport = self.transport(Response(500), Response())
        transport._sleeper = lambda _: (_ for _ in ()).throw(RuntimeError(TOKEN))
        with self.assertRaises(TelegramTransportError) as caught:
            transport.send_message("safe")
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(len(self.session.calls), 1)

    def test_http_client_token_url_diagnostics_suppressed_then_restored(self):
        logger = logging.getLogger("urllib3.connectionpool")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler,handler)
        prior = tuple(logger.filters)
        transport = self.transport(Response())
        real_post = self.session.post
        def noisy_post(url,**kwargs):
            logger.warning("HTTP client diagnostic %s",url)
            return real_post(url,**kwargs)
        with patch.object(self.session,"post",side_effect=noisy_post):
            self.assertIs(transport.send_message("safe").status,S.DELIVERED)
        self.assertEqual(stream.getvalue(),"")
        self.assertEqual(tuple(logger.filters),prior)
        logger.warning("safe outside diagnostic")
        self.assertIn("safe outside diagnostic",stream.getvalue())
        self.assertNotIn(TOKEN,stream.getvalue())

    def test_url_log_guard_is_thread_scoped_and_restored_after_ambiguity(self):
        guard = t._PrivateHttpDiagnostics()
        record = logging.LogRecord("urllib3.connectionpool",logging.WARNING,"",0,"synthetic",(),None)
        self.assertFalse(guard.filter(record))
        with patch.object(t.threading,"get_ident",return_value=guard.thread_id+1):
            self.assertTrue(guard.filter(record))
        logger = logging.getLogger("urllib3.connectionpool")
        prior = tuple(logger.filters)
        self.assertIs(self.transport(requests.Timeout(TOKEN)).send_message("safe").status,S.AMBIGUOUS)
        self.assertEqual(tuple(logger.filters),prior)


class DeliveryAndReceiptTests(TelegramCase):
    def test_confirmed_delivery_then_no_network_duplicate(self):
        transport = self.transport(Response())
        event = sample()
        first = deliver_telegram_event(event, transport, self.receipts, utc_now_ms=lambda: 4567)
        second = deliver_telegram_event(event, transport, self.receipts)
        self.assertEqual((first.status, second.status), (S.DELIVERED, S.ALREADY_DELIVERED))
        self.assertEqual(len(self.session.calls), 1)
        self.assertEqual((first.event_id, first.telegram_message_id, first.delivered_at_ms), (event.event_id,123,4567))
        self.assertEqual(second.attempt_count, 0)

    def test_restart_dedupe_durable_event_id_ignores_run_and_clock(self):
        event = sample(T.POSITION_OPEN_CONFIRMED)
        self.deliver(event)
        receipts = TelegramDeliveryStore(ObservabilityStorage(self.storage.root,self.config), CHAT)
        event_again = sample(T.POSITION_OPEN_CONFIRMED, run_id="1"*32, observed_at_ms=999999)
        transport = self.transport()
        result = deliver_telegram_event(event_again,transport,receipts)
        self.assertIs(result.status,S.ALREADY_DELIVERED)
        self.assertEqual(self.session.calls,[])

    def test_different_target_has_separate_receipt_namespace(self):
        self.deliver()
        other_chat = "123456789"
        other = TelegramDeliveryStore(self.storage, other_chat)
        transport = self.transport(chat=other_chat)
        result = deliver_telegram_event(sample(),transport,other,utc_now_ms=lambda:1)
        self.assertIs(result.status,S.DELIVERED)
        self.assertNotEqual(other.target_hash,self.receipts.target_hash)
        self.assertEqual(len(self.session.calls),1)
        for store in (self.receipts,other):
            self.assertNotIn(CHAT,str(store.directory))
            self.assertNotIn(other_chat,str(store.directory))

    def test_target_hash_canonical_chat_only_not_token(self):
        canonical = json.dumps({"chat_id":CHAT},sort_keys=True,separators=(",",":")).encode()
        self.assertEqual(self.receipts.target_hash,hashlib.sha256(canonical).hexdigest())
        self.deliver()
        transport = self.transport(token="123456:ANOTHER_FAKE_TOKEN_FOR_TESTING_ONLY")
        self.assertIs(deliver_telegram_event(sample(),transport,self.receipts).status,S.ALREADY_DELIVERED)
        self.assertEqual(self.session.calls,[])

    def test_mismatched_target_fails_before_request(self):
        transport = self.transport(chat="123456789")
        with self.assertRaises(TelegramConfigurationError):
            deliver_telegram_event(sample(),transport,self.receipts)
        self.assertEqual(self.session.calls,[])

    def test_other_instance_event_refused_before_request(self):
        transport = self.transport()
        event = process_started(replace(self.config,bot_id="bot2"),run_id=RUN,observed_at_ms=1,process_started_at_ms=0)
        with self.assertRaises(TelegramDeliveryStateError):
            deliver_telegram_event(event,transport,self.receipts)
        self.assertEqual(self.session.calls,[])

    def test_non_alertable_has_no_lookup_write_or_network(self):
        transport = self.transport()
        with patch.object(TelegramDeliveryStore,"get_receipt",side_effect=AssertionError("No lookup")), \
             patch.object(TelegramDeliveryStore,"record_delivery",side_effect=AssertionError("No write")):
            for kind in (T.CYCLE_COMPLETED,T.RISK_BLOCKED,T.OWNED_EXECUTION_DISCOVERED,T.ACTION_UNKNOWN_OUTCOME):
                self.assertIs(deliver_telegram_event(sample(kind),transport,self.receipts).status,S.NOT_ALERTABLE)
        self.assertEqual(self.session.calls,[])
        self.assertFalse(self.receipts.directory.exists())

    def test_ambiguous_and_failures_never_record_success(self):
        for responses, expected in (((requests.Timeout(TOKEN),),S.AMBIGUOUS),
                                    ((Response(raw=b"bad"),),S.AMBIGUOUS),
                                    ((Response(401),),S.PERMANENT_FAILURE),
                                    ((Response(500),Response(500),Response(500)),S.TRANSIENT_FAILURE)):
            with self.subTest(expected=expected):
                result = self.deliver(None,*responses)
                self.assertIs(result.status,expected)
                self.assertIsNone(self.receipts.get_receipt(sample().event_id))

    def test_success_receipt_failure_unrecorded_no_retry_one_safe_indication(self):
        stream = io.StringIO()
        transport = self.transport(Response(),Response())
        with patch.object(TelegramDeliveryStore,"record_delivery",side_effect=TelegramDeliveryStateError(TOKEN)), \
                patch.object(t.sys,"stderr",stream):
            result = deliver_telegram_event(sample(),transport,self.receipts)
        self.assertIs(result.status,S.DELIVERED_UNRECORDED)
        self.assertEqual((result.telegram_message_id,len(self.session.calls)),(123,1))
        self.assertEqual(stream.getvalue().count("\n"),1)
        for secret in (TOKEN,CHAT):
            self.assertNotIn(secret,repr(result)+stream.getvalue())

    def test_fallback_failure_does_not_recurse_or_change_delivery(self):
        transport = self.transport()
        with patch.object(TelegramDeliveryStore,"record_delivery",side_effect=TelegramDeliveryStateError("fixed")), \
                patch.object(t.sys.stderr,"write",side_effect=OSError(TOKEN)) as fallback:
            result = deliver_telegram_event(sample(),transport,self.receipts)
        self.assertIs(result.status,S.DELIVERED_UNRECORDED)
        self.assertEqual(fallback.call_count,1)

    def test_invalid_post_success_clock_is_unrecorded(self):
        stream = io.StringIO()
        transport = self.transport()
        with patch.object(t.sys,"stderr",stream):
            result = deliver_telegram_event(sample(),transport,self.receipts,utc_now_ms=lambda:True)
        self.assertIs(result.status,S.DELIVERED_UNRECORDED)
        self.assertFalse(self.path().exists())
        self.assertEqual(len(self.session.calls),1)

    def test_crash_before_request_has_no_message_no_receipt(self):
        transport = self.transport()
        with patch.object(TelegramHttpTransport,"send_message",side_effect=Crash()):
            with self.assertRaises(Crash):
                deliver_telegram_event(sample(),transport,self.receipts)
        self.assertEqual(self.session.calls,[])
        self.assertIsNone(self.receipts.get_receipt(sample().event_id))

    def test_crash_after_remote_success_before_receipt_can_duplicate_later(self):
        transport = self.transport(Response(),Response())
        with self.assertRaises(Crash):
            deliver_telegram_event(sample(),transport,self.receipts,utc_now_ms=lambda: (_ for _ in ()).throw(Crash()))
        self.assertEqual(len(self.session.calls),1)
        self.assertIsNone(self.receipts.get_receipt(sample().event_id))
        self.assertIs(deliver_telegram_event(sample(),transport,self.receipts,utc_now_ms=lambda:1).status,S.DELIVERED)
        self.assertEqual(len(self.session.calls),2)

    def test_crash_after_receipt_restart_dedupes(self):
        transport = self.transport(Response())
        original = TelegramDeliveryStore.record_delivery
        def record_then_crash(store,*args,**kwargs):
            original(store,*args,**kwargs)
            raise Crash()
        with patch.object(TelegramDeliveryStore,"record_delivery",record_then_crash):
            with self.assertRaises(Crash):
                deliver_telegram_event(sample(),transport,self.receipts,utc_now_ms=lambda:1)
        restarted = TelegramDeliveryStore(self.storage,CHAT)
        self.assertIs(deliver_telegram_event(sample(),transport,restarted).status,S.ALREADY_DELIVERED)
        self.assertEqual(len(self.session.calls),1)

    def test_receipt_minimal_canonical_and_no_secret_or_body(self):
        self.deliver()
        raw = self.path().read_bytes()
        value = json.loads(raw)
        self.assertEqual(set(value),{"version","event_id","target_hash","telegram_message_id","delivered_at_ms"})
        self.assertEqual(raw,json.dumps(value,sort_keys=True,separators=(",",":")).encode())
        for secret in (TOKEN,CHAT,"Trading Lab started","SECRET-LIKE-UNTRUSTED-TEXT"):
            self.assertNotIn(secret,raw.decode()+str(self.path()))
        self.assertEqual(self.path().name,sample().event_id+".json")

    def test_permissions_and_immutable_receipt_first_wins(self):
        self.deliver()
        before = self.path().read_bytes()
        self.assertFalse(self.receipts.record_delivery(sample().event_id,telegram_message_id=999,delivered_at_ms=999))
        self.assertEqual(self.path().read_bytes(),before)
        self.assertEqual(stat.S_IMODE(self.path().stat().st_mode),0o600)
        for path in (self.receipts.directory,self.receipts.directory.parent):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o700)

    def test_receipt_fsync_file_and_directories(self):
        with patch.object(t.os,"fsync",wraps=os.fsync) as sync:
            self.deliver()
        self.assertEqual(sync.call_count,4)  # Two newly created directories, file, target directory.

    def test_receipt_corruption_prevents_network(self):
        self.deliver()
        for data in (b"",b"{",b"{}",b"[]",b"x"*(t.MAX_TELEGRAM_RECEIPT_BYTES+1)):
            self.path().write_bytes(data)
            transport = self.transport()
            with self.subTest(data=data[:10]), self.assertRaises(TelegramDeliveryStateError):
                deliver_telegram_event(sample(),transport,self.receipts)
            self.assertEqual(self.session.calls,[])

    def test_wrong_receipt_binding_version_extra_and_duplicate_rejected(self):
        self.deliver()
        value = json.loads(self.path().read_bytes())
        for fields in ({"version":True},{"version":2},{"event_id":"0"*64},{"target_hash":"0"*64},
                       {"telegram_message_id":True},{"delivered_at_ms":-1},{"token":TOKEN}):
            self.path().write_bytes(json.dumps({**value,**fields},sort_keys=True,separators=(",",":")).encode())
            with self.subTest(fields=list(fields)), self.assertRaises(TelegramDeliveryStateError) as caught:
                self.receipts.get_receipt(sample().event_id)
            self.assertNotIn(TOKEN,str(caught.exception))
        self.path().write_bytes(json.dumps(value).encode()[:-1]+b',"version":1}')
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)

    def test_raw_description_and_http_exception_never_leak(self):
        secret = "SECRET-LIKE-UNTRUSTED-TEXT"
        stream = io.StringIO()
        with patch.object(t.sys,"stderr",stream):
            result = self.deliver(None,Response(403,body={"ok":False,"description":secret}))
        for text in (repr(result),stream.getvalue()):
            self.assertNotIn(secret,text)
            self.assertNotIn(TOKEN,text)
            self.assertNotIn(CHAT,text)
        self.assertFalse(self.path().exists())

    def test_bounded_direct_lookup_no_directory_scan(self):
        self.deliver()
        with patch.object(Path,"iterdir",side_effect=AssertionError("No scan")), \
                patch.object(Path,"rglob",side_effect=AssertionError("No scan")):
            self.assertIs(self.receipts.get_receipt(sample().event_id).status,S.ALREADY_DELIVERED)

    def test_path_escape_invalid_event_reference(self):
        for reference in ("../escape","x"*65,"A"*64,None):
            with self.subTest(reference=reference), self.assertRaises(TelegramDeliveryStateError):
                self.receipts.get_receipt(reference)

    def test_symlink_receipt_refused_without_target_change(self):
        self.deliver()
        target = Path(self.temp)/"unrelated"
        target.write_bytes(b"original")
        self.path().unlink()
        self.path().symlink_to(target)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)
        self.assertEqual(target.read_bytes(),b"original")

    def test_symlink_target_directory_refused(self):
        self.deliver()
        self.path().unlink()
        self.receipts.directory.rmdir()
        target = Path(self.temp)/"elsewhere"
        target.mkdir(mode=0o700)
        self.receipts.directory.symlink_to(target,target_is_directory=True)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)
        self.assertEqual(list(target.iterdir()),[])

    def test_fifo_hardlink_and_broader_file_permissions_refused(self):
        self.deliver()
        self.path().chmod(0o644)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)
        self.assertEqual(stat.S_IMODE(self.path().stat().st_mode),0o644)
        self.path().chmod(0o600)
        link = Path(self.temp)/"hardlink"
        os.link(self.path(),link)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)
        link.unlink()
        self.path().unlink()
        os.mkfifo(self.path(),0o600)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)

    def test_unsafe_directory_permissions_refused_before_http(self):
        self.deliver()
        self.receipts.directory.chmod(0o755)
        transport = self.transport()
        with self.assertRaises(TelegramDeliveryStateError):
            deliver_telegram_event(sample(),transport,self.receipts)
        self.assertEqual(self.session.calls,[])

    def test_receipt_parent_substitution_refused_without_network(self):
        self.deliver()
        self.path().unlink()
        self.receipts.directory.rmdir()
        parent = self.receipts.directory.parent
        parent.rmdir()
        parent.write_bytes(b"not a directory")
        transport = self.transport()
        with self.assertRaises(TelegramDeliveryStateError):
            deliver_telegram_event(sample(),transport,self.receipts)
        self.assertEqual(self.session.calls,[])

    def test_receipt_directory_binding_cannot_be_changed(self):
        with self.assertRaises(FrozenInstanceError):
            self.receipts.target_hash = "../escape"
        with self.assertRaises(TelegramConfigurationError):
            TelegramDeliveryStore(Path(self.temp),CHAT)

    def test_disk_failure_after_success_never_resends(self):
        transport = self.transport(Response(),Response())
        with patch.object(t.os,"mkdir",side_effect=OSError(errno.ENOSPC,TOKEN)),patch.object(t.sys,"stderr",io.StringIO()) as errors:
            result = deliver_telegram_event(sample(),transport,self.receipts)
        self.assertIs(result.status,S.DELIVERED_UNRECORDED)
        self.assertEqual(len(self.session.calls),1)
        self.assertNotIn(TOKEN,errors.getvalue())

    def test_partial_receipt_write_is_unrecorded_then_explicit_corruption(self):
        # Pre-create directories so the fault targets the receipt content.
        with self.receipts._directory(create=True):
            pass
        real_write = os.write
        stream = io.StringIO()
        with patch.object(t.os,"write",side_effect=lambda fd,data:real_write(fd,data[:10])),patch.object(t.sys,"stderr",stream):
            result = self.deliver()
        self.assertIs(result.status,S.DELIVERED_UNRECORDED)
        self.assertEqual(len(self.session.calls),1)
        with self.assertRaises(TelegramDeliveryStateError):
            self.receipts.get_receipt(sample().event_id)

    def test_delivery_result_frozen_slotted_and_explicit_status(self):
        result = self.deliver()
        self.assertFalse(hasattr(result,"__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.status = S.AMBIGUOUS
        with self.assertRaises(TelegramError):
            TelegramDeliveryResult("DELIVERED",1,123)


class BatchTests(TelegramCase):
    def test_order_skip_open_dedupe_close(self):
        transport = self.transport(Response(),Response())
        opening,closing = sample(T.POSITION_OPEN_CONFIRMED),sample(T.POSITION_CLOSE_CONFIRMED)
        result = deliver_telegram_events((sample(T.CYCLE_COMPLETED),opening,opening,closing),transport,self.receipts,utc_now_ms=lambda:1)
        self.assertEqual([r.status for r in result],[S.NOT_ALERTABLE,S.DELIVERED,S.ALREADY_DELIVERED,S.DELIVERED])
        self.assertIn("position opened",self.session.calls[0][1]["json"]["text"])
        self.assertIn("position closed",self.session.calls[1][1]["json"]["text"])

    def test_batch_stops_on_every_unresolved_status(self):
        for responses, expected in (((requests.Timeout(TOKEN),),S.AMBIGUOUS),((Response(403),),S.PERMANENT_FAILURE),
                                    ((Response(500),Response(500),Response(500)),S.TRANSIENT_FAILURE)):
            transport = self.transport(*responses,Response())
            results = deliver_telegram_events((sample(),sample(T.POSITION_OPEN_CONFIRMED)),transport,self.receipts)
            self.assertEqual(len(results),1)
            self.assertIs(results[0].status,expected)
            self.assertEqual(len(self.session.calls),len(responses))

    def test_batch_stops_when_delivery_unrecorded(self):
        transport = self.transport(Response(),Response())
        with patch.object(TelegramDeliveryStore,"record_delivery",side_effect=TelegramDeliveryStateError("fixed")), \
                patch.object(t.sys,"stderr",io.StringIO()):
            results = deliver_telegram_events((sample(),sample(T.POSITION_OPEN_CONFIRMED)),transport,self.receipts)
        self.assertEqual([r.status for r in results],[S.DELIVERED_UNRECORDED])
        self.assertEqual(len(self.session.calls),1)

    def test_batch_bounds_empty_and_preserved_input(self):
        transport = self.transport()
        event = sample(T.CYCLE_COMPLETED)
        self.assertEqual(deliver_telegram_events((),transport,self.receipts),())
        events = (event,)*MAX_TELEGRAM_BATCH_EVENTS
        results = deliver_telegram_events(events,transport,self.receipts)
        self.assertEqual(len(results),MAX_TELEGRAM_BATCH_EVENTS)
        self.assertEqual(events,(event,)*MAX_TELEGRAM_BATCH_EVENTS)
        for value in ([event],(event,)*(MAX_TELEGRAM_BATCH_EVENTS+1),iter((event,))):
            with self.assertRaises(TelegramError):
                deliver_telegram_events(value,transport,self.receipts)
        self.assertEqual(self.session.calls,[])

    def test_batch_validates_all_records_before_first_send(self):
        transport = self.transport()
        with self.assertRaises(TelegramError):
            deliver_telegram_events((sample(),{"token":TOKEN}),transport,self.receipts)
        self.assertEqual(self.session.calls,[])


class GoldenIsolationTests(golden_fixtures.IntegrationCase):
    def test_receipt_failure_and_deletion_cannot_change_golden_trading_truth(self):
        history,actions,fills,_ = self.golden()
        self.assertEqual((len(history),len(self.sends),len(fills),len(self.cancels),self.store.get_current_risk_epoch().epoch_sequence),(54,2,2,0,1))
        before = self.store.get_checkpoint(),self.store.list_actions(),self.store.list_fills(),self.store.list_risk_valuations(),self.store.list_risk_verdicts()
        storage = ObservabilityStorage(Path(self.directory).resolve()/"telegram-test",self.config)
        health_path = storage.instance_directory/"health.json"
        health_path.write_bytes(b"sentinel-health-unchanged")
        receipts = TelegramDeliveryStore(storage,CHAT)
        session = FakeSession(Response(),Response(),Response())
        transport = TelegramHttpTransport(TOKEN,CHAT,session=session,sleeper=lambda _:self.fail("No sleep"))
        event = process_started(self.config,run_id=RUN,observed_at_ms=1,process_started_at_ms=0)
        with patch.object(TelegramDeliveryStore,"record_delivery",side_effect=TelegramDeliveryStateError("fixed")), \
                patch.object(t.sys,"stderr",io.StringIO()):
            self.assertIs(deliver_telegram_event(event,transport,receipts).status,S.DELIVERED_UNRECORDED)
        self.assertIs(deliver_telegram_event(event,transport,receipts,utc_now_ms=lambda:1).status,S.DELIVERED)
        (receipts.directory/(event.event_id+".json")).unlink()
        self.assertIs(deliver_telegram_event(event,transport,receipts,utc_now_ms=lambda:2).status,S.DELIVERED)
        self.assertEqual(len(session.calls),3)  # Notification duplicates, never orders.
        self.assertEqual(health_path.read_bytes(),b"sentinel-health-unchanged")
        self.assertEqual(before,(self.store.get_checkpoint(),self.store.list_actions(),self.store.list_fills(),self.store.list_risk_valuations(),self.store.list_risk_verdicts()))
        self.assertEqual((len(self.sends),len(self.cancels)),(2,0))
