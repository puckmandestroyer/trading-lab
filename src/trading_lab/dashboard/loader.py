"""Bounded local read-only access; no storage constructor or trading database.

Directories are opened component by component without following symlinks.
Only health.json and directly named UTC JSONL segments are read. No repair,
permission change, directory creation or retention policy is performed.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat

from ..observability.health import MAX_HEALTH_BYTES, health_from_json
from ..observability.model import MAX_EVENT_BYTES, ObservabilityError, event_from_json
from .analytics import build_dashboard_model, instance_name, IDENTITY_FIELDS, MAX_INPUT_RECORDS
from .formatting import format_timestamp
from .model import (DashboardError, DashboardNotice, DashboardInstance, DashboardDiscovery,
                    DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT, SNAPSHOT_MAX_AGE_MS)

MAX_ROOT_ENTRIES = 256
MAX_INSTANCES = 64
MAX_INSTANCE_ENTRIES = 4096
MAX_EVENT_FILES = 7
MAX_EVENT_FILE_BYTES = 4 * 1024 * 1024
MAX_HISTORY_BYTES = 8 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_EVENT_NAME = re.compile(r"events-\d{4}-\d{2}-\d{2}\.jsonl", re.ASCII)


class _HistoryCorrupt(DashboardError):
    pass


class _ResourceLimit(DashboardError):
    pass


def _private_directory(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise DashboardError("Observability directory unavailable or unsafe.")


@contextmanager
def _root_directory(root):
    descriptors = []
    try:
        path = Path(root)
        if not path.is_absolute() or len(str(path)) > 4096 or ".." in path.parts:
            raise DashboardError("An explicit absolute observability root is required.")
        fd = os.open(path.anchor, _DIRECTORY_FLAGS)
        descriptors.append(fd)
        for part in path.parts[1:]:
            fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            descriptors.append(fd)
        _private_directory(fd)
        yield fd
    except (OSError, ValueError, TypeError):
        raise DashboardError("Observability root unavailable or unsafe.") from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


@contextmanager
def _instance_directory(root_fd, name):
    if type(name) is not str or re.fullmatch(r"[0-9a-f]{64}", name) is None:
        raise DashboardError("Invalid observability instance reference.")
    fd = None
    try:
        fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_fd)
        _private_directory(fd)
        yield fd
    except (OSError, ValueError):
        raise DashboardError("Observability instance unavailable or unsafe.") from None
    finally:
        if fd is not None:
            os.close(fd)


def _entries(fd, maximum):
    names = []
    with os.scandir(fd) as entries:
        for entry in entries:
            if len(names) == maximum:
                raise _ResourceLimit("Observability directory exceeds its display bound.")
            names.append(entry.name)
    return tuple(names)


def _read(fd, name, maximum):
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(file_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise DashboardError("Observability file unavailable or unsafe.")
        if info.st_size > maximum:
            raise _ResourceLimit("Observability file exceeds its display bound.")
        chunks, remaining = [], maximum + 1
        while remaining:
            part = os.read(file_fd, min(remaining, 65_536))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise _ResourceLimit("Observability file exceeds its display bound.")
        return data
    finally:
        os.close(file_fd)


def _health(fd, name):
    health = health_from_json(_read(fd, "health.json", MAX_HEALTH_BYTES))
    if instance_name(health) != name:
        raise DashboardError("Observability instance identity mismatch.")
    return health


def discover_instances(root):
    """Only direct candidates, bounded and validated; no raw path diagnostics."""
    instances, notices = [], []
    with _root_directory(root) as fd:
        names = _entries(fd, MAX_ROOT_ENTRIES)
        candidates = sorted(name for name in names if re.fullmatch(r"[0-9a-f]{64}", name))
        if len(candidates) > MAX_INSTANCES:
            raise DashboardError("Too many observability instances for this dashboard.")
        for name in candidates:
            try:
                with _instance_directory(fd, name) as instance_fd:
                    health = _health(instance_fd, name)
                instances.append(DashboardInstance(name, *(getattr(health, key) for key in IDENTITY_FIELDS)))
            except (DashboardError, OSError, ObservabilityError):
                notices.append(DashboardNotice.CANDIDATE_UNAVAILABLE)
    return DashboardDiscovery(tuple(sorted(instances, key=lambda instance: (instance.label, instance.instance_name))),
                              tuple(dict.fromkeys(notices)))


def _history(fd, health):
    files = sorted((name for name in _entries(fd, MAX_INSTANCE_ENTRIES) if _EVENT_NAME.fullmatch(name)), reverse=True)
    notices = [DashboardNotice.HISTORY_LIMITED] if len(files) > MAX_EVENT_FILES else []
    events, total = [], 0
    for filename in files[:MAX_EVENT_FILES]:
        allowance = min(MAX_EVENT_FILE_BYTES, MAX_HISTORY_BYTES - total)
        if allowance <= 0:
            raise _ResourceLimit("Observability history exceeds its display bound.")
        data = _read(fd, filename, allowance)
        total += len(data)
        lines = data.split(b"\n")
        if lines[-1]:
            if len(lines[-1]) > MAX_EVENT_BYTES:
                raise _ResourceLimit("Observability record exceeds its display bound.")
            notices.append(DashboardNotice.TORN_TAIL)
        for line in lines[:-1]:
            if len(events) == MAX_INPUT_RECORDS:
                raise _ResourceLimit("Observability record count exceeds its display bound.")
            try:
                event = event_from_json(line)
            except ObservabilityError:
                raise _HistoryCorrupt("Invalid complete observability event.") from None
            if (tuple(getattr(event, key) for key in IDENTITY_FIELDS)
                    != tuple(getattr(health, key) for key in IDENTITY_FIELDS)
                    or format_timestamp(event.observed_at_ms)[:10] != filename[7:17]):
                raise _HistoryCorrupt("Observability event identity or segment mismatch.")
            events.append(event)
    return tuple(events), tuple(dict.fromkeys(notices))


def load_dashboard(root, instance, *, now_ms, limit=DEFAULT_HISTORY_LIMIT,
                   snapshot_max_age_ms=SNAPSHOT_MAX_AGE_MS):
    """Load one explicit hashed instance; history failure never invents health."""
    if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise DashboardError("Invalid dashboard history limit.")
    try:
        with _root_directory(root) as root_fd, _instance_directory(root_fd, instance) as fd:
            health = _health(fd, instance)
            try:
                events, notices = _history(fd, health)
            except _HistoryCorrupt:
                events, notices = (), (DashboardNotice.HISTORY_CORRUPT,)
            except _ResourceLimit:
                events, notices = (), (DashboardNotice.HISTORY_RESOURCE_LIMIT,)
            except (DashboardError, ObservabilityError, OSError):
                events, notices = (), (DashboardNotice.HISTORY_UNAVAILABLE,)
        return build_dashboard_model(health, events, now_ms=now_ms, limit=limit,
                                     snapshot_max_age_ms=snapshot_max_age_ms, notices=notices)
    except (ObservabilityError, OSError):
        raise DashboardError("Observability data unavailable or invalid.") from None
