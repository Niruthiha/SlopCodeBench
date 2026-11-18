"""Work done before every command: first-run setup and the version comparison."""

import io

from . import __version__, upgrade
from .config_loader import root_dir
from .errors import AppctlError
from .system import PRODUCT_NAME, is_darwin

CLI_FAMILY = "cli"
MIGRATE_COMMAND = "cli migrate"
# Commands that must never print anything besides their own (possibly empty) payload.
SILENT_COMMANDS = ("cli completions", "cli has-command")
MACHINE_FORMATS = ("json", "csv", "yaml", "count", "ids", "var_export")
MACHINE_FLAGS = ("field", "porcelain")

FIRST_RUN_SUCCESS = f"{PRODUCT_NAME} has been set up successfully."


def family(command):
    if command is None or command.is_root or not command.path:
        return None
    return command.path[0]


def is_silent(command):
    return command is not None and command.full_name in SILENT_COMMANDS


def is_machine_readable(command, assoc=None):
    """Whether the command's documented output is a machine-readable payload."""
    if command is None or command.is_root:
        return False
    if command.machine_output or is_silent(command):
        return True
    assoc = assoc or {}
    fmt = assoc.get("format", command.defaults.get("format"))
    if isinstance(fmt, str) and fmt in MACHINE_FORMATS:
        return True
    return any(assoc.get(flag) not in (None, False, "") for flag in MACHINE_FLAGS)


def darwin_instructions(environ):
    return [
        "Please configure the container runtime (Docker Desktop) before using "
        f"{PRODUCT_NAME}:",
        "  1. Open Docker Desktop > Settings > Resources > File sharing.",
        f"  2. Add '{root_dir(environ)}' and the directories of your projects to the shared paths.",
        "  3. Click 'Apply & restart' and wait for the container runtime to be running again.",
    ]


def older_binary_message(stored, current=__version__):
    return (f"{PRODUCT_NAME} {current} is older than the version that last used this "
            f"installation ({stored}).")


class Startup:
    """First run, version comparison and migration for one invocation."""

    def __init__(self, environ, output, db, command=None, assoc=None, platform_name=None,
                 current=__version__):
        self.environ = environ
        self.output = output
        self.db = db
        self.command = command
        self.assoc = assoc or {}
        self.platform_name = platform_name
        self.current = current

    @property
    def messages(self):
        """Writer for startup messages that keeps the command's payload intact.

        Silent commands discard them all; machine-readable commands drop the
        informational (STDOUT) ones and keep warnings and errors on STDERR.
        """
        if is_silent(self.command):
            sink = io.StringIO()
            return self.output.redirected(stdout=sink, stderr=sink)
        if is_machine_readable(self.command, self.assoc):
            return self.output.redirected(stdout=io.StringIO())
        return self.output

    def run(self):
        stored = upgrade.stored_version(self.db)
        if stored is None:
            return self.first_run()
        status = upgrade.version_status(stored, self.current)
        if status == upgrade.VERSION_NEWER:
            if self.command is None or self.command.full_name != MIGRATE_COMMAND:
                self.output.debug("Version changed, running the upgrade.", group="bootstrap")
                upgrade.run_upgrade(self.environ, self.messages)
        elif status == upgrade.VERSION_OLDER:
            self.older_binary(stored)
        return True

    def first_run(self):
        output = self.messages
        output.debug("First run, setting up.", group="bootstrap")
        upgrade.run_setup(self.environ, output, self.db)
        output.success(FIRST_RUN_SUCCESS)
        if is_darwin(self.platform_name):
            for line in darwin_instructions(self.environ):
                output.log(line)
        return True

    def older_binary(self, stored):
        message = older_binary_message(stored, self.current)
        if family(self.command) == CLI_FAMILY:
            if not is_silent(self.command):
                self.output.warning(f"{message} Please update {PRODUCT_NAME}.")
            return
        raise AppctlError(f"{message} Please update {PRODUCT_NAME} to version {stored} or newer "
                          "with 'appctl cli update' before running this command.")
