"""Compose tool version check and safe upgrade.

Secret: the minimum compose version required, where an upgraded compose
plugin is installed and downloaded from, and how the previously working
plugin is kept as a backup so that a failed (or later reverted) upgrade
restores it.
"""

import os
import platform as _platform
import shutil
import sys
import urllib.request

from . import messages as _messages
from . import process, semver
from .errors import CliError
from .output import Output
from .revertable import RevertableStepProcessor

MIN_VERSION = "2.20.2"
_URL_ENV = "APPCTL_COMPOSE_DOWNLOAD_URL"
_DEFAULT_URL = ("https://github.com/docker/compose/releases/download/"
                "v{version}/docker-compose-{os}-{arch}")
_PLUGIN = "docker-compose"
_BACKUP_SUFFIX = ".appctl-backup"
_DOWNLOAD_SUFFIX = ".appctl-download"
_TIMEOUT = 120
_ARCHES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64",
           "aarch64": "aarch64", "armv7l": "armv7", "armv6l": "armv6",
           "ppc64le": "ppc64le", "s390x": "s390x", "riscv64": "riscv64"}


def plugin_path(env):
    """The user-level compose plugin, which takes precedence over system
    plugins; upgrades are installed there."""
    config = env.get("DOCKER_CONFIG")
    if not config:
        home = env.get("HOME") or os.path.expanduser("~")
        config = os.path.join(home, ".docker")
    return os.path.join(config, "cli-plugins", _PLUGIN)


def download_url(version, env, system=None, machine=None):
    template = env.get(_URL_ENV) or _DEFAULT_URL
    system = (system or _platform.system()).lower()
    machine = (machine or _platform.machine()).lower()
    return template.format(version=version, os=system, arch=_ARCHES.get(machine, machine))


def _download(url, destination):
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:  # noqa: S310
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)


def _remove(path):
    if os.path.lexists(path):
        os.remove(path)


class ComposeTool:
    """Checks the installed compose version and upgrades it when it is
    below ``min_version``."""

    def __init__(self, runtime, out=None, env=None, min_version=MIN_VERSION,
                 target_version=None, downloader=None):
        self.runtime = runtime
        self.out = out or Output(sys.stdout, sys.stderr)
        self.env = dict(env if env is not None else os.environ)
        self.min_version = semver.parse(min_version)
        self.target_version = semver.parse(target_version or min_version)
        self.downloader = downloader or _download
        self.path = plugin_path(self.env)
        self.backup = self.path + _BACKUP_SUFFIX
        self.download = self.path + _DOWNLOAD_SUFFIX
        self._processor = None

    def installed_version(self):
        """The installed version, or ``None`` when it cannot be determined."""
        return semver.parse(self.runtime.compose_version())

    def needs_upgrade(self):
        installed = self.installed_version()
        return installed is not None and installed < self.min_version

    def ensure(self):
        """Upgrade when needed; return whether an upgrade was installed.

        A failed upgrade raises ``CliError`` after the previous compose tool
        has been restored.
        """
        installed = self.installed_version()
        if installed is None:
            self.out.debug("Unable to determine the compose tool version.", group="upgrade")
            return False
        if not installed < self.min_version:
            return False
        self.upgrade(installed)
        return True

    def upgrade(self, installed=None):
        directory = os.path.dirname(self.path)
        created_dir = not os.path.isdir(directory)
        had_plugin = os.path.lexists(self.path)
        processor = RevertableStepProcessor(self.out)
        processor.add_step("create plugin directory",
                           lambda: os.makedirs(directory, exist_ok=True),
                           lambda: created_dir and _rmdir_if_empty(directory))
        processor.add_step("download compose tool", self._fetch,
                           lambda: _remove(self.download))
        processor.add_step("verify downloaded compose tool", self._verify_download)
        if had_plugin:
            processor.add_step("back up compose tool",
                               lambda: os.replace(self.path, self.backup),
                               self._restore_backup)
        processor.add_step("install compose tool",
                           lambda: os.replace(self.download, self.path),
                           lambda: _remove(self.path))
        processor.add_step("verify installed compose tool", self._verify_installed)
        if not processor.execute():
            raise CliError(_reason(processor.error))
        self._processor = processor
        self.out.log_only(_messages.compose_upgraded(installed, self.installed_version()))
        return True

    def restore(self):
        """Undo a successful upgrade (restoring the previous compose tool)."""
        if self._processor is not None:
            self._processor.rollback()
            self._processor = None

    def cleanup(self):
        """Forget the backup once the upgrade is final."""
        if self._processor is not None:
            self._processor = None
            _remove(self.backup)

    # --- steps --------------------------------------------------------------

    def _fetch(self):
        url = download_url(self.target_version, self.env)
        self.out.debug(f"Downloading compose tool from {url}", group="upgrade")
        try:
            self.downloader(url, self.download)
        except Exception as exc:  # noqa: BLE001 - network and file errors alike
            raise CliError(f"Unable to download '{url}': {_reason(exc)}") from exc
        os.chmod(self.download, 0o755)

    def _verify_download(self):
        result = process.run([self.download, "version", "--short"], env=self.runtime.env,
                             out=self.out)
        version = semver.parse(result.stdout) if result.succeeded else None
        if version is None or version < self.min_version:
            raise CliError("The downloaded compose tool is not usable.")

    def _verify_installed(self):
        version = self.installed_version()
        if version is None or version < self.min_version:
            raise CliError("The upgraded compose tool is not usable.")

    def _restore_backup(self):
        if os.path.lexists(self.backup):
            os.replace(self.backup, self.path)


def _rmdir_if_empty(directory):
    try:
        os.rmdir(directory)
    except OSError:
        pass


def _reason(exc):
    return getattr(exc, "message", None) or str(exc) or type(exc).__name__
