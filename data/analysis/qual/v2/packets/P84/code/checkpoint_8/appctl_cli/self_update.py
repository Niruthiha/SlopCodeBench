"""Release lookup, self-update of the appctl binary and the periodic update check."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request

from . import PROGRAM_NAME, __version__
from .arguments import END_OF_OPTIONS, is_assoc_token, parse_assoc_token
from .config_loader import CONFIG_PATH_ENV, PACKAGES_DIR_ENV, ROOT_DIR_ENV
from .container import is_truthy
from .errors import AppctlError
from .file_cache import CACHE_DIR_ENV, get_cache
from .output import _isatty
from .process import run_command
from .system import PRODUCT_NAME, binary_path, is_binary_writable, is_darwin, runtime_binary
from .upgrade import _SEMVER_RE, compare_semver, is_nightly, parse_semver

RELEASES_URL_ENV = "APPCTL_RELEASES_URL"
NIGHTLY_VERSION_URL_ENV = "APPCTL_NIGHTLY_VERSION_URL"
NIGHTLY_URL_ENV = "APPCTL_NIGHTLY_URL"
AUTO_CHECK_DAYS_ENV = "APPCTL_AUTO_CHECK_UPDATE_DAYS"
DISABLE_AUTO_CHECK_ENV = "APPCTL_DISABLE_AUTO_CHECK_UPDATE"

RELEASES_URL = f"https://api.github.com/repos/{PROGRAM_NAME}/{PROGRAM_NAME}/releases?per_page=100"
NIGHTLY_BASE_URL = f"https://raw.githubusercontent.com/{PROGRAM_NAME}/{PROGRAM_NAME}-builds/main/nightly"
NIGHTLY_VERSION_URL = f"{NIGHTLY_BASE_URL}/NIGHTLY_VERSION"
NIGHTLY_URL = f"{NIGHTLY_BASE_URL}/{PROGRAM_NAME}-nightly.pyz"

MAJOR, MINOR, PATCH, NIGHTLY = "major", "minor", "patch", "nightly"
UPDATE_TYPES = (MAJOR, MINOR, PATCH)
STABLE = "stable"
CHANNELS = (STABLE, NIGHTLY)
UPDATE_FIELDS = ["version", "update_type", "package_url"]
UPDATE_ALL_FIELDS = UPDATE_FIELDS + ["status"]

DEFAULT_CHECK_DAYS = 1
SECONDS_PER_DAY = 86400
UPDATE_CHECK_KEY = f"{PROGRAM_NAME}-update-check"

CHECKSUM_ALGORITHMS = ("sha512", "sha256", "md5")
HTTP_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 600
VALIDATION_TIMEOUT = 120

DARWIN_ERROR = ("Self-update is not available. "
                "Please use your system package manager to update.")
BROKEN_UPDATE = ("The downloaded update is broken; the existing installation was kept. "
                 f"Please try running '{PROGRAM_NAME} cli update' again.")


# -- HTTP ------------------------------------------------------------------------------


def _request(url):
    return urllib.request.Request(str(url), headers={
        "User-Agent": f"{PROGRAM_NAME}/{__version__}",
        "Accept": "application/vnd.github+json, application/json;q=0.9, */*;q=0.8",
    })


def _reason(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP code {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return getattr(exc, "strerror", None) or str(exc) or exc.__class__.__name__


def fetch(url, timeout=HTTP_TIMEOUT):
    """The body of ``url`` as bytes."""
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AppctlError(f"Failed to fetch '{url}' ({_reason(exc)}).") from exc


def download(url, destination, timeout=DOWNLOAD_TIMEOUT):
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as response, \
                open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AppctlError(f"Unable to download the update from '{url}' ({_reason(exc)}).") from exc


# -- releases ------------------------------------------------------------------------------


def releases_url(environ):
    return environ.get(RELEASES_URL_ENV) or RELEASES_URL


def nightly_version_url(environ):
    return environ.get(NIGHTLY_VERSION_URL_ENV) or NIGHTLY_VERSION_URL


def nightly_package_url(environ):
    return environ.get(NIGHTLY_URL_ENV) or NIGHTLY_URL


def _clean_version(text):
    text = str(text or "").strip()
    return text[1:] if text[:1] in ("v", "V") else text


def _package_url(release):
    for asset in release.get("assets") or ():
        if isinstance(asset, dict) and asset.get("browser_download_url"):
            return str(asset["browser_download_url"])
    for key in ("package_url", "download_url"):
        if release.get(key):
            return str(release[key])
    return None


def stable_releases(environ):
    """Published stable releases as ``[{"version", "package_url"}]``."""
    url = releases_url(environ)
    try:
        data = json.loads(fetch(url).decode("utf-8", "replace"))
    except AppctlError as exc:
        raise AppctlError(f"Failed to get the latest version: {exc.message}") from exc
    except ValueError as exc:
        raise AppctlError(f"Failed to get the latest version: invalid response from '{url}'.") from exc
    if isinstance(data, dict):
        data = data.get("releases", [data])
    if not isinstance(data, list):
        raise AppctlError(f"Failed to get the latest version: invalid response from '{url}'.")
    found = []
    for release in data:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        version = _clean_version(release.get("tag_name") or release.get("version")
                                 or release.get("name"))
        parsed = parse_semver(version)
        if parsed is None or parsed[1] or _SEMVER_RE.fullmatch(version) is None:
            continue
        found.append({"version": version, "package_url": _package_url(release)})
    return found


def update_type(new, current=__version__):
    """``major``, ``minor`` or ``patch`` when ``new`` is newer than ``current``, else ``None``."""
    try:
        if compare_semver(new, current) <= 0:
            return None
    except ValueError:
        return None
    new_release, current_release = parse_semver(new)[0], parse_semver(current)[0]
    if new_release[0] != current_release[0]:
        return MAJOR
    if new_release[1] != current_release[1]:
        return MINOR
    return PATCH


def _entry(version, kind, package_url):
    return {"version": version, "update_type": kind, "package_url": package_url,
            "status": "available"}


def nightly_version(environ):
    url = nightly_version_url(environ)
    try:
        text = fetch(url).decode("utf-8", "replace").strip()
    except AppctlError as exc:
        raise AppctlError(f"Failed to get the latest nightly version: {exc.message}") from exc
    if not text:
        raise AppctlError(f"Failed to get the latest nightly version from '{url}'.")
    return _clean_version(text.split()[0])


def nightly_updates(environ, current=__version__):
    latest = nightly_version(environ)
    try:
        newer = compare_semver(latest, current) > 0
    except ValueError:
        newer = latest != current
    return [_entry(latest, NIGHTLY, nightly_package_url(environ))] if newer else []


def available_updates(environ, current=__version__, only=None):
    """Newest release per update type (major, minor, patch order), optionally one type only.

    Nightly builds consult the nightly version source instead of the releases.
    """
    if is_nightly(current):
        return nightly_updates(environ, current)
    best = {}
    for release in stable_releases(environ):
        kind = update_type(release["version"], current)
        if kind is None:
            continue
        if kind in best and compare_semver(release["version"], best[kind]["version"]) <= 0:
            continue
        best[kind] = _entry(release["version"], kind, release["package_url"])
    types = [only] if only else UPDATE_TYPES
    return [best[kind] for kind in types if kind in best]


def latest_stable(environ):
    latest = None
    for release in stable_releases(environ):
        if latest is None or compare_semver(release["version"], latest["version"]) > 0:
            latest = release
    if latest is None:
        raise AppctlError("Failed to get the latest stable release: no release found.")
    return latest


def last_flag(argv, assoc, names):
    """The last of ``names`` given as an enabled flag, in command-line order."""
    last = None
    for token in argv or ():
        if token == END_OF_OPTIONS:
            break
        if is_assoc_token(token):
            key, value = parse_assoc_token(token)
            if key in names and value is not False:
                last = key
    if last is not None and assoc.get(last):
        return last
    enabled = [name for name in assoc if name in names and assoc[name]]
    return enabled[-1] if enabled else None


def selected_update_type(argv, assoc):
    """The ``--patch``/``--minor``/``--major`` filter; the last one given wins."""
    return last_flag(argv, assoc, UPDATE_TYPES)


def up_to_date_message(only=None):
    level = f"latest {only} version" if only else "latest version"
    return f"{PRODUCT_NAME} is up to date: it is at the {level}."


# -- self-update ------------------------------------------------------------------------------


def verify_checksum(path, url, output):
    """Check the download against a published ``<url>.<algorithm>`` hash, when there is one."""
    for algorithm in CHECKSUM_ALGORITHMS:
        try:
            published = fetch(f"{url}.{algorithm}").decode("utf-8", "replace").split()
        except AppctlError:
            continue
        if not published:
            continue
        expected = published[0].lower()
        digest = hashlib.new(algorithm)
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise AppctlError(f"The {algorithm} hash of the download ({actual}) is different "
                              f"than the release hash ({expected}).")
        output.log(f"{algorithm} hash verified: {expected}")
        return True
    output.debug("No release hash published, skipping the hash verification.", group="update")
    return False


def validation_environment(environ, workdir):
    """Run the new binary against throwaway state, never the user's."""
    env = {k: v for k, v in environ.items()
           if k not in (CONFIG_PATH_ENV, PACKAGES_DIR_ENV, CACHE_DIR_ENV)}
    env[ROOT_DIR_ENV] = workdir
    env[DISABLE_AUTO_CHECK_ENV] = "1"
    return env


