"""Outbound notifications only; no trading resources, hooks or secret loading.

The caller supplies a dedicated requests-compatible session and owns its
lifecycle. Client creation/configuration wiring is deliberately outside this
component. A remote success and a local receipt are separate operations:
crashes, ambiguous responses and concurrent callers can duplicate notifications.
No receipt is trading truth, and exactly-once delivery is not promised.
"""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

from .model import ObservabilityEvent, ObservabilityEventType, event_from_json
from .storage import ObservabilityStorage

__all__ = [
    "TELEGRAM_ALERT_EVENT_TYPES", "MAX_TELEGRAM_MESSAGE_CHARS", "MAX_TELEGRAM_BATCH_EVENTS",
    "TelegramError", "TelegramConfigurationError", "TelegramTransportError", "TelegramDeliveryStateError",
    "TelegramDeliveryStatus", "TelegramDeliveryResult", "is_telegram_alert_event", "render_telegram_message",
    "TelegramHttpTransport", "TelegramDeliveryStore", "deliver_telegram_event", "deliver_telegram_events",
]

MAX_TELEGRAM_MESSAGE_CHARS = 3500
MAX_TELEGRAM_BATCH_EVENTS = 256
MAX_TELEGRAM_RESPONSE_BYTES = 65_536
MAX_TELEGRAM_RECEIPT_BYTES = 1024
TELEGRAM_RECEIPT_VERSION = 1
_ORIGIN = "https://api.telegram.org"
_TIMEOUT = (5, 10)
_BACKOFF = (1, 2)
_T = ObservabilityEventType
TELEGRAM_ALERT_EVENT_TYPES = frozenset((
    _T.PROCESS_STARTED, _T.PROCESS_STOPPED, _T.POSITION_OPEN_CONFIRMED, _T.POSITION_CLOSE_CONFIRMED,
    _T.RISK_TRIPPED, _T.RUNTIME_HALTED, _T.RUNTIME_UNCERTAIN, _T.RUNTIME_REARMED,
    _T.RISK_REARMED, _T.CRITICAL_FAILURE,
))
_TITLES = {
    _T.PROCESS_STARTED: "Trading Lab started", _T.PROCESS_STOPPED: "Trading Lab stopped",
    _T.POSITION_OPEN_CONFIRMED: "Confirmed position opened",
    _T.POSITION_CLOSE_CONFIRMED: "Confirmed position closed",
    _T.RISK_TRIPPED: "Risk tripped", _T.RUNTIME_HALTED: "Runtime halted",
    _T.RUNTIME_UNCERTAIN: "Runtime uncertain", _T.RUNTIME_REARMED: "Runtime rearm accepted",
    _T.RISK_REARMED: "Risk rearm accepted", _T.CRITICAL_FAILURE: "Critical runtime failure",
}


class TelegramError(ValueError):
    """Only fixed safe diagnostics; no raw HTTP/exception/configuration text."""


class TelegramConfigurationError(TelegramError):
    """Invalid explicit configuration."""


class TelegramTransportError(TelegramError):
    """Invalid local send input; remote outcomes use explicit statuses."""


class TelegramDeliveryStateError(TelegramError):
    """Missing integrity/permissions or malformed local delivery evidence."""


class TelegramDeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    ALREADY_DELIVERED = "ALREADY_DELIVERED"
    NOT_ALERTABLE = "NOT_ALERTABLE"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"
    DELIVERED_UNRECORDED = "DELIVERED_UNRECORDED"


