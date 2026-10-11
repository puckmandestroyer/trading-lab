"""Explicit POSIX account lock. No clients, credentials or import-time I/O.

All cooperating launches must use the same operator-configured registry root.
The account hash uses public labels, never credentials. Database/bot choices
cannot select another lock within that registry. The descriptor is authority;
the file is kept after release and contains no metadata.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat

try:
    import fcntl
except ImportError:  # Unsupported platforms fail on acquisition, not import.
    fcntl = None


class RuntimeLockError(RuntimeError):
    """Safe lock/path/lifecycle diagnostic, without OS exception text."""


class RuntimeAccountLock:
    """Acquire before store access; close stores before releasing this lock.

    Root must already exist. Root aliases are resolved to one canonical path;
    generated child directories/files must not be symlinks. This protects
    cooperating local processes, not hostile users replacing trusted directories.
    """

    def __init__(self, registry_root: Path, account_binding: str, *, broker_id: str = "bybit-demo"):
        if broker_id != "bybit-demo" or not isinstance(account_binding, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account_binding):
            raise RuntimeLockError("A Demo broker and safe non-secret account binding are required.")
        try:
            root = Path(registry_root)
            if not root.is_absolute():
                raise RuntimeLockError("Registry root must be explicit and absolute.")
            root = root.resolve(strict=True)
            if not root.is_dir():
                raise RuntimeLockError("Registry root must be an existing directory.")
        except (OSError, TypeError, ValueError):
            raise RuntimeLockError("Cannot resolve registry root.") from None
        self.registry_root = root
        self.account_binding = account_binding
        self.broker_id = broker_id
        identity = json.dumps([broker_id, account_binding], separators=(",", ":"), ensure_ascii=True)
        self.account_key = hashlib.sha256(identity.encode("ascii")).hexdigest()
        self.lock_path = root / "locks" / (self.account_key + ".lock")
        self.database_path = root / "accounts" / self.account_key / "runtime.sqlite3"
        self._fd = None
        self._pid = None
        self._stores = 0
        self._file_identity = None

    def acquire(self) -> "RuntimeAccountLock":
        if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeLockError("POSIX flock and safe file opening are required.")
        if self._fd is not None:
            raise RuntimeLockError("This lock is already acquired.")
        descriptor = None
        try:
            directory = self.lock_path.parent
            if directory.is_symlink():
                raise RuntimeLockError("Lock directory must not be a symlink.")
            directory.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeLockError("Lock must be a regular unaliased file.")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd = descriptor
            self._pid = os.getpid()
            self._file_identity = (info.st_dev, info.st_ino)
            self._assert_held()
            return self
        except (OSError, RuntimeLockError):
            if descriptor is not None:
                os.close(descriptor)
            self._fd = None
            self._pid = None
            self._file_identity = None
            raise RuntimeLockError("Account lock unavailable, held, or unsafe.") from None

    def _assert_held(self):
        if self._fd is None or self._pid != os.getpid():
            raise RuntimeLockError("An acquired lock owned by this process is required.")
        try:
            descriptor = os.fstat(self._fd)
            path = self.lock_path.lstat()
            if not stat.S_ISREG(path.st_mode) or (descriptor.st_dev, descriptor.st_ino) != self._file_identity or self._file_identity != (path.st_dev, path.st_ino) or path.st_nlink != 1:
                raise RuntimeLockError("Account lock file identity changed.")
        except OSError:
            raise RuntimeLockError("Account lock descriptor is unavailable.") from None

    def release(self) -> None:
        # Cleanup uses the original descriptor even if an unrelated process
        # moved the path. It never unlinks or unlocks a replacement file.
        if self._fd is None or self._pid != os.getpid():
            raise RuntimeLockError("An acquired lock owned by this process is required.")
        if self._stores:
            raise RuntimeLockError("Close every store before releasing the account lock.")
        descriptor = self._fd
        self._fd = None
        self._pid = None
        self._file_identity = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            raise RuntimeLockError("Cannot explicitly release account lock.") from None
        finally:
            os.close(descriptor)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
