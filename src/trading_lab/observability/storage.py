"""Bounded local derived files, independent of every trading transaction.

No retention/deletion policy or delivery cursor is implemented. Readers surface
torn tails; they never repair or use these files to recover trading truth.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from ..runtime.store import RuntimeConfiguration, RuntimeStoreError
from .model import (ObservabilityEvent, ObservabilityError, ObservabilityStorageError,
                    ObservabilityValidationError, MAX_EVENT_BYTES, MAX_RETAINED_RECORDS,
                    canonical_bytes, event_from_json, integer, require)
from .health import HealthSnapshot, MAX_HEALTH_BYTES, health_from_json
from .projection import exact

MAX_READ_BYTES = 16_777_216
_FALLBACK = "Trading Lab observability: local output unavailable.\n"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


@contextmanager
def _io_errors():
    try:
        yield
    except (OSError, ValueError, OverflowError, RuntimeStoreError):
        raise ObservabilityStorageError("Local observability storage unavailable or invalid.") from None


def _directory_check(fd):
    info = os.fstat(fd)
    require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o077 and info.st_uid == os.getuid())


def _file_check(fd):
    info = os.fstat(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not info.st_mode & 0o077 and info.st_uid == os.getuid())


def _sync_directory(fd):
    try:
        os.fsync(fd)
    except OSError as error:
        # Some platforms cannot fsync directories. Other durability errors are
        # surfaced; they are not treated as a successful write.
        if error.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


@dataclass(frozen=True, slots=True)
class EventReadResult:
    events: tuple[ObservabilityEvent, ...]
    torn_tail: bool

    def __post_init__(self):
        require(type(self.events) is tuple and len(self.events) <= MAX_RETAINED_RECORDS
                and all(type(event) is ObservabilityEvent for event in self.events)
                and type(self.torn_tail) is bool)

    @property
    def degraded(self):
        return self.torn_tail


@dataclass(frozen=True, slots=True, init=False)
class ObservabilityStorage:
    """One explicitly supplied private local root and hashed instance directory.

    No default runtime session is created. Paths beneath project source,
    notebooks, results or raw data are refused. Directory-relative no-follow
    opens limit path substitution; this is not protection from a hostile OS.
    """

    root: Path
    instance_name: str
    instance_directory: Path
    _identity: tuple[str, str, str]

    def __init__(self, root, configuration: RuntimeConfiguration):
        with _io_errors():
            exact(configuration, RuntimeConfiguration)
            object.__setattr__(self, "_identity", tuple(getattr(configuration, key) for key in ("broker_id", "account_binding", "bot_id")))
            name = hashlib.sha256(canonical_bytes(dict(zip(("broker_id", "account_binding", "bot_id"), self._identity)))).hexdigest()
            path = Path(root).absolute()
            require(not path.is_symlink())
            project = Path(__file__).resolve().parents[3]
            for excluded in (project / "src", project / "notebooks", project / "results", project / "data" / "raw"):
                require(not path.resolve().is_relative_to(excluded))
            # Refuse any symlink ancestor as well as the final component.
            require(all(not parent.is_symlink() for parent in (path, *path.parents)))
            path.mkdir(mode=0o700, exist_ok=True)  # Caller supplies an existing parent.
            object.__setattr__(self, "root", path)
            object.__setattr__(self, "instance_name", name)
            object.__setattr__(self, "instance_directory", path / name)
            fd = os.open(path, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
            try:
                _directory_check(fd)
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=fd)
                try:
                    _directory_check(child)
                finally:
                    os.close(child)
            finally:
                os.close(fd)

    @contextmanager
    def _directory(self):
        # Re-open and verify each time, rather than trusting a path checked once.
        require(all(not parent.is_symlink() for parent in (self.root, *self.root.parents)))
        root_fd = os.open(self.root, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
        try:
            _directory_check(root_fd)
            fd = os.open(self.instance_name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=root_fd)
            try:
                _directory_check(fd)
                yield fd
            finally:
                os.close(fd)
        finally:
            os.close(root_fd)

    def _bound_identity(self, record):
        require(tuple(getattr(record, name) for name in ("broker_id", "account_binding", "bot_id")) == self._identity)

    @staticmethod
    def event_filename(observed_at_ms):
        integer(observed_at_ms)
        try:
            date = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=observed_at_ms)
            return "events-" + date.strftime("%Y-%m-%d") + ".jsonl"
        except (ValueError, OverflowError):
            raise ObservabilityStorageError("Observation date is outside local storage range.") from None

    def append_event(self, event: ObservabilityEvent):
        with _io_errors():
            exact(event, ObservabilityEvent)
            self._bound_identity(event)
            data = event.to_json() + b"\n"
            filename = self.event_filename(event.observed_at_ms)
            with self._directory() as directory:
                fd = os.open(filename, os.O_RDWR | os.O_APPEND | os.O_CREAT | _NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
                try:
                    _file_check(fd)
                    size = os.fstat(fd).st_size
                    # Never append behind a crash-torn line: that would make an
                    # invalid interior record and hide the original boundary.
                    require(size == 0 or os.pread(fd, 1, size - 1) == b"\n")
                    require(os.write(fd, data) == len(data))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                _sync_directory(directory)

    def _read(self, directory, filename, maximum):
        fd = os.open(filename, os.O_RDONLY | _NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            _file_check(fd)
            require(os.fstat(fd).st_size <= maximum)
            parts, remaining = [], maximum + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 65_536))
                if not chunk:
                    break
                parts.append(chunk)
                remaining -= len(chunk)
            data = b"".join(parts)
            require(len(data) <= maximum)
            return data
        finally:
            os.close(fd)

    def read_events(self, filename: str, *, max_records: int, max_bytes: int) -> EventReadResult:
        with _io_errors():
            require(type(filename) is str and re.fullmatch(r"events-\d{4}-\d{2}-\d{2}\.jsonl", filename) is not None)
            integer(max_records, 1)
            integer(max_bytes, 1)
            require(max_records <= MAX_RETAINED_RECORDS and max_bytes <= MAX_READ_BYTES)
            with self._directory() as directory:
                data = self._read(directory, filename, max_bytes)
            lines = data.split(b"\n")
            torn = bool(lines[-1])
            complete = lines[:-1]
            require(len(complete) <= max_records)
            events = []
            for line in complete:
                require(0 < len(line) <= MAX_EVENT_BYTES)
                event = event_from_json(line)
                self._bound_identity(event)
                events.append(event)
            require(not torn or len(lines[-1]) <= MAX_EVENT_BYTES)
            return EventReadResult(tuple(events), torn)

    def write_health(self, snapshot: HealthSnapshot):
        with _io_errors():
            exact(snapshot, HealthSnapshot)
            self._bound_identity(snapshot)
            data = snapshot.to_json()
            with self._directory() as directory:
                try:
                    info = os.stat("health.json", dir_fd=directory, follow_symlinks=False)
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                            and not info.st_mode & 0o077 and info.st_uid == os.getuid())
                except FileNotFoundError:
                    pass
                temporary = ".health-" + uuid.uuid4().hex + ".tmp"
                created = False
                replaced = False
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600, dir_fd=directory)
                    created = True
                    try:
                        _file_check(fd)
                        require(os.write(fd, data) == len(data))
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.replace(temporary, "health.json", src_dir_fd=directory, dst_dir_fd=directory)
                    replaced = True
                    _sync_directory(directory)
                finally:
                    if created and not replaced:
                        try:
                            os.unlink(temporary, dir_fd=directory)
                        except OSError:
                            pass

    def read_health(self) -> HealthSnapshot:
        with _io_errors():
            with self._directory() as directory:
                data = self._read(directory, "health.json", MAX_HEALTH_BYTES)
            snapshot = health_from_json(data)
            self._bound_identity(snapshot)
            return snapshot


def _fallback():
    try:
        sys.stderr.write(_FALLBACK)
    except Exception:
        pass  # One bounded attempt; never recursively log the fallback.


def safe_append_event(storage: ObservabilityStorage, event: ObservabilityEvent) -> bool:
    try:
        storage.append_event(event)
        return True
    except ObservabilityError:
        _fallback()
        return False


def safe_write_health(storage: ObservabilityStorage, snapshot: HealthSnapshot) -> bool:
    try:
        storage.write_health(snapshot)
        return True
    except ObservabilityError:
        _fallback()
        return False