def _integer(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _chat(value):
    if (type(value) is not str or re.fullmatch(r"-?[1-9][0-9]{0,18}", value) is None
            or not -(2**63) <= int(value) <= 2**63 - 1):
        raise TelegramConfigurationError("Invalid Telegram destination configuration.")
    return value


def _target(chat_id):
    return hashlib.sha256(_canonical({"chat_id": _chat(chat_id)})).hexdigest()


@dataclass(frozen=True, slots=True)
class TelegramDeliveryResult:
    status: TelegramDeliveryStatus
    attempt_count: int = 0
    telegram_message_id: int | None = None
    event_id: str | None = None
    delivered_at_ms: int | None = None

    def __post_init__(self):
        valid = (type(self.status) is TelegramDeliveryStatus and type(self.attempt_count) is int
                 and 0 <= self.attempt_count <= 3
                 and (self.event_id is None or _digest(self.event_id))
                 and (self.telegram_message_id is None or _integer(self.telegram_message_id))
                 and (self.delivered_at_ms is None or _integer(self.delivered_at_ms)))
        if not valid:
            raise TelegramError("Invalid normalized Telegram delivery result.")
        confirmed = self.status in (TelegramDeliveryStatus.DELIVERED, TelegramDeliveryStatus.ALREADY_DELIVERED,
                                    TelegramDeliveryStatus.DELIVERED_UNRECORDED)
        if confirmed != (self.telegram_message_id is not None):
            raise TelegramError("Inconsistent normalized Telegram delivery result.")
        skipped = self.status in (TelegramDeliveryStatus.ALREADY_DELIVERED, TelegramDeliveryStatus.NOT_ALERTABLE)
        if skipped != (self.attempt_count == 0):
            raise TelegramError("Inconsistent Telegram attempt count.")
        if (not confirmed and self.delivered_at_ms is not None
                or self.status is TelegramDeliveryStatus.ALREADY_DELIVERED
                and (self.event_id is None or self.delivered_at_ms is None)):
            raise TelegramError("Inconsistent Telegram receipt evidence.")


def _event(event):
    try:
        if type(event) is not ObservabilityEvent:
            raise TelegramError("A validated observability event is required.")
        return event_from_json(event.to_json())
    except Exception:
        raise TelegramError("A validated observability event is required.") from None


def is_telegram_alert_event(event: ObservabilityEvent) -> bool:
    return _event(event).event_type in TELEGRAM_ALERT_EVENT_TYPES


def _utc(milliseconds):
    if milliseconds is None:
        return "unavailable"
    try:
        value = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)
        return value.strftime("%Y-%m-%d %H:%M:%S") + f".{milliseconds % 1000:03d} UTC"
    except (ValueError, OverflowError, TypeError):
        raise TelegramError("Event time cannot be rendered safely.") from None


