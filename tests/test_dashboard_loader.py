"""Private synthetic files only; fail closed without repairing local state."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trading_lab.dashboard import *
from trading_lab.dashboard import loader
from tests import test_dashboard_model as f


class DashboardLoaderTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory).resolve() / "observability"
        self.root.mkdir(mode=0o700)
        self.health = f.health_fixture()
        self.event = f.event_fixture()
        self.instance = f.write_instance(self.root, self.health, (self.event,))
        self.log = self.instance / "events-1970-01-01.jsonl"

    def load(self, **changes):
        return load_dashboard(self.root, self.instance.name, **{**dict(now_ms=f.AT), **changes})

    def test_same_loader_model_and_formatting_pipeline_for_two_strategies(self):
        second_health = f.health_fixture(strategy="donchian", symbol="ETHUSDT", bot="bot2")
        second = f.write_instance(self.root, second_health,
            (f.event_fixture(strategy="donchian", symbol="ETHUSDT", bot="bot2"),))
        models = [load_dashboard(self.root, directory.name, now_ms=f.AT) for directory in (self.instance, second)]
        self.assertEqual(type(models[0]), type(models[1]))
        self.assertEqual(models[0].views, models[1].views)
        self.assertEqual(len(models[0].views), 6)
        self.assertEqual(len(event_rows(models[0].events)), len(event_rows(models[1].events)))
        self.assertEqual(models[1].identity.strategy_id, "donchian")
        self.assertEqual(models[1].identity.symbol, "ETHUSDT")
        discovered = discover_instances(self.root)
        self.assertEqual(len(discovered.instances), 2)
        self.assertTrue(any("donchian" in instance.label for instance in discovered.instances))

    def test_empty_root_no_automatic_fixture_or_directory_creation(self):
        empty = self.root / "empty"
        empty.mkdir(mode=0o700)
        self.assertEqual(discover_instances(empty).instances, ())
        missing = self.root / "missing"
        with self.assertRaises(DashboardError):
            discover_instances(missing)
        self.assertFalse(missing.exists())

    def test_invalid_health_candidate_reported_unavailable(self):
        (self.instance / "health.json").write_bytes(b"{}")
        result = discover_instances(self.root)
        self.assertEqual(result.instances, ())
        self.assertEqual(result.notices, (DashboardNotice.CANDIDATE_UNAVAILABLE,))
        with self.assertRaises(DashboardError):
            self.load()

    def test_healthy_candidate_remains_visible_with_invalid_neighbor(self):
        bad = self.root / ("f"*64)
        bad.mkdir(mode=0o700)
        result = discover_instances(self.root)
        self.assertEqual(len(result.instances), 1)
        self.assertEqual(result.notices, (DashboardNotice.CANDIDATE_UNAVAILABLE,))

    def test_discovery_is_direct_only(self):
        hidden = self.root / "nested"
        hidden.mkdir(mode=0o700)
        f.write_instance(hidden, f.health_fixture(bot="bot2"))
        self.assertEqual(len(discover_instances(self.root).instances), 1)

    def test_instance_hash_must_bind_health_identity(self):
        wrong = self.root / ("d"*64)
        self.instance.rename(wrong)
        self.assertEqual(discover_instances(self.root).instances, ())
        with self.assertRaises(DashboardError):
            load_dashboard(self.root, wrong.name, now_ms=f.AT)

    def test_all_event_identity_fields_must_match_snapshot(self):
        for changes in (dict(strategy="donchian"), dict(symbol="ETHUSDT"), dict(bot="bot2")):
            event = f.event_fixture(**changes)
            self.log.write_bytes(event.to_json() + b"\n")
            model = self.load()
            self.assertEqual(model.events, ())
            self.assertIn(DashboardNotice.HISTORY_CORRUPT, model.notices)
            self.assertEqual(model.health, self.health)

    def test_wrong_segment_date_is_not_silently_accepted(self):
        self.log.rename(self.instance / "events-1970-01-02.jsonl")
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_CORRUPT,))

    def test_missing_events_keeps_health_and_incomplete_history(self):
        self.log.unlink()
        model = self.load()
        self.assertEqual(model.health, self.health)
        self.assertEqual(model.events, ())
        self.assertTrue(model.trade_history_incomplete)

    def test_torn_tail_retains_preceding_valid_records_and_warning(self):
        original = self.log.read_bytes()
        self.log.write_bytes(original + b'{"unfinished')
        model = self.load()
        self.assertEqual(model.events, (self.event,))
        self.assertIn(DashboardNotice.TORN_TAIL, model.notices)
        self.assertTrue(model.trade_history_incomplete)
        self.assertEqual(self.log.read_bytes(), original + b'{"unfinished')

    def test_valid_json_without_final_newline_is_still_torn(self):
        self.log.write_bytes(self.event.to_json())
        model = self.load()
        self.assertEqual(model.events, ())
        self.assertEqual(model.notices, (DashboardNotice.TORN_TAIL,))

    def test_invalid_complete_interior_record_discards_history_explicitly(self):
        self.log.write_bytes(self.event.to_json() + b'\n{}\n' + self.event.to_json() + b'\n')
        model = self.load()
        self.assertEqual(model.events, ())
        self.assertEqual(model.notices, (DashboardNotice.HISTORY_CORRUPT,))
        self.assertEqual(model.health, self.health)

    def test_duplicate_event_ids_deduped_not_corruption(self):
        later = replace(self.event, observed_at_ms=f.AT+1)
        self.log.write_bytes(self.event.to_json()+b"\n"+later.to_json()+b"\n")
        model = self.load()
        self.assertEqual(model.events, (later,))
        self.assertEqual(model.notices, ())

    def test_recent_file_window_is_bounded_and_disclosed(self):
        self.log.unlink()
        events = tuple(f.event_fixture(sequence=n, observed=n*86_400_000) for n in range(8))
        f.write_instance(self.root, self.health, events)
        model = self.load()
        self.assertEqual(len(model.events), loader.MAX_EVENT_FILES)
        self.assertEqual(model.events[0].observed_at_ms, 7*86_400_000)
        self.assertIn(DashboardNotice.HISTORY_LIMITED, model.notices)

    def test_record_bound_surfaces_resource_limit_without_partial_success(self):
        self.log.write_bytes((self.event.to_json()+b"\n")*3)
        with patch.object(loader, "MAX_INPUT_RECORDS", 2):
            model = self.load()
        self.assertEqual(model.events, ())
        self.assertEqual(model.notices, (DashboardNotice.HISTORY_RESOURCE_LIMIT,))

    def test_event_file_size_bound_refuses_oversize(self):
        with self.log.open("wb") as stream:
            stream.truncate(loader.MAX_EVENT_FILE_BYTES+1)
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_RESOURCE_LIMIT,))

    def test_total_history_byte_bound_is_explicit(self):
        with patch.object(loader, "MAX_HISTORY_BYTES", 10):
            model = self.load()
        self.assertEqual(model.notices, (DashboardNotice.HISTORY_RESOURCE_LIMIT,))

    def test_health_size_bound_and_missing_health(self):
        file = self.instance / "health.json"
        file.write_bytes(b"x"*(loader.MAX_HEALTH_BYTES+1))
        with self.assertRaises(DashboardError):
            self.load()
        file.unlink()
        with self.assertRaises(DashboardError):
            self.load()

    def test_directory_enumeration_bounds(self):
        with patch.object(loader, "MAX_ROOT_ENTRIES", 0), self.assertRaises(DashboardError):
            discover_instances(self.root)
        with patch.object(loader, "MAX_INSTANCE_ENTRIES", 1):
            self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_RESOURCE_LIMIT,))
        with patch.object(loader, "MAX_INSTANCES", 0), self.assertRaises(DashboardError):
            discover_instances(self.root)

    def test_invalid_history_limits_and_instance_paths(self):
        for limit in (0, -1, True, 1.0, 1001):
            with self.assertRaises(DashboardError):
                self.load(limit=limit)
        for name in ("../escape", "/etc/passwd", "", "f"*65, "../"+self.instance.name):
            with self.assertRaises(DashboardError):
                load_dashboard(self.root, name, now_ms=f.AT)

    def test_root_must_be_explicit_absolute_and_canonical(self):
        for root in (".", "", self.root / ".." / "observability"):
            with self.assertRaises(DashboardError):
                discover_instances(root)

    def test_symlink_root_or_ancestor_refused(self):
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for path in (alias, alias / self.instance.name):
            with self.assertRaises(DashboardError):
                discover_instances(path)

    def test_symlink_instance_refused_not_followed(self):
        alias = self.root / ("e"*64)
        alias.symlink_to(self.instance, target_is_directory=True)
        result = discover_instances(self.root)
        self.assertEqual(len(result.instances), 1)
        self.assertIn(DashboardNotice.CANDIDATE_UNAVAILABLE, result.notices)
        with self.assertRaises(DashboardError):
            load_dashboard(self.root, alias.name, now_ms=f.AT)

    def test_symlink_health_refused(self):
        file = self.instance / "health.json"
        file.unlink()
        file.symlink_to(self.log)
        with self.assertRaises(DashboardError):
            self.load()

    def test_symlink_log_refused_and_target_unchanged(self):
        original = self.log.read_bytes()
        target = self.root / "outside"
        target.write_bytes(original)
        target.chmod(0o600)
        self.log.unlink()
        self.log.symlink_to(target)
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_UNAVAILABLE,))
        self.assertEqual(target.read_bytes(), original)

    def test_fifo_and_hardlinked_logs_refused_without_blocking(self):
        self.log.unlink()
        os.mkfifo(self.log, 0o600)
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_UNAVAILABLE,))
        self.log.unlink()
        self.log.write_bytes(self.event.to_json()+b"\n")
        self.log.chmod(0o600)
        os.link(self.log, self.root / "alias-file")
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_UNAVAILABLE,))

    def test_broad_permissions_refused_without_chmod_repair(self):
        self.log.chmod(0o644)
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_UNAVAILABLE,))
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o644)
        self.instance.chmod(0o755)
        with self.assertRaises(DashboardError):
            self.load()
        self.instance.chmod(0o700)
        self.root.chmod(0o755)
        with self.assertRaises(DashboardError):
            discover_instances(self.root)

    def test_file_substitution_directory_refused(self):
        self.log.unlink()
        self.log.mkdir(mode=0o700)
        self.assertEqual(self.load().notices, (DashboardNotice.HISTORY_UNAVAILABLE,))

    def test_loader_opens_only_readonly_and_changes_no_file_bytes(self):
        files = (self.log, self.instance / "health.json")
        before = tuple((file.read_bytes(), file.stat().st_mtime_ns) for file in files)
        real_open = os.open
        flags_seen = []
        def open_readonly(path, flags, *args, **kwargs):
            flags_seen.append(flags)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(loader.os, "open", side_effect=open_readonly), \
                patch.object(loader.os, "write", side_effect=AssertionError("write forbidden")), \
                patch.object(loader.os, "mkdir", side_effect=AssertionError("mkdir forbidden")):
            discover_instances(self.root)
            self.load()
        self.assertTrue(flags_seen)
        self.assertTrue(all(not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC) for flags in flags_seen))
        self.assertEqual(before, tuple((file.read_bytes(), file.stat().st_mtime_ns) for file in files))

    def test_errors_do_not_echo_raw_paths_or_exception_text(self):
        with patch.object(loader.os, "read", side_effect=OSError("SECRET-PATH-OR-TOKEN")):
            with self.assertRaises(DashboardError) as caught:
                self.load()
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_viewer_time_ages_loaded_health(self):
        model = self.load(now_ms=f.AT+120001)
        self.assertEqual(model.overview.snapshot_freshness.value, "STALE")
        self.assertEqual(model.health.to_json(), self.health.to_json())
