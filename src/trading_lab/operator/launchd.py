"""Explicit per-user launchd management, never broker or durable runtime status.

Nothing is installed, started or inspected at import time. All subprocess calls
have one injectable boundary. Diagnostics deliberately exclude launchctl output.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess

from .demo_runtime import (
    DemoRuntimeConfiguration, OperatorError, PROJECT_ROOT, SafeArgumentParser,
    _PROCESS_ENV, _no_symlinks, _require, absolute_path, add_runtime_arguments,
    configuration_from_arguments, private_directory, private_file,
)

LABEL = "com.tradinglab.demo-runtime"


@dataclass(frozen=True, slots=True)
class LaunchAgentConfiguration:
    runtime: DemoRuntimeConfiguration
    python_executable: Path
    operator_root: Path
    working_directory: Path = PROJECT_ROOT

    def __post_init__(self):
        _require(type(self.runtime) is DemoRuntimeConfiguration, "RUNTIME_CONFIGURATION_REQUIRED")
        for path in (self.python_executable, self.operator_root, self.working_directory):
            absolute_path(path)
            _require(not any(ord(c) < 32 for c in str(path)), "CONTROL_CHARACTER_PATH_REFUSED")
        _require(self.working_directory == PROJECT_ROOT, "PROJECT_WORKING_DIRECTORY_REQUIRED")
        _require(not self.operator_root.is_relative_to(PROJECT_ROOT)
                 and all(not self.operator_root.is_relative_to(path)
                         and not path.is_relative_to(self.operator_root)
                         for path in (self.runtime.registry_root, self.runtime.observability_root))
                 and not self.runtime.secret_file.is_relative_to(self.operator_root),
                 "SEPARATE_PRIVATE_OPERATOR_ROOT_REQUIRED")

    @property
    def generated_path(self):
        return self.operator_root / (LABEL + ".plist")


@dataclass(frozen=True, slots=True)
class LaunchctlResult:
    returncode: int
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class LaunchAgentStatus:
    loaded: bool | None
    running: bool | None
    pid: int | None
    last_exit_code: int | None
    stdout_exists: bool
    stderr_exists: bool


def launchctl(arguments):
    """Only approved management verbs, one send, no shell or inherited secrets."""
    _require(type(arguments) in (tuple, list) and bool(arguments)
             and all(type(item) is str for item in arguments)
             and arguments[0] in ("print", "bootstrap", "bootout", "kickstart", "kill"),
             "LAUNCHCTL_ARGUMENTS_REFUSED")
    domain = "gui/" + str(os.getuid())
    target = domain + "/" + LABEL
    valid = (tuple(arguments) in (("print", target), ("kickstart", target),
                                 ("kill", "SIGTERM", target), ("bootout", target))
             or (len(arguments) == 3 and tuple(arguments[:2]) == ("bootstrap", domain)
                 and arguments[2] == str(Path.home() / "Library/LaunchAgents" / (LABEL + ".plist"))))
    _require(valid, "LAUNCHCTL_SCOPE_REFUSED")
    try:
        result = subprocess.run(["/bin/launchctl", *arguments], shell=False,
            capture_output=True, text=True, timeout=10, env=_PROCESS_ENV)
        return LaunchctlResult(result.returncode, result.stdout, result.stderr)
    except Exception:
        raise OperatorError("LAUNCHCTL_FAILED") from None


def generate_plist(configuration):
    """Return plist bytes only; no filesystem, credential or launchd access."""
    _require(type(configuration) is LaunchAgentConfiguration, "LAUNCHAGENT_CONFIGURATION_REQUIRED")
    config = configuration.runtime
    arguments = [str(configuration.python_executable), "-B",
        str(PROJECT_ROOT / "scripts/trading_lab_demo_runtime.py"),
        "--registry-root", str(config.registry_root),
        "--observability-root", str(config.observability_root),
        "--secret-file", str(config.secret_file),
        "--duration-hours", str(config.duration_hours), "--start-next-hour", "--confirm-demo-runtime"]
    return plistlib.dumps({"Label": LABEL, "ProgramArguments": arguments,
        "WorkingDirectory": str(configuration.working_directory),
        "StandardOutPath": str(configuration.operator_root / "stdout.log"),
        "StandardErrorPath": str(configuration.operator_root / "stderr.log"),
        "RunAtLoad": False, "KeepAlive": False, "ProcessType": "Background", "Umask": 0o077},
        fmt=plistlib.FMT_XML, sort_keys=True)


def _exclusive_file(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    private_file(path, maximum=max(len(content), 1))


def _private_logs(configuration):
    private_directory(configuration.operator_root, create=True)
    for name in ("stdout.log", "stderr.log"):
        path = configuration.operator_root / name
        if not path.exists() and not path.is_symlink():
            _exclusive_file(path, b"")
        private_file(path, maximum=2**63 - 1)


def write_launchagent(configuration):
    """Create a reviewable private plist and log files; never load or run it."""
    content = generate_plist(configuration)
    _private_logs(configuration)
    _exclusive_file(configuration.generated_path, content)
    return configuration.generated_path


def _reviewed_file(path, expected):
    before = private_file(path, maximum=65_536)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        _require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), "PLIST_CHANGED")
        content = handle.read(65_537)
    _require(content == expected, "PLIST_DOES_NOT_MATCH_REVIEWED_CONFIGURATION")


def _agents_directory():
    # Resolve the actual user at invocation; never commit an operator's username.
    directory = Path.home() / "Library/LaunchAgents"
    _no_symlinks(directory)
    for path in (directory.parent, directory):
        if path == directory and not path.exists():
            path.mkdir(mode=0o700)
        info = path.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and not info.st_mode & 0o022, "UNSAFE_LAUNCHAGENTS_DIRECTORY")
    return directory


class LaunchAgentManager:
    """No implicit activation. Each management operation is an explicit call."""

    def __init__(self, configuration, *, runner=launchctl):
        _require(type(configuration) is LaunchAgentConfiguration and callable(runner),
                 "LAUNCHAGENT_CONFIGURATION_REQUIRED")
        self.configuration = configuration
        self.runner = runner
        self.domain = "gui/" + str(os.getuid())
        self.target = self.domain + "/" + LABEL

    def _run(self, *arguments):
        try:
            result = self.runner(tuple(arguments))
            _require(type(result) is LaunchctlResult, "LAUNCHCTL_RESULT_INVALID")
            return result
        except Exception:
            raise OperatorError("LAUNCHCTL_FAILED") from None

    def status(self):
        """Only process metadata; UNKNOWN on unsupported/error print formats."""
        result = self._run("print", self.target)
        loaded = running = pid = last_exit = None
        if result.returncode == 0:
            loaded = True
            pids = re.findall(r"^\s*pid = ([1-9][0-9]*)\s*$", result.stdout, re.MULTILINE)
            states = re.findall(r"^\s*state = ([a-z ]+)\s*$", result.stdout, re.MULTILINE)
            exits = re.findall(r"^\s*last exit code = (-?[0-9]+)\s*$", result.stdout, re.MULTILINE)
            if len(pids) == 1 and states == ["running"]:
                pid, running = int(pids[0]), True
            elif not pids and states in (["not running"], ["exited"], ["waiting"]):
                running = False
            if len(exits) == 1:
                last_exit = int(exits[0])
        elif (result.returncode == 113 and "Could not find service" in result.stderr
              and LABEL in result.stderr):
            loaded, running = False, False
        root = self.configuration.operator_root
        # lstat only: status never opens the logs (which might contain private data).
        def exists(name):
            path = root / name
            return not root.is_symlink() and not path.is_symlink() and path.is_file()
        return LaunchAgentStatus(loaded, running, pid, last_exit, exists("stdout.log"), exists("stderr.log"))

    def install(self):
        _require(self.status().loaded is False, "JOB_MUST_BE_CONFIRMED_UNLOADED")
        expected = generate_plist(self.configuration)
        _reviewed_file(self.configuration.generated_path, expected)
        _private_logs(self.configuration)
        path = _agents_directory() / (LABEL + ".plist")
        _exclusive_file(path, expected)
        # RunAtLoad=false: bootstrap is registration, not trading authorization.
        _require(self._run("bootstrap", self.domain, str(path)).returncode == 0,
                 "BOOTSTRAP_FAILED_REVIEW_REQUIRED")

    def start(self):
        status = self.status()
        _require(status.loaded is True and status.running is False, "JOB_MUST_BE_CONFIRMED_STOPPED")
        _reviewed_file(_agents_directory() / (LABEL + ".plist"), generate_plist(self.configuration))
        _private_logs(self.configuration)
        # Never -k: an already-running process must not be terminated/restarted.
        _require(self._run("kickstart", self.target).returncode == 0, "KICKSTART_FAILED_REVIEW_REQUIRED")

    def stop(self):
        _require(self.status().running is True, "JOB_MUST_BE_CONFIRMED_RUNNING")
        _require(self._run("kill", "SIGTERM", self.target).returncode == 0, "STOP_REQUEST_FAILED")

    def uninstall(self):
        status = self.status()
        _require(status.running is False and status.loaded is not None, "JOB_MUST_BE_CONFIRMED_STOPPED")
        path = _agents_directory() / (LABEL + ".plist")
        _reviewed_file(path, generate_plist(self.configuration))
        if status.loaded:
            _require(self._run("bootout", self.target).returncode == 0, "BOOTOUT_FAILED_REVIEW_REQUIRED")
        path.unlink()  # Only the validated, stopped job's own plist; never a lock.


def launchagent_main(argv=None):
    parser = SafeArgumentParser(description="Explicit bounded Demo LaunchAgent management.")
    parser.add_argument("operation", choices=("generate", "install", "status", "start", "stop", "uninstall"))
    add_runtime_arguments(parser)
    parser.add_argument("--python-executable", required=True, type=Path)
    parser.add_argument("--operator-root", required=True, type=Path)
    parser.add_argument("--confirm-management", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = LaunchAgentConfiguration(configuration_from_arguments(args),
                                         args.python_executable, args.operator_root)
        manager = LaunchAgentManager(config)
        if args.operation == "status":
            from dataclasses import asdict
            print(json.dumps(asdict(manager.status())))
        else:
            _require(args.confirm_management, "EXPLICIT_MANAGEMENT_CONFIRMATION_REQUIRED")
            if args.operation == "generate":
                write_launchagent(config)
            else:
                getattr(manager, args.operation)()
            print("Management operation completed; no broker state is inferred.")
        return 0
    except BaseException:
        print("LaunchAgent operation refused; owner review required.")
        return 1