def render_telegram_message(event: ObservabilityEvent) -> str:
    """Deterministic plain text from approved fields, with no inferred finances."""
    event = _event(event)
    if event.event_type not in TELEGRAM_ALERT_EVENT_TYPES:
        raise TelegramError("Event is outside the Telegram alert policy.")
    values = event.to_dict()  # Already canonical exact Decimal strings.
    kind = event.event_type
    lines = [_TITLES[kind], "Severity: " + values["severity"], "Bot: " + event.bot_id, "Symbol: " + event.symbol,
             "Event time: " + _utc(event.occurred_at_ms)]
    if event.occurred_at_ms is None:
        lines.append("Observed: " + _utc(event.observed_at_ms))
    if values["runtime_state"] is not None:
        lines.append("Runtime state: " + values["runtime_state"])

    def optional(label, name):
        value = values.get(name)
        if value is not None:
            lines.append(label + ": " + value)

    if kind is _T.PROCESS_STOPPED:
        optional("Stop reason", "stop_reason")
    elif kind in (_T.POSITION_OPEN_CONFIRMED, _T.POSITION_CLOSE_CONFIRMED):
        optional("Previous base quantity", "previous_owned_base_quantity")
        optional("Owned base quantity", "owned_base_quantity")
        if kind is _T.POSITION_OPEN_CONFIRMED:
            lines.append("Exposure confirmed; order may still be pending.")
        optional("Realized trade PnL (quote)", "realized_trade_pnl_quote")
    elif kind is _T.RISK_TRIPPED:
        optional("Trip reason", "risk_trip_reason")
        optional("Risk epoch", "risk_epoch_id")
        lines.append("Trip time: " + _utc(values["tripped_at_ms"]))
        optional("Risk equity (quote)", "risk_equity")
        optional("Daily PnL (quote)", "daily_pnl")
    elif kind is _T.RUNTIME_HALTED:
        optional("Runtime reason", "runtime_reason")
        optional("Owned base quantity", "owned_base_quantity")
        if values.get("pending_action_id") is not None:
            lines.append("Pending action: " + values["pending_action_id"][:12])
        lines.append("Halt time: " + _utc(values["halted_at_ms"]))
    elif kind is _T.RUNTIME_UNCERTAIN:
        lines.append("Order/action outcome may be unknown. Operator review required.")
        optional("Runtime reason", "runtime_reason")
        action = values.get("action_id") or values.get("pending_action_id")
        if action is not None:
            lines.append("Action: " + action[:12])
    elif kind is _T.RUNTIME_REARMED:
        lines.append("Reconciliation still required.")
        lines.append("Rearm time: " + _utc(values["rearmed_at_ms"]))
    elif kind is _T.RISK_REARMED:
        optional("Parent epoch", "parent_epoch_id")
        optional("Child epoch", "child_epoch_id")
        lines.append("Accepted boundary: " + _utc(values["accepted_boundary_ms"]))
        lines.append("Book and capital allocation are unchanged.")
    elif kind is _T.CRITICAL_FAILURE:
        for label, name in (("Operation", "operation"), ("Failure kind", "failure_kind"),
                            ("Exception type", "exception_type"), ("Safe error code", "safe_error_code")):
            optional(label, name)
    lines.append("Event: " + event.event_id[:12])
    message = "\n".join(lines)
    if len(message) > MAX_TELEGRAM_MESSAGE_CHARS:
        raise TelegramError("Telegram message exceeds its safe local bound.")
    return message


class _PrivateHttpDiagnostics(logging.Filter):
    """Library URL diagnostics can contain the Bot API token.

    Suppress this call's HTTP-client diagnostics at their producer, without
    changing logging levels/handlers or filtering another thread's records.
    The filter retains only an integer thread identity, never credentials.
    """

    def __init__(self):
        super().__init__()
        self.thread_id = threading.get_ident()

    def filter(self, record):
        return threading.get_ident() != self.thread_id


@contextmanager
def _private_http_diagnostics():
    guard = _PrivateHttpDiagnostics()
    installed = []
    try:
        for name in ("urllib3.connectionpool", "urllib3.util.retry", "urllib3.poolmanager",
                     "requests.packages.urllib3.connectionpool", "requests.packages.urllib3.util.retry"):
            logger = logging.getLogger(name)
            logger.addFilter(guard)
            installed.append(logger)
        yield
    finally:
        for logger in installed:
            try:
                logger.removeFilter(guard)
            except Exception:
                pass  # Diagnostic cleanup cannot mask an accepted HTTP result.


