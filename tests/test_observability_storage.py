"""Private temporary local files, atomic replacement and bounded fault paths."""

from dataclasses import FrozenInstanceError, replace
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from unittest.mock import patch

from trading_lab.observability import *
from trading_lab.observability import storage as s
from tests import test_runtime_store as fixtures

RUN = "0"*32
DAY = 86_400_000


class StorageTests(fixtures.RiskPersistenceCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.directory).resolve() / "observability"
        self.output = ObservabilityStorage(self.root, self.config)
        self.event = process_started(self.config, run_id=RUN, observed_at_ms=DAY,
                                     process_started_at_ms=0)
        self.filename = self.output.event_filename(self.event.observed_at_ms)
        self.file = self.output.instance_directory / self.filename

    def snapshot(self, at=DAY):
        return build_health_snapshot(self.store, run_id=RUN, process_started_at_ms=0, generated_at_ms=at)

    def read(self, **bounds):
        return self.output.read_events(self.filename, **{"max_records": 10, "max_bytes": 100_000, **bounds})

    def test_hashed_identity_path_is_deterministic_and_separate(self):
        payload = {"broker_id": "bybit-demo", "account_binding": "research", "bot_id": "bot1"}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(self.output.instance_name, expected)
        self.assertNotIn("research", str(self.output.instance_directory))
        self.assertEqual(ObservabilityStorage(self.root, self.config).instance_directory, self.output.instance_directory)
        other = ObservabilityStorage(self.root, replace(self.config, bot_id="bot2"))
        self.assertNotEqual(other.instance_directory, self.output.instance_directory)

    def test_storage_binding_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.output.instance_name = "../escape"

    def test_protected_project_directories_refused_before_creation(self):
        root = Path(s.__file__).resolve().parents[3]
        for path in (root/"src"/"never-created", root/"notebooks"/"never-created",
                     root/"results"/"never-created", root/"data"/"raw"/"never-created"):
            with self.subTest(path=path), self.assertRaises(ObservabilityStorageError):
                ObservabilityStorage(path, self.config)
            self.assertFalse(path.exists())

    def test_success_helpers_true(self):
        self.assertTrue(safe_append_event(self.output, self.event))
        self.assertTrue(safe_write_health(self.output, self.snapshot()))

    def test_observation_utc_date_not_occurrence(self):
        self.assertEqual(self.filename, "events-1970-01-02.jsonl")
        self.assertEqual(self.output.event_filename(DAY-1), "events-1970-01-01.jsonl")
        self.assertEqual(self.output.event_filename(DAY), "events-1970-01-02.jsonl")
        self.output.append_event(self.event)
        event, = self.read().events
        self.assertEqual(event.occurred_at_ms, 0)
        self.assertEqual(event.observed_at_ms, DAY)

    def test_two_appends_duplicates_surface_canonical_lines(self):
        self.output.append_event(self.event)
        self.output.append_event(self.event)
        self.assertEqual(self.file.read_bytes(), (self.event.to_json()+b"\n")*2)
        result = self.read()
        self.assertEqual(result.events, (self.event, self.event))
        self.assertFalse(result.degraded)

    def test_empty_file_empty_events_not_degraded(self):
        self.file.touch(mode=0o600)
        self.assertEqual(self.read(), EventReadResult((), False))

    def test_user_only_permissions(self):
        self.output.append_event(self.event)
        self.output.write_health(self.snapshot())
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.output.instance_directory.stat().st_mode), 0o700)
        for file in (self.file, self.output.instance_directory / "health.json"):
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_append_and_health_fsync_file_and_directory(self):
        with patch.object(s.os, "fsync", wraps=os.fsync) as sync:
            self.output.append_event(self.event)
            self.assertEqual(sync.call_count, 2)
        with patch.object(s.os, "fsync", wraps=os.fsync) as sync:
            self.output.write_health(self.snapshot())
            self.assertEqual(sync.call_count, 2)

    def test_torn_final_line_not_accepted_even_complete_json(self):
        self.output.append_event(self.event)
        with self.file.open("ab") as stream:
            stream.write(self.event.to_json())
        result = self.read()
        self.assertEqual(result.events, (self.event,))
        self.assertTrue(result.torn_tail)
        self.assertTrue(result.degraded)

    def test_only_torn_tail_returns_no_events(self):
        self.file.write_bytes(b'{"event')
        self.file.chmod(0o600)
        self.assertEqual(self.read(), EventReadResult((), True))

    def test_append_refuses_to_hide_torn_tail(self):
        self.file.write_bytes(b'{"event')
        self.file.chmod(0o600)
        before = self.file.read_bytes()
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(self.event)
        self.assertEqual(self.file.read_bytes(), before)

    def test_invalid_complete_interior_line_fails_whole_read(self):
        self.output.append_event(self.event)
        with self.file.open("ab") as stream:
            stream.write(b'{"invalid":true}\n' + self.event.to_json()+b"\n")
        with self.assertRaises(ObservabilityStorageError):
            self.read()

    def test_read_record_and_byte_bounds_reject_prefix(self):
        self.output.append_event(self.event)
        self.output.append_event(self.event)
        for bounds in ({"max_records":1}, {"max_bytes":1}, {"max_records":0}, {"max_records":True},
                       {"max_records":s.MAX_RETAINED_RECORDS+1}, {"max_bytes":s.MAX_READ_BYTES+1}):
            with self.subTest(bounds=bounds), self.assertRaises(ObservabilityStorageError):
                self.read(**bounds)

    def test_read_requires_explicit_bounds(self):
        with self.assertRaises(TypeError):
            self.output.read_events(self.filename)

    def test_path_escape_and_special_filename_rejected(self):
        for filename in ("../health.json", "health.json", "/etc/passwd", "events-1970-01-02.jsonl/../x"):
            with self.subTest(filename=filename), self.assertRaises(ObservabilityStorageError):
                self.output.read_events(filename, max_records=1, max_bytes=100)

    def test_symlink_root_and_non_directory_rejected(self):
        link = self.root.parent / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ObservabilityStorageError):
            ObservabilityStorage(link, self.config)
        file = self.root.parent / "plain"
        file.touch(mode=0o600)
        with self.assertRaises(ObservabilityStorageError):
            ObservabilityStorage(file, self.config)

    def test_symlink_instance_rejected_after_construction(self):
        instance = self.output.instance_directory
        instance.rmdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        instance.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(self.event)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_symlink_files_rejected_no_target_mutation(self):
        target = self.root / "target"
        target.write_bytes(b"original")
        target.chmod(0o600)
        for file in (self.file, self.output.instance_directory/"health.json"):
            file.symlink_to(target)
        for operation in (lambda: self.output.append_event(self.event), lambda: self.output.write_health(self.snapshot()),
                          lambda: self.output.read_health(), self.read):
            with self.assertRaises(ObservabilityStorageError):
                operation()
        self.assertEqual(target.read_bytes(), b"original")

    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.file, 0o600)
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(self.event)
        with self.assertRaises(ObservabilityStorageError):
            self.read()

    def test_hardlinked_file_rejected(self):
        self.output.append_event(self.event)
        os.link(self.file, self.root/"other-link")
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(self.event)

    def test_existing_wide_permissions_refused_not_loosened_or_repaired(self):
        self.output.append_event(self.event)
        self.file.chmod(0o644)
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(self.event)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        self.root.chmod(0o755)
        with self.assertRaises(ObservabilityStorageError):
            ObservabilityStorage(self.root, self.config)

    def test_other_instance_event_and_snapshot_rejected(self):
        cfg = replace(self.config, bot_id="bot2")
        event = process_started(cfg, run_id=RUN, observed_at_ms=DAY, process_started_at_ms=0)
        with self.assertRaises(ObservabilityStorageError):
            self.output.append_event(event)
        with self.assertRaises(ObservabilityStorageError):
            self.output.write_health(replace(self.snapshot(), bot_id="bot2"))

    def test_health_atomic_reader_observes_old_then_new(self):
        old, new = self.snapshot(), self.snapshot(DAY+1)
        self.output.write_health(old)
        real_replace = os.replace
        observed = []
        def replace_and_observe(*args, **kwargs):
            observed.append(self.output.read_health())
            real_replace(*args, **kwargs)
            observed.append(self.output.read_health())
        with patch.object(s.os, "replace", side_effect=replace_and_observe):
            self.output.write_health(new)
        self.assertEqual(observed, [old, new])
        self.assertEqual(list(self.output.instance_directory.glob("*.tmp")), [])

    def test_pre_replace_failure_retains_old_and_cleans_only_own_temp(self):
        old = self.snapshot()
        self.output.write_health(old)
        orphan = self.output.instance_directory/".health-orphan.tmp"
        orphan.write_text("unrelated")
        with patch.object(s.os, "replace", side_effect=OSError(errno.EIO, "synthetic-secret")):
            with self.assertRaises(ObservabilityStorageError):
                self.output.write_health(self.snapshot(DAY+1))
        self.assertEqual(self.output.read_health(), old)
        self.assertEqual(list(self.output.instance_directory.glob("*.tmp")), [orphan])

    def test_crash_orphan_ignored_by_health_reader(self):
        self.output.write_health(self.snapshot())
        (self.output.instance_directory/".health-crash.tmp").write_bytes(b"half")
        self.assertEqual(self.output.read_health(), self.snapshot())

    def test_health_missing_malformed_oversized_unavailable(self):
        with self.assertRaises(ObservabilityStorageError):
            self.output.read_health()
        file = self.output.instance_directory/"health.json"
        for data in (b"", b"{", b"{}", b"x"*(s.MAX_HEALTH_BYTES+1)):
            file.write_bytes(data)
            file.chmod(0o600)
            with self.subTest(size=len(data)), self.assertRaises(ObservabilityStorageError):
                self.output.read_health()

    def test_post_replace_sync_failure_still_complete_snapshot(self):
        snapshot = self.snapshot()
        with patch.object(s, "_sync_directory", side_effect=OSError(errno.EIO, "synthetic")):
            with self.assertRaises(ObservabilityStorageError):
                self.output.write_health(snapshot)
        self.assertEqual(self.output.read_health(), snapshot)

    def test_unsupported_directory_fsync_only_is_tolerated(self):
        with patch.object(s.os, "fsync", side_effect=OSError(errno.EINVAL, "unsupported")):
            s._sync_directory(1)
        with patch.object(s.os, "fsync", side_effect=OSError(errno.EIO, "bad")):
            with self.assertRaises(OSError):
                s._sync_directory(1)

    def test_append_disk_failure_one_safe_fallback_without_secret(self):
        stream = io.StringIO()
        with patch.object(s.os, "write", side_effect=OSError(errno.ENOSPC, "synthetic-secret")) as write, patch.object(s.sys, "stderr", stream):
            self.assertFalse(safe_append_event(self.output, self.event))
            self.assertEqual(write.call_count, 1)
        self.assertEqual(stream.getvalue().count("\n"), 1)
        self.assertNotIn("synthetic", stream.getvalue())

    def test_health_disk_failure_one_fallback_no_recursion(self):
        with patch.object(self.output.__class__, "write_health", side_effect=ObservabilityStorageError("fixed")) as write, \
                patch.object(s.sys.stderr, "write", side_effect=OSError("synthetic-secret")) as fallback:
            self.assertFalse(safe_write_health(self.output, self.snapshot()))
            self.assertEqual(write.call_count, 1)
            self.assertEqual(fallback.call_count, 1)

    def test_unrelated_trading_exception_is_not_swallowed(self):
        with patch.object(self.output.__class__, "append_event", side_effect=RuntimeError("trading failure")):
            with self.assertRaisesRegex(RuntimeError, "trading failure"):
                safe_append_event(self.output, self.event)

    def test_short_append_surfaces_failure_and_torn_tail(self):
        real_write = os.write
        with patch.object(s.os, "write", side_effect=lambda fd, data: real_write(fd, data[:10])):
            with self.assertRaises(ObservabilityStorageError):
                self.output.append_event(self.event)
        self.assertTrue(self.read().torn_tail)

    def test_artifact_deletion_does_not_change_trading_truth(self):
        self.activate()
        before = self.store.get_checkpoint(), self.store.list_actions(), self.store.list_risk_valuations()
        self.output.append_event(self.event)
        self.output.write_health(self.snapshot())
        self.file.unlink()
        (self.output.instance_directory/"health.json").unlink()
        self.assertEqual(before, (self.store.get_checkpoint(), self.store.list_actions(), self.store.list_risk_valuations()))
        self.assertFalse(self.store._connection.in_transaction)
