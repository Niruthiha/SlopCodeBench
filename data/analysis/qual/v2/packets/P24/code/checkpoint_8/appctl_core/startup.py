"""Work done before a command runs.

Secret: which command families skip the host requirement checks, which
commands are quiet or machine-readable (and how first-run messaging is
kept out of their output), how a first run is detected and set up, how the
binary version is compared with the stored one (nightly builds always
migrate), and when and how often updates are checked for automatically.
"""

import time

from . import catalog, migrations, releases, semver, system, upgrade
from . import messages as _messages
from .errors import CliError, Halt

EXEMPT_FAMILIES = {"cli", "config", "help"}
# Commands that never print anything beyond their documented payload.
SILENT_COMMANDS = {"cli completions", "cli has-command"}
# Commands whose output is meant to be consumed by programs or shells.
MACHINE_READABLE = SILENT_COMMANDS | {
    "cli version", "cli param-dump", "cli cmd-dump", "cli alias"}
# Commands that run their own migrations, or must not trigger any.
_NO_MIGRATION = {"cli completions", "cli migrate", "cli self-uninstall"}
_NO_AUTO_UPDATE = {"cli completions", "cli has-command", "cli update", "cli check-update",
                   "cli self-uninstall", "cli migrate"}
_HUMAN_FORMATS = {None, "table", "list"}
_DATA_OPTIONS = ("porcelain", "field", "fields")

UPDATE_CHECK_KEY = "appctl-update-check"
_DAYS_ENV = "APPCTL_AUTO_CHECK_UPDATE_DAYS"
_DISABLE_ENV = "APPCTL_DISABLE_AUTO_CHECK_UPDATE"
_DEFAULT_DAYS = 1
_DAY = 24 * 60 * 60
_FALSE_WORDS = {"", "0", "false", "no", "off"}


def family(path):
    return path.split()[0] if path else "help"


def is_exempt(path):
    """Whether the command runs without checking the host requirements."""
    return family(path) in EXEMPT_FAMILIES


def is_silent(path):
    return path in SILENT_COMMANDS


def is_machine_readable(path, options):
    """Whether the command's output is a payload for programs or shells."""
    if path in MACHINE_READABLE or path.split()[-1:] == ["get"]:
        return True
    given = dict(options)
    if given.get("format") not in _HUMAN_FORMATS:
        return True
    return any(name in given for name in _DATA_OPTIONS)


class Startup:
    """Runs the pre-command steps for one invocation."""

    def __init__(self, node, options, out, env, db, config, stdout, cache=None,
                 update=None):
        self.path = node.path
        self.options = list(options)
        self.out = out
        self.env = dict(env)
        self.db = db
        self.config = config
        self.stdout = stdout
        self.cache = cache
        self.update = update

    # --- requirements ---------------------------------------------------------

    def check_requirements(self):
        if is_exempt(self.path):
            return
        if not system.Requirements(self.env, self.out).check():
            raise Halt(1)

    # --- first run and version comparison --------------------------------------

    def _notify(self, text):
        if is_machine_readable(self.path, self.options):
            return
        self.out.success(text)

    def first_run(self):
        """Create the store and run every pending migration."""
        self.out.debug("First run: setting up the persistence store.", group="bootstrap")
        sources = migrations.default_sources(self.config.packages_dir(), self.out)
        batches = []
        try:
            for kind in migrations.TYPES:
                batch = migrations.MigrationBatch(
                    self.db, self.out, migrations.pending(self.db, sources, kind),
                    lambda m: migrations.MigrationContext(
                        m, self.db, self.out, env=self.env,
                        root_dir=self.config.root_dir()))
                batch.execute()
                batches.append(batch)
            self.db.update_option(upgrade.VERSION_KEY, catalog.VERSION)
        except CliError as exc:
            for batch in reversed(batches):
                batch.rollback()
            self.out.report(exc)
            raise CliError(_messages.migration_error()) from None
        self._notify(_messages.first_run_completed())
        if system.is_darwin() and not is_machine_readable(self.path, self.options):
            self.out.log(_messages.darwin_runtime_instructions(self.config.root_dir()))

    def compare_versions(self):
        stored = upgrade.stored_version(self.db)
        current = catalog.VERSION
        binary_v = semver.parse(releases.base_version(current))
        stored_v = semver.parse(releases.base_version(stored))
        if binary_v is not None and stored_v is not None and binary_v < stored_v:
            if family(self.path) != "cli":
                raise CliError(_messages.update_required(current, stored))
            if not is_silent(self.path):
                self.out.warning(_messages.binary_older_than_database(current, stored))
            newer = False
        else:
            newer = stored_v is None or binary_v is None or binary_v > stored_v
        if newer or releases.is_nightly(current):
            catalog.upgrader(self.db, self.out, self.env, self.config).run()

    def migrate(self):
        if self.path in _NO_MIGRATION:
            return
        if upgrade.stored_version(self.db) is None:
            self.first_run()
        else:
            self.compare_versions()

    # --- automatic update checks -----------------------------------------------

    def _interval(self):
        try:
            days = int(str(self.env.get(_DAYS_ENV, "")).strip())
        except ValueError:
            return _DEFAULT_DAYS
        return days if days > 0 else _DEFAULT_DAYS

    def _should_check(self):
        if self.path in _NO_AUTO_UPDATE or self.cache is None or self.update is None:
            return False
        if str(self.env.get(_DISABLE_ENV, "")).strip().lower() not in _FALSE_WORDS:
            return False
        if system.is_darwin():
            return False
        try:
            interactive = bool(self.stdout.isatty())
        except (AttributeError, ValueError, OSError):
            interactive = False
        return interactive and system.is_writable(system.binary_path(self.env))

    def auto_check_update(self, now=None):
        """Check for updates every few days and install one when found.
        Returns whether an update was found."""
        if not self._should_check():
            return False
        now = time.time() if now is None else now
        last = self.cache.read(UPDATE_CHECK_KEY)
        if last is False:
            # The first check only records when it happened.
            self.cache.write(UPDATE_CHECK_KEY, str(int(now)))
            return False
        try:
            last = float(str(last).strip())
        except ValueError:
            last = 0.0
        if int((now - last) // _DAY) < self._interval():
            return False
        self.cache.write(UPDATE_CHECK_KEY, str(int(now)))
        try:
            updates = releases.available_updates(catalog.VERSION, self.env)
        except CliError as exc:
            self.out.debug(f"Update check failed: {exc.message}", group="bootstrap")
            return False
        if not updates:
            return False
        try:
            self.update()
        except CliError as exc:
            self.out.warning(_messages.auto_update_failed(exc.message))
        return True

    def run(self):
        self.check_requirements()
        self.migrate()
        self.auto_check_update()