def validate_binary(path, environ, output):
    """Run ``<runtime> <path> cli version``; return the version it reports or raise."""
    workdir = tempfile.mkdtemp(prefix=f"{PROGRAM_NAME}-update-")
    try:
        result = run_command([runtime_binary(environ), path, "cli", "version"], output,
                             cwd=workdir, env=validation_environment(environ, workdir),
                             timeout=VALIDATION_TIMEOUT)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    match = _SEMVER_RE.search(result.stdout or "")
    if not result.succeeded or not match:
        details = [line for line in (result.stderr or "").strip().splitlines() if line.strip()]
        for line in details[-5:]:
            output.debug(f"Validation: {line}", group="update")
        raise AppctlError(BROKEN_UPDATE)
    return match.group(0).lstrip("vV")


def install_binary(source, target):
    """Atomically replace ``target`` with ``source``, keeping the permissions of ``target``."""
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except OSError:
        mode = 0o755
    try:
        os.chmod(source, mode)
    except OSError as exc:
        raise AppctlError(f"Cannot chmod {source}.") from exc
    try:
        os.replace(source, target)
    except OSError as exc:
        raise AppctlError(f"Cannot move {source} to {target} ({exc.strerror or exc}).") from exc


def _check_target(target):
    if not target or not os.path.isfile(target):
        raise AppctlError(f"Unable to locate the {PRODUCT_NAME} binary.")
    if not os.access(target, os.W_OK):
        raise AppctlError(f"{target} is not writable by current user.")
    directory = os.path.dirname(target) or "."
    if not os.access(directory, os.W_OK):
        raise AppctlError(f"{directory} is not writable by current user.")


