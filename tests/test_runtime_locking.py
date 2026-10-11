"""Actual nonblocking POSIX exclusion, process death and safe descriptor lifetime."""

import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
import trading_lab.runtime.locking as module


ROOT = Path(__file__).resolve().parents[1]
ENV = {"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
CONTENDER = """
from pathlib import Path
import sys
from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
try:
    with RuntimeAccountLock(Path(sys.argv[1]), sys.argv[2]):
        print('ACQUIRED', flush=True)
except RuntimeLockError:
    print('BLOCKED', flush=True)
"""
HOLDER = """
from pathlib import Path
import sys
from trading_lab.runtime.locking import RuntimeAccountLock
with RuntimeAccountLock(Path(sys.argv[1]), sys.argv[2]):
    print('HELD', flush=True)
    sys.stdin.readline()
"""


class RuntimeLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.root = Path(self.directory)

    def contender(self, account="research"):
        result = subprocess.run([sys.executable, "-c", CONTENDER, str(self.root), account],
                                cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.strip()

    def holder(self):
        child = subprocess.Popen([sys.executable, "-c", HOLDER, str(self.root), "research"],
                                 cwd=ROOT, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        def cleanup():
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        ready, _, _ = select.select([child.stdout], [], [], 10)
        self.assertTrue(ready, "Child lock holder did not become ready")
        self.assertEqual(child.stdout.readline().strip(), "HELD")
        return child

    def test_first_lock_acquires_and_persistent_file_contains_no_metadata(self):
        with RuntimeAccountLock(self.root, "research") as lock:
            lock._assert_held()
            self.assertEqual(lock.lock_path.read_bytes(), b"")
            self.assertEqual(lock.lock_path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(lock.lock_path.exists())

    def test_second_independent_descriptor_fails_immediately(self):
        with RuntimeAccountLock(self.root, "research"):
            with self.assertRaises(RuntimeLockError):
                RuntimeAccountLock(self.root, "research").acquire()

    def test_second_process_is_blocked_without_wait_or_network(self):
        with RuntimeAccountLock(self.root, "research"):
            self.assertEqual(self.contender(), "BLOCKED")

    def test_release_allows_later_process(self):
        with RuntimeAccountLock(self.root, "research"):
            self.assertEqual(self.contender(), "BLOCKED")
        self.assertEqual(self.contender(), "ACQUIRED")

    def test_process_death_naturally_releases_lock(self):
        child = self.holder()
        with self.assertRaises(RuntimeLockError):
            RuntimeAccountLock(self.root, "research").acquire()
        child.terminate()
        child.wait(timeout=10)
        self.assertEqual(self.contender(), "ACQUIRED")

    def test_process_context_exit_releases_lock(self):
        child = self.holder()
        child.communicate(input="stop\n", timeout=10)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(self.contender(), "ACQUIRED")

    def test_file_existence_without_held_flock_does_not_block(self):
        lock = RuntimeAccountLock(self.root, "research")
        lock.lock_path.parent.mkdir()
        lock.lock_path.write_text("stale diagnostic text")
        with lock:
            lock._assert_held()
        self.assertEqual(lock.lock_path.read_text(), "stale diagnostic text")

    def test_closing_owner_descriptor_releases_os_ownership(self):
        lock = RuntimeAccountLock(self.root, "research").acquire()
        os.close(lock._fd)
        with self.assertRaises(RuntimeLockError):
            lock._assert_held()
        lock._fd = None
        self.assertEqual(self.contender(), "ACQUIRED")

    def test_different_accounts_have_independent_locks(self):
        with RuntimeAccountLock(self.root, "research") as first:
            with RuntimeAccountLock(self.root, "other") as second:
                self.assertNotEqual(first.lock_path, second.lock_path)
                self.assertNotEqual(first.database_path, second.database_path)

    def test_account_scope_does_not_depend_on_bot_or_database_options(self):
        first = RuntimeAccountLock(self.root, "research")
        second = RuntimeAccountLock(self.root, "research")
        self.assertEqual(first.lock_path, second.lock_path)
        self.assertEqual(first.account_key, second.account_key)
        with self.assertRaises(TypeError):
            RuntimeAccountLock(self.root, "research", bot_id="other")
        with self.assertRaises(TypeError):
            RuntimeAccountLock(self.root, "research", database_path=self.root / "other.db")

    def test_root_alias_resolves_to_same_lock(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        first = RuntimeAccountLock(self.root, "research")
        second = RuntimeAccountLock(alias, "research")
        self.assertEqual(first.lock_path, second.lock_path)
        with first:
            with self.assertRaises(RuntimeLockError):
                second.acquire()

    def test_relative_or_missing_root_fails_without_creation(self):
        for root in (Path("relative"), self.root / "missing"):
            with self.subTest(root=root), self.assertRaises(RuntimeLockError):
                RuntimeAccountLock(root, "research")
        self.assertFalse((self.root / "missing").exists())

    def test_unsafe_account_names_and_non_demo_broker_fail(self):
        for account in ("", "../escape", "a/b", " a", None, "x"*65):
            with self.subTest(account=account), self.assertRaises(RuntimeLockError):
                RuntimeAccountLock(self.root, account)
        with self.assertRaises(RuntimeLockError):
            RuntimeAccountLock(self.root, "research", broker_id="live")

    def test_lock_path_does_not_embed_account_binding(self):
        lock = RuntimeAccountLock(self.root, "research")
        self.assertNotIn("research", lock.lock_path.name)
        self.assertEqual(len(lock.account_key), 64)

    def test_repeated_acquire_rejects_instead_of_losing_descriptor(self):
        with RuntimeAccountLock(self.root, "research") as lock:
            descriptor = lock._fd
            with self.assertRaises(RuntimeLockError):
                lock.acquire()
            self.assertEqual(lock._fd, descriptor)
            lock._assert_held()

    def test_exception_in_context_releases_without_unlink(self):
        lock = RuntimeAccountLock(self.root, "research")
        with self.assertRaises(ValueError):
            with lock:
                raise ValueError("Synthetic caller failure")
        self.assertTrue(lock.lock_path.exists())
        self.assertEqual(self.contender(), "ACQUIRED")

    def test_unavailable_fcntl_fails_closed(self):
        with patch.object(module, "fcntl", None), self.assertRaises(RuntimeLockError):
            RuntimeAccountLock(self.root, "research").acquire()

    def test_symlink_lock_file_fails_without_following(self):
        lock = RuntimeAccountLock(self.root, "research")
        lock.lock_path.parent.mkdir()
        target = self.root / "unrelated"
        target.write_text("preserve")
        lock.lock_path.symlink_to(target)
        with self.assertRaises(RuntimeLockError):
            lock.acquire()
        self.assertEqual(target.read_text(), "preserve")

    def test_symlink_lock_directory_fails(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.root / "locks").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(RuntimeLockError):
            RuntimeAccountLock(self.root, "research").acquire()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_hardlink_lock_file_fails(self):
        lock = RuntimeAccountLock(self.root, "research")
        lock.lock_path.parent.mkdir()
        target = self.root / "alias"
        target.touch()
        os.link(target, lock.lock_path)
        with self.assertRaises(RuntimeLockError):
            lock.acquire()

    def test_inherited_descriptor_cannot_be_used_by_a_different_process(self):
        with RuntimeAccountLock(self.root, "research") as lock:
            with patch.object(module.os, "getpid", return_value=os.getpid() + 1), self.assertRaises(RuntimeLockError):
                lock._assert_held()

    def test_replaced_lock_path_blocks_access_but_releases_original_descriptor(self):
        lock = RuntimeAccountLock(self.root, "research").acquire()
        lock.lock_path.rename(lock.lock_path.with_name("original.lock"))
        lock.lock_path.write_text("replacement")
        with self.assertRaises(RuntimeLockError):
            lock._assert_held()
        lock.release()
        self.assertEqual(lock.lock_path.read_text(), "replacement")

    def test_import_has_no_filesystem_environment_or_network_effect(self):
        code = """
from unittest.mock import patch
import os, socket
with patch('os.open', side_effect=AssertionError('No file opening')), \\
     patch('os.getenv', side_effect=AssertionError('No environment')), \\
     patch('socket.create_connection', side_effect=AssertionError('No network')):
    import trading_lab.runtime.locking, trading_lab.runtime.store
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=ENV,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