class TelegramHttpTransport:
    """Fixed-origin sendMessage only, using an explicitly supplied private client.

    Supply a dedicated requests.Session (or the same small interface in tests).
    Environment proxies/auth, cookies, headers and SDK retries are disabled;
    caller owns closing the session. No client is discovered/created implicitly.
    """

    __slots__ = ("_token", "_chat_id", "_session", "_sleeper")

    def __init__(self, bot_token: str, chat_id: str, *, session, sleeper=time.sleep):
        if (type(bot_token) is not str or re.fullmatch(r"[1-9][0-9]{0,19}:[A-Za-z0-9_-]{20,128}", bot_token) is None
                or not callable(sleeper)):
            raise TelegramConfigurationError("Invalid Telegram transport configuration.")
        _chat(chat_id)
        try:
            if not callable(session.post) or session.get_adapter(_ORIGIN + "/bot" + bot_token + "/sendMessage").max_retries.total != 0:
                raise TelegramConfigurationError("A dedicated non-retrying HTTP session is required.")
            session.trust_env = False
            session.auth = None
            session.headers.clear()
            session.cookies.clear()
            session.params.clear()
            session.proxies.clear()
            session.hooks.clear()
            session.verify = True
            session.cert = None
        except Exception:
            raise TelegramConfigurationError("A dedicated non-retrying HTTP session is required.") from None
        self._token, self._chat_id, self._session, self._sleeper = bot_token, chat_id, session, sleeper

    def __repr__(self):
        return "<TelegramHttpTransport>"

    __str__ = __repr__

    @property
    def target_hash(self):
        return _target(self._chat_id)

    def send_message(self, message: str) -> TelegramDeliveryResult:
        if (type(message) is not str or not 1 <= len(message) <= MAX_TELEGRAM_MESSAGE_CHARS
                or "\x00" in message or self._token in message):
            raise TelegramTransportError("Invalid bounded Telegram message.")
        with _private_http_diagnostics():
            return self._send_validated(message)

    def _send_validated(self, message):
        status_type = TelegramDeliveryStatus
        for attempt in range(1, 4):
            response = None
            try:
                response = self._session.post(_ORIGIN + "/bot" + self._token + "/sendMessage",
                    json={"chat_id": self._chat_id, "text": message, "disable_web_page_preview": True},
                    timeout=_TIMEOUT, allow_redirects=False, stream=True)
                status = response.status_code
                if type(status) is not int:
                    return TelegramDeliveryResult(status_type.AMBIGUOUS, attempt)
                if status == 200:
                    raw = response.raw.read(MAX_TELEGRAM_RESPONSE_BYTES + 1, decode_content=True)
                    if type(raw) is not bytes or len(raw) > MAX_TELEGRAM_RESPONSE_BYTES:
                        return TelegramDeliveryResult(status_type.AMBIGUOUS, attempt)
                    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                                       parse_constant=_invalid_constant)
                    if type(value) is not dict or type(value.get("ok")) is not bool:
                        return TelegramDeliveryResult(status_type.AMBIGUOUS, attempt)
                    if value["ok"] is False:
                        return TelegramDeliveryResult(status_type.PERMANENT_FAILURE, attempt)
                    result = value.get("result")
                    message_id = result.get("message_id") if type(result) is dict else None
                    if not _integer(message_id):
                        return TelegramDeliveryResult(status_type.AMBIGUOUS, attempt)
                    return TelegramDeliveryResult(status_type.DELIVERED, attempt, message_id)
                if status != 429 and not 500 <= status <= 599:
                    return TelegramDeliveryResult(status_type.PERMANENT_FAILURE if 400 <= status <= 499
                                                  else status_type.AMBIGUOUS, attempt)
            except Exception:
                # No raw exception/response survives in the normalized result.
                # Ambiguity never authorizes an immediate notification resend.
                return TelegramDeliveryResult(status_type.AMBIGUOUS, attempt)
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass  # Cleanup cannot undo a proven success or hide it.
            if attempt < 3:
                try:
                    self._sleeper(_BACKOFF[attempt - 1])
                except Exception:
                    raise TelegramTransportError("Telegram retry wait failed.") from None
        return TelegramDeliveryResult(status_type.TRANSIENT_FAILURE, 3)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TelegramDeliveryStateError("Duplicate derived JSON field.")
        result[key] = value
    return result


def _invalid_constant(_):
    raise TelegramDeliveryStateError("Invalid derived JSON value.")


@contextmanager
def _state_errors():
    try:
        yield
    except (OSError, ValueError, TypeError, RecursionError):
        raise TelegramDeliveryStateError("Telegram delivery state unavailable or invalid.") from None


def _check_directory(fd):
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode) or value.st_mode & 0o077 or value.st_uid != os.getuid():
        raise TelegramDeliveryStateError("Unsafe Telegram delivery directory.")


