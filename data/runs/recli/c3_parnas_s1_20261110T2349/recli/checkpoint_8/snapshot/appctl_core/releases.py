"""Releases and self-update.

Secret: where releases, nightly builds and their checksums are published
(and the environment variables overriding those locations), the shape of
the releases API response, how nightly builds are recognised, how an
available update is classified (patch, minor, major or nightly), and how a
downloaded archive is validated before it atomically replaces the running
binary.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from . import messages as _messages
from . import semver, system
from .errors import CliError

RELEASES_URL = "https://api.github.com/repos/appctl/appctl/releases?per_page=100"
NIGHTLY_VERSION_URL = "https://raw.githubusercontent.com/appctl/builds/gh-pages/NIGHTLY_VERSION"
NIGHTLY_URL = "https://raw.githubusercontent.com/appctl/builds/gh-pages/appctl-nightly.pyz"
_RELEASES_ENV = "APPCTL_RELEASES_URL"
_NIGHTLY_VERSION_ENV = "APPCTL_NIGHTLY_VERSION_URL"
_NIGHTLY_URL_ENV = "APPCTL_NIGHTLY_URL"
_CHECKSUM_SUFFIX = ".sha256"
_ARCHIVE_SUFFIX = ".pyz"
_NIGHTLY = "nightly"
_TIMEOUT = 60
_VALIDATION_TIMEOUT = 120
UPDATE_TYPES = ("patch", "minor", "major")
NIGHTLY = _NIGHTLY


# --- versions --------------------------------------------------------------------

def is_nightly(version):
    return _NIGHTLY in str(version or "").lower()


def base_version(version):
    """The release a (possibly nightly) version is built from."""
    text = str(version or "")
    index = text.lower().find("-" + _NIGHTLY)
    return text[:index] if index >= 0 else text


def update_type(new, current):
    """``"patch"``, ``"minor"`` or ``"major"`` when ``new`` is newer than
    ``current`` (semantic version precedence), else ``None``."""
    new_v, cur_v = semver.parse(new), semver.parse(base_version(current))
    if new_v is None or cur_v is None or not new_v > cur_v:
        return None
    if new_v.major != cur_v.major:
        return "major"
    if new_v.minor != cur_v.minor:
        return "minor"
    return "patch"


# --- fetching --------------------------------------------------------------------

def _reason(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP code {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return getattr(exc, "strerror", None) or str(exc) or type(exc).__name__


def fetch(url, timeout=_TIMEOUT):
    """The body at ``url`` as bytes. Raises ``OSError``/``URLError``."""
    request = urllib.request.Request(url, headers={"User-Agent": "AppCtl"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _fetch_text(url, what):
    try:
        data = fetch(url)
    except Exception as exc:  # noqa: BLE001 - network and file errors alike
        raise CliError(_messages.releases_unavailable(url, _reason(exc))) from None
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)


def _asset_url(release):
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    urls = [a.get("browser_download_url") for a in assets
            if isinstance(a, dict) and a.get("browser_download_url")]
    for url in urls:
        if str(url).endswith(_ARCHIVE_SUFFIX):
            return url
    if urls:
        return urls[0]
    return release.get("package_url")


def stable_releases(env):
    """``[{version, package_url}]`` of the published stable releases."""
    url = env.get(_RELEASES_ENV) or RELEASES_URL
    text = _fetch_text(url, "releases")
    try:
        data = json.loads(text)
    except ValueError:
        raise CliError(_messages.releases_unavailable(url, "invalid JSON response")) from None
    if isinstance(data, dict):
        data = data.get("releases", [])
    releases = []
    for release in data if isinstance(data, list) else ():
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or release.get("version") or "").strip()
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        parsed = semver.parse(version)
        package = _asset_url(release)
        if parsed is None or parsed.prerelease or not package:
            continue
        releases.append({"version": version, "package_url": package})
    return releases


def nightly_version(env):
    url = env.get(_NIGHTLY_VERSION_ENV) or NIGHTLY_VERSION_URL
    return _fetch_text(url, "nightly version").strip()


def nightly_url(env):
    return env.get(_NIGHTLY_URL_ENV) or NIGHTLY_URL


def available_updates(current, env, update_filter=None):
    """Updates newer than ``current``, newest type first; with a filter only
    the newest update of that type. A nightly build consults the nightly
    channel instead of the stable releases."""
    if is_nightly(current):
        latest = nightly_version(env)
        if latest and latest != current:
            return [{"version": latest, "update_type": _NIGHTLY,
                     "package_url": nightly_url(env)}]
        return []
    newest = {}
    for release in stable_releases(env):
        kind = update_type(release["version"], current)
        if kind is None:
            continue
        known = newest.get(kind)
        if known is None or semver.parse(release["version"]) > semver.parse(known["version"]):
            newest[kind] = {"version": release["version"], "update_type": kind,
                            "package_url": release["package_url"]}
    if update_filter:
        return [newest[update_filter]] if update_filter in newest else []
    return [newest[kind] for kind in reversed(UPDATE_TYPES) if kind in newest]


def latest_stable(env):
    releases = stable_releases(env)
    if not releases:
        raise CliError(_messages.no_stable_release())
    return max(releases, key=lambda r: semver.parse(r["version"]))


# --- installing ------------------------------------------------------------------

def download(url, destination):
    try:
        data = fetch(url)
    except Exception as exc:  # noqa: BLE001
        raise CliError(_messages.download_failed(url, _reason(exc))) from None
    with open(destination, "wb") as handle:
        handle.write(data)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(url, path, out):
    """Compare with the published checksum when one is published."""
    try:
        published = fetch(url + _CHECKSUM_SUFFIX).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - checksums are optional
        out.debug(f"No checksum published for {url} ({_reason(exc)}).", group="update")
        return None
    expected = (published.split() or [""])[0].lower()
    actual = _sha256(path)
    if expected != actual:
        raise CliError(_messages.update_broken(_messages.checksum_mismatch(actual, expected)))
    out.log(f"Checksum verified: {expected}")
    return expected


def validate(path, env):
    """Run the downloaded archive in isolation; return the version it
    reports or raise ``CliError``."""
    if not zipfile.is_zipfile(path):
        raise CliError(_messages.update_broken("not a distribution archive"))
    with zipfile.ZipFile(path) as bundle:
        if "__main__.py" not in bundle.namelist():
            raise CliError(_messages.update_broken("no entry point in the archive"))
    scratch = tempfile.mkdtemp(prefix="appctl-validate-")
    child_env = {k: v for k, v in env.items() if not k.startswith("APPCTL_")}
    child_env.update({"APPCTL_ROOT_DIR": scratch, "APPCTL_DISABLE_AUTO_CHECK_UPDATE": "1",
                      "PATH": env.get("PATH", os.environ.get("PATH", ""))})
    try:
        proc = subprocess.run([system.runtime_binary(env), path, "cli", "version"],
                              env=child_env, cwd=scratch, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=_VALIDATION_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CliError(_messages.update_broken(_reason(exc))) from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    stdout = proc.stdout.decode(errors="replace").strip()
    version = semver.parse(stdout) if proc.returncode == 0 else None
    if version is None:
        detail = proc.stderr.decode(errors="replace").strip().splitlines()
        raise CliError(_messages.update_broken(
            detail[-1] if detail else f"exit code {proc.returncode}"))
    return stdout.split()[-1]


def install(url, binary, env, out):
    """Download ``url``, validate it and replace ``binary`` with it. The
    old binary is untouched unless every check passed. Returns the version
    of the installed archive."""
    directory = os.path.dirname(os.path.abspath(binary))
    handle, temp = tempfile.mkstemp(prefix=".appctl-update-", suffix=_ARCHIVE_SUFFIX,
                                    dir=directory)
    os.close(handle)
    try:
        out.log(f"Downloading from {url}...")
        download(url, temp)
        verify_checksum(url, temp, out)
        version = validate(temp, env)
        out.log("New version works. Proceeding to replace.")
        mode = os.stat(binary).st_mode & 0o777 if os.path.exists(binary) else 0o755
        os.chmod(temp, mode)
        os.replace(temp, binary)
    except OSError as exc:
        raise CliError(_messages.update_broken(_reason(exc))) from None
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return version