def self_update(environ, output, assoc=None, argv=(), current=__version__, platform_name=None,
                target=None):
    """``cli update``: download, validate and install a newer distribution archive."""
    assoc = dict(assoc or {})
    if is_darwin(platform_name):
        raise AppctlError(DARWIN_ERROR)
    target = target or binary_path()
    _check_target(target)
    channel = last_flag(argv, assoc, CHANNELS)
    if channel == NIGHTLY:
        try:
            version = nightly_version(environ)
        except AppctlError as exc:
            output.debug(exc.message, group="update")
            version = None
        url = nightly_package_url(environ)
        question = (f"You are currently using {PRODUCT_NAME} version {current}. "
                    "Would you like to update to the latest nightly version?")
    elif channel == STABLE:
        release = latest_stable(environ)
        version, url = release["version"], release["package_url"]
        question = (f"You are currently using {PRODUCT_NAME} version {current}. "
                    f"Would you like to update to the latest stable release ({version})?")
    else:
        only = selected_update_type(argv, assoc)
        updates = available_updates(environ, current, only)
        if not updates:
            output.success(up_to_date_message(only))
            return 0
        newest = updates[0]
        version, url = newest["version"], newest["package_url"]
        question = f"You have version {current}. Would you like to update to {version}?"
    if not url:
        raise AppctlError(f"No download is available for {PRODUCT_NAME} {version}.")
    if not output.confirm(question, assoc):
        return 0

    output.log(f"Downloading from {url}...")
    handle, temp = tempfile.mkstemp(prefix=f".{os.path.basename(target)}.", suffix=".download",
                                    dir=os.path.dirname(target) or ".")
    os.close(handle)
    try:
        download(url, temp)
        verify_checksum(temp, url, output)
        reported = validate_binary(temp, environ, output)
        output.log("New version works. Proceeding to replace.")
        install_binary(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    output.success(f"Updated {PRODUCT_NAME} to {version or reported}.")
    return 0


# -- automatic update check ------------------------------------------------------------------------


def check_interval(environ):
    """Whole days between automatic checks (``APPCTL_AUTO_CHECK_UPDATE_DAYS``, default 1)."""
    raw = environ.get(AUTO_CHECK_DAYS_ENV)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_CHECK_DAYS
    try:
        days = int(float(str(raw).strip()))
    except ValueError:
        return DEFAULT_CHECK_DAYS
    return days if days >= 0 else DEFAULT_CHECK_DAYS


def auto_check_disabled(environ):
    return is_truthy(environ.get(DISABLE_AUTO_CHECK_ENV, ""))


def is_interactive(output):
    return _isatty(output.stdout) and _isatty(output.stdin)


def elapsed_days(last_check, now=None):
    now = time.time() if now is None else now
    return int((now - last_check) // SECONDS_PER_DAY)


def _read_last_check(cache):
    raw = cache.read(UPDATE_CHECK_KEY, ttl=0)
    if raw is False:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def auto_check_update(environ, output, current=__version__, now=None, interactive=None,
                      writable=None, update=None, platform_name=None):
    """Periodic update check; returns the update's exit code when one was triggered.

    Only runs for a human at an interactive terminal with a writable binary.
    The first check only records its timestamp; later checks run once the
    configured number of whole days has elapsed since the last one.
    """
    if auto_check_disabled(environ):
        return None
    if not (is_interactive(output) if interactive is None else interactive):
        return None
    if not (is_binary_writable() if writable is None else writable):
        return None
    if is_darwin(platform_name):
        return None
    now = time.time() if now is None else now
    cache = get_cache(environ, output)
    last_check = _read_last_check(cache)
    if last_check is None:
        cache.write(UPDATE_CHECK_KEY, str(int(now)))
        return None
    if elapsed_days(last_check, now) < check_interval(environ):
        return None
    cache.write(UPDATE_CHECK_KEY, str(int(now)))
    try:
        updates = available_updates(environ, current)
    except AppctlError as exc:
        output.debug(f"Automatic update check failed: {exc.message}", group="update")
        return None
    if not updates:
        return None
    output.log(f"A new version of {PRODUCT_NAME} is available: {updates[0]['version']}.")
    update = update or (lambda: self_update(environ, output, {}, current=current,
                                            platform_name=platform_name))
    return update()