def _check_file(fd):
    value = os.fstat(fd)
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
            or value.st_mode & 0o077 or value.st_uid != os.getuid()):
        raise TelegramDeliveryStateError("Unsafe Telegram delivery receipt.")


def _sync_directory(fd):
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TelegramDeliveryStore:
    """Immutable target binding, direct lookups, no scans or trading database.

    Each receipt is exclusively created, written once and fsynced. A crash
    during writing can leave a malformed file; that is a state error, never
    silently treated as either absent or delivered. Concurrent sends can race;
    the first valid receipt wins without being overwritten.
    """

    storage: ObservabilityStorage
    target_hash: str

    def __init__(self, storage: ObservabilityStorage, chat_id: str):
        if type(storage) is not ObservabilityStorage:
            raise TelegramConfigurationError("An existing observability instance is required.")
        object.__setattr__(self, "storage", storage)
        object.__setattr__(self, "target_hash", _target(chat_id))
        with self._directory(create=False):
            pass  # Validate the parent even before any delivery is attempted.

    def __repr__(self):
        return "<TelegramDeliveryStore>"

    __str__ = __repr__

    @property
    def directory(self):
        return self.storage.instance_directory / "telegram-delivery" / self.target_hash

    def validate_event_identity(self, event):
        identity = {name: getattr(event, name) for name in ("broker_id", "account_binding", "bot_id")}
        if hashlib.sha256(_canonical(identity)).hexdigest() != self.storage.instance_name:
            raise TelegramDeliveryStateError("Event belongs to another observability instance.")

    @contextmanager
    def _directory(self, *, create):
        with _state_errors():
            root = self.storage.root
            if (not _digest(self.storage.instance_name) or not _digest(self.target_hash)
                    or self.storage.instance_directory != root / self.storage.instance_name
                    or any(path.is_symlink() for path in (root, *root.parents))):
                raise TelegramDeliveryStateError("Unsafe Telegram delivery path.")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptors = []
            try:
                fd = os.open(root, flags)
                descriptors.append(fd)
                _check_directory(fd)
                for index, name in enumerate((self.storage.instance_name, "telegram-delivery", self.target_hash)):
                    if create and index > 0:
                        try:
                            os.mkdir(name, 0o700, dir_fd=fd)
                            _sync_directory(fd)
                        except FileExistsError:
                            pass
                    try:
                        child = os.open(name, flags, dir_fd=fd)
                    except FileNotFoundError:
                        if not create and index > 0:
                            yield None
                            return
                        raise
                    descriptors.append(child)
                    _check_directory(child)
                    fd = child
                yield fd
            finally:
                for descriptor in reversed(descriptors):
                    os.close(descriptor)

    def _read(self, fd, event_id):
        try:
            file = os.open(event_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        try:
            _check_file(file)
            if not 0 < os.fstat(file).st_size <= MAX_TELEGRAM_RECEIPT_BYTES:
                raise TelegramDeliveryStateError("Invalid bounded Telegram receipt.")
            raw = os.read(file, MAX_TELEGRAM_RECEIPT_BYTES + 1)
        finally:
            os.close(file)
        if len(raw) > MAX_TELEGRAM_RECEIPT_BYTES:
            raise TelegramDeliveryStateError("Invalid bounded Telegram receipt.")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
        if (type(value) is not dict or set(value) != {"version", "event_id", "target_hash", "telegram_message_id", "delivered_at_ms"}
                or type(value["version"]) is not int or value["version"] != TELEGRAM_RECEIPT_VERSION
                or value["event_id"] != event_id or value["target_hash"] != self.target_hash
                or not _integer(value["telegram_message_id"]) or not _integer(value["delivered_at_ms"])
                or raw != _canonical(value)):
            raise TelegramDeliveryStateError("Invalid bound Telegram receipt.")
        return TelegramDeliveryResult(TelegramDeliveryStatus.ALREADY_DELIVERED, 0,
            value["telegram_message_id"], event_id, value["delivered_at_ms"])

    def get_receipt(self, event_id: str) -> TelegramDeliveryResult | None:
        if not _digest(event_id):
            raise TelegramDeliveryStateError("Invalid Telegram receipt reference.")
        with self._directory(create=False) as fd:
            return None if fd is None else self._read(fd, event_id)

    def record_delivery(self, event_id: str, *, telegram_message_id: int, delivered_at_ms: int) -> bool:
        if not _digest(event_id) or not _integer(telegram_message_id) or not _integer(delivered_at_ms):
            raise TelegramDeliveryStateError("Invalid confirmed Telegram receipt fields.")
        data = _canonical({"version": TELEGRAM_RECEIPT_VERSION, "event_id": event_id,
            "target_hash": self.target_hash, "telegram_message_id": telegram_message_id, "delivered_at_ms": delivered_at_ms})
        with self._directory(create=True) as fd:
            try:
                file = os.open(event_id + ".json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                               0o600, dir_fd=fd)
            except FileExistsError:
                if self._read(fd, event_id) is None:
                    raise TelegramDeliveryStateError("Existing Telegram receipt disappeared.")
                return False
            try:
                _check_file(file)
                if os.write(file, data) != len(data):
                    raise TelegramDeliveryStateError("Incomplete Telegram receipt write.")
                os.fsync(file)
            finally:
                os.close(file)
            _sync_directory(fd)
        return True


def _now_ms():
    return time.time_ns() // 1_000_000


def _receipt_fallback():
    try:
        sys.stderr.write("Trading Lab Telegram: delivery confirmed; local receipt unavailable.\n")
    except Exception:
        pass


def deliver_telegram_event(event: ObservabilityEvent, transport: TelegramHttpTransport,
                           receipts: TelegramDeliveryStore, *, utc_now_ms=_now_ms) -> TelegramDeliveryResult:
    event = _event(event)
    if event.event_type not in TELEGRAM_ALERT_EVENT_TYPES:
        return TelegramDeliveryResult(TelegramDeliveryStatus.NOT_ALERTABLE, event_id=event.event_id)
    if (type(transport) is not TelegramHttpTransport or type(receipts) is not TelegramDeliveryStore
            or not callable(utc_now_ms) or transport.target_hash != receipts.target_hash):
        raise TelegramConfigurationError("Telegram delivery bindings do not match.")
    receipts.validate_event_identity(event)
    previous = receipts.get_receipt(event.event_id)
    if previous is not None:
        return previous
    message = render_telegram_message(event)
    outcome = replace(transport.send_message(message), event_id=event.event_id)
    if outcome.status is not TelegramDeliveryStatus.DELIVERED:
        return outcome
    try:
        observed = utc_now_ms()
        receipts.record_delivery(event.event_id, telegram_message_id=outcome.telegram_message_id, delivered_at_ms=observed)
    except Exception:
        _receipt_fallback()
        return replace(outcome, status=TelegramDeliveryStatus.DELIVERED_UNRECORDED)
    return replace(outcome, delivered_at_ms=observed)


def deliver_telegram_events(events: tuple[ObservabilityEvent, ...], transport: TelegramHttpTransport,
                            receipts: TelegramDeliveryStore, *, utc_now_ms=_now_ms) -> tuple[TelegramDeliveryResult, ...]:
    if type(events) is not tuple or len(events) > MAX_TELEGRAM_BATCH_EVENTS:
        raise TelegramError("A bounded tuple of observability events is required.")
    validated = tuple(_event(event) for event in events)
    results = []
    for event in validated:
        result = deliver_telegram_event(event, transport, receipts, utc_now_ms=utc_now_ms)
        results.append(result)
        if result.status not in (TelegramDeliveryStatus.NOT_ALERTABLE, TelegramDeliveryStatus.ALREADY_DELIVERED,
                                 TelegramDeliveryStatus.DELIVERED):
            break
    return tuple(results)
