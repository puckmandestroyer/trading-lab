"""No real launchctl invocation: plist/temp-file tests and fake process results."""

from dataclasses import replace
import io
import os
from pathlib import Path
import plistlib
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from trading_lab.operator import launchd as m
from tests.test_operator_demo_runtime import PrivateCase


def job_output(body):
    """Sanitized launchctl outer job with the observed tab-per-scope layout."""
    return ("gui/" + str(os.getuid()) + "/" + m.LABEL + " = {\n"
            + "\n".join("\t" + line for line in body.splitlines()) + "\n}\n")


class LaunchdTests(PrivateCase):
    def setUp(self):
        super().setUp()
        self.agent = m.LaunchAgentConfiguration(self.config, Path("/usr/bin/python3"), self.root / "operator")
        self.runner = Mock(return_value=m.LaunchctlResult(0, job_output("state = not running\nlast exit code = 0")))
        self.manager = m.LaunchAgentManager(self.agent, runner=self.runner)
        self.home = self.root / "home"
        (self.home / "Library").mkdir(parents=True, mode=0o700)
        self.enterContext(patch.object(m.Path, "home", return_value=self.home))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("NETWORK")))

    def parsed(self):
        return plistlib.loads(m.generate_plist(self.agent))

    def installed(self):
        m.write_launchagent(self.agent)
        directory = self.home / "Library/LaunchAgents"
        directory.mkdir(mode=0o700)
        path = directory / (m.LABEL + ".plist")
        path.write_bytes(m.generate_plist(self.agent))
        path.chmod(0o600)
        return path

    def test_plist_required_fields(self):
        plist = self.parsed()
        self.assertEqual(plist["Label"], m.LABEL)
        self.assertEqual(plist["WorkingDirectory"], str(m.PROJECT_ROOT))
        self.assertEqual(plist["ProcessType"], "Background")

    def test_no_keepalive(self):
        self.assertIs(self.parsed()["KeepAlive"], False)

    def test_no_runatload(self):
        self.assertIs(self.parsed()["RunAtLoad"], False)

    def test_no_restart_or_repetition_keys(self):
        self.assertFalse(set(self.parsed()) & {"StartInterval", "StartCalendarInterval", "ThrottleInterval",
            "SuccessfulExit", "WatchPaths", "QueueDirectories", "MachServices", "Sockets"})

    def test_program_arguments_sequence_not_shell(self):
        arguments = self.parsed()["ProgramArguments"]
        self.assertIs(type(arguments), list)
        self.assertEqual(arguments[0], "/usr/bin/python3")
        self.assertNotIn("sh", arguments)
        self.assertIn("--start-next-hour", arguments)
        self.assertIn("--confirm-demo-runtime", arguments)
        self.assertEqual(arguments[arguments.index("--duration-hours") + 1], "24")

    def test_paths_with_spaces_remain_single_arguments(self):
        config = replace(self.agent, python_executable=self.root / "path with spaces/python")
        self.assertEqual(plistlib.loads(m.generate_plist(config))["ProgramArguments"][0],
                         str(config.python_executable))

    def test_plist_has_paths_only_no_environment_or_values(self):
        plist = self.parsed()
        self.assertNotIn("EnvironmentVariables", plist)
        text = m.generate_plist(self.agent).decode()
        for name in ("BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            self.assertNotIn(name, text)
        self.assertFalse(self.config.secret_file.exists())

    def test_generation_is_pure(self):
        m.generate_plist(self.agent)
        self.runner.assert_not_called()
        self.assertFalse(self.agent.operator_root.exists())

    def test_operator_root_outside_repository(self):
        with self.assertRaises(m.OperatorError):
            replace(self.agent, operator_root=m.PROJECT_ROOT / "logs")

    def test_overlapping_roots_refused(self):
        with self.assertRaises(m.OperatorError):
            replace(self.agent, operator_root=self.config.registry_root)

    def test_canonical_working_directory_required(self):
        with self.assertRaises(m.OperatorError):
            replace(self.agent, working_directory=self.root)

    def test_private_files_created_with_exact_permissions(self):
        path = m.write_launchagent(self.agent)
        self.assertEqual(self.agent.operator_root.stat().st_mode & 0o777, 0o700)
        for file in (path, self.agent.operator_root / "stdout.log", self.agent.operator_root / "stderr.log"):
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.runner.assert_not_called()

    def test_existing_unsafe_root_not_repaired(self):
        self.agent.operator_root.mkdir(mode=0o755)
        with self.assertRaises(m.OperatorError):
            m.write_launchagent(self.agent)
        self.assertEqual(self.agent.operator_root.stat().st_mode & 0o777, 0o755)

    def test_existing_unsafe_log_not_repaired(self):
        self.agent.operator_root.mkdir(mode=0o700)
        path = self.agent.operator_root / "stdout.log"
        path.write_text("<TEST_ONLY>")
        path.chmod(0o644)
        with self.assertRaises(m.OperatorError):
            m.write_launchagent(self.agent)
        self.assertEqual(path.read_text(), "<TEST_ONLY>")

    def test_symlink_log_refused(self):
        self.agent.operator_root.mkdir(mode=0o700)
        (self.agent.operator_root / "stdout.log").symlink_to(self.root / "elsewhere")
        with self.assertRaises(m.OperatorError):
            m.write_launchagent(self.agent)

    def test_existing_plist_never_overwritten(self):
        path = m.write_launchagent(self.agent)
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            m.write_launchagent(self.agent)
        self.assertEqual(path.read_bytes(), before)

    def test_status_reports_process_only(self):
        self.runner.return_value = m.LaunchctlResult(0, job_output("state = running\npid = 123\nlast exit code = 1"))
        status = self.manager.status()
        self.assertTrue(status.loaded)
        self.assertTrue(status.running)
        self.assertEqual(status.pid, 123)
        self.assertEqual(status.last_exit_code, 1)
        self.assertFalse(status.stdout_exists)
        self.assertFalse(self.config.secret_file.exists())
        self.assertFalse(self.config.registry_root.exists())
        self.runner.assert_called_once_with(("print", self.manager.target))

    def test_unknown_status_is_not_invented(self):
        self.runner.return_value = m.LaunchctlResult(0, "new unsupported print format")
        self.assertIsNone(self.manager.status().running)
        self.runner.return_value = m.LaunchctlResult(1, "", "<TEST_ONLY>")
        self.assertIsNone(self.manager.status().loaded)

    def test_unloaded_status_requires_specific_error(self):
        self.runner.return_value = m.LaunchctlResult(113, "", 'Could not find service "' + m.LABEL + '"')
        self.assertFalse(self.manager.status().loaded)

    def test_result_repr_hides_raw_diagnostics(self):
        self.assertNotIn("<TEST_ONLY>", repr(m.LaunchctlResult(1, "<TEST_ONLY>", "<TEST_ONLY>")))

    def test_install_bootstraps_without_start(self):
        m.write_launchagent(self.agent)
        self.runner.side_effect = [m.LaunchctlResult(113, "", "Could not find service " + m.LABEL),
                                   m.LaunchctlResult(0)]
        self.manager.install()
        path = self.home / "Library/LaunchAgents" / (m.LABEL + ".plist")
        self.assertEqual(path.read_bytes(), m.generate_plist(self.agent))
        self.assertEqual(self.runner.call_args.args[0], ("bootstrap", self.manager.domain, str(path)))
        self.assertNotIn("kickstart", str(self.runner.call_args_list))

    def test_install_refuses_loaded_job(self):
        with self.assertRaises(m.OperatorError):
            self.manager.install()
        self.runner.assert_called_once()

    def test_explicit_start_never_kills_or_restarts(self):
        self.installed()
        self.manager.start()
        self.assertEqual(self.runner.call_args.args[0], ("kickstart", self.manager.target))
        self.assertNotIn("-k", str(self.runner.call_args_list))

    def test_start_refuses_running_job(self):
        self.runner.return_value = m.LaunchctlResult(0, job_output("state = running\npid = 123"))
        with self.assertRaises(m.OperatorError):
            self.manager.start()
        self.runner.assert_called_once()

    def test_start_refuses_changed_reviewed_plist(self):
        path = self.installed()
        path.write_text("<TEST_ONLY>")
        with self.assertRaises(m.OperatorError):
            self.manager.start()
        self.runner.assert_called_once()

    def test_stop_only_sigterm(self):
        self.runner.return_value = m.LaunchctlResult(0, job_output("state = running\npid = 123"))
        self.manager.stop()
        self.assertEqual(self.runner.call_args.args[0], ("kill", "SIGTERM", self.manager.target))

    def test_uninstall_refuses_running_job(self):
        self.runner.return_value = m.LaunchctlResult(0, job_output("state = running\npid = 123"))
        with self.assertRaises(m.OperatorError):
            self.manager.uninstall()
        self.runner.assert_called_once()

    def test_uninstall_only_stopped_reviewed_job(self):
        path = self.installed()
        self.manager.uninstall()
        self.assertFalse(path.exists())
        self.assertTrue(self.agent.generated_path.exists())
        self.assertEqual(self.runner.call_args.args[0], ("bootout", self.manager.target))

    def test_wrapper_argument_array_shell_false_and_minimal_environment(self):
        with patch.object(m.subprocess, "run", return_value=NS(returncode=0, stdout="", stderr="")) as run:
            result = m.launchctl(("print", self.manager.target))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_args.args[0], ["/bin/launchctl", "print", self.manager.target])
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "LC_ALL"})

    def test_wrapper_rejects_force_and_other_domain(self):
        with patch.object(m.subprocess, "run") as run:
            for args in (("kickstart", "-k", self.manager.target), ("kill", "SIGKILL", self.manager.target),
                         ("print", "system/other"), "print shell string"):
                with self.assertRaises(m.OperatorError):
                    m.launchctl(args)
            run.assert_not_called()

    def test_subprocess_failure_diagnostics_redacted(self):
        with patch.object(m.subprocess, "run", side_effect=RuntimeError("<TEST_ONLY>")):
            with self.assertRaisesRegex(m.OperatorError, "^LAUNCHCTL_FAILED$"):
                m.launchctl(("print", self.manager.target))

    def test_cli_requires_explicit_management_confirmation(self):
        args = ["start", "--registry-root", str(self.config.registry_root), "--observability-root",
                str(self.config.observability_root), "--secret-file", str(self.config.secret_file),
                "--duration-hours", "24", "--start-next-hour", "--operator-root", str(self.agent.operator_root),
                "--python-executable", str(self.agent.python_executable)]
        with patch.object(m, "launchctl", side_effect=AssertionError("NO CALL")), patch("sys.stdout", io.StringIO()):
            self.assertEqual(m.launchagent_main(args), 1)

    def status_for(self, body):
        self.runner.return_value = m.LaunchctlResult(0, job_output(body))
        return self.manager.status()

    def test_observed_nested_active_fixture_is_stopped(self):
        status = self.status_for("active count = 0\nstate = not running\n"
            "resource coalition = {\n\tstate = active\n\tactive count = 1\n}\n"
            "jetsam coalition = {\n\tstate = active\n\tactive count = 1\n}\nlast exit code = 1")
        self.assertTrue(status.loaded)
        self.assertIs(status.running, False)
        self.assertIsNone(status.pid)
        self.assertEqual(status.last_exit_code, 1)

    def test_running_top_level_with_nested_active(self):
        status = self.status_for("state = running\npid = 321\n"
                                 "nested = {\n\tstate = active\n}")
        self.assertIs(status.running, True)
        self.assertEqual(status.pid, 321)

    def test_nested_pid_cannot_make_stopped_job_running(self):
        status = self.status_for("state = not running\nnested = {\n\tpid = 321\n\tstate = active\n}")
        self.assertIs(status.running, False)
        self.assertIsNone(status.pid)

    def test_nested_pid_cannot_supply_missing_running_job_pid(self):
        status = self.status_for("state = running\nnested = {\n\tpid = 321\n}")
        self.assertIsNone(status.running)
        self.assertIsNone(status.pid)

    def test_nested_exit_does_not_override_job_exit(self):
        status = self.status_for("state = exited\nlast exit code = 1\n"
                                 "nested = {\n\tlast exit code = 0\n}")
        self.assertEqual(status.last_exit_code, 1)
        status = self.status_for("state = exited\nnested = {\n\tlast exit code = 0\n}")
        self.assertIsNone(status.last_exit_code)

    def test_duplicate_top_level_states_are_unknown(self):
        for second in ("running", "not running"):
            with self.subTest(second=second):
                self.assertIsNone(self.status_for("state = not running\nstate = " + second).running)

    def test_unsupported_top_level_state_is_unknown(self):
        for state in ("active", "spawn scheduled", "future state"):
            with self.subTest(state=state):
                self.assertIsNone(self.status_for("state = " + state).running)

    def test_malformed_top_level_pid_is_unknown(self):
        for pid in ("0", "-1", "abc", "1 2", "00123", "", "True"):
            for state in ("running", "not running"):
                with self.subTest(pid=pid,state=state):
                    self.assertIsNone(self.status_for("state = " + state + "\npid = " + pid).running)

    def test_stopped_state_with_top_level_pid_is_unknown(self):
        self.assertIsNone(self.status_for("state = waiting\npid = 123").running)

    def test_absent_pid_alone_is_not_stopped_evidence(self):
        self.assertIsNone(self.status_for("last exit code = 1").running)

    def test_duplicate_pid_and_exit_are_unknown(self):
        for body in ("state = running\npid = 123\npid = 123",
                     "state = exited\nlast exit code = 1\nlast exit code = 0",
                     "state = exited\nlast exit code = invalid"):
            self.assertIsNone(self.status_for(body).running)

    def test_malformed_reserved_top_level_fields_are_unknown(self):
        for field in ("pid : 123", "pid", "last exit code : 1", "state : exited", "pid = {\n}"):
            with self.subTest(field=field):
                self.assertIsNone(self.status_for("state = not running\n" + field).running)

    def test_malformed_outer_structure_is_unknown(self):
        valid = job_output("state = not running")
        cases = ("state = not running", valid + valid, valid.rstrip()[:-1], valid + "unrelated text",
                 valid.replace("\tstate", "\t\tstate"), valid.replace("gui/", "system/"),
                 job_output("state = not running\nunclosed = {"))
        for index,text in enumerate(cases):
            with self.subTest(case=index):
                self.runner.return_value = m.LaunchctlResult(0,text)
                self.assertIsNone(self.manager.status().running)

    def test_each_reviewed_stopped_state_remains_supported(self):
        for state in ("not running", "exited", "waiting"):
            self.assertIs(self.status_for("state = " + state).running, False)


if __name__ == "__main__":
    unittest.main()
