"""User-facing message wording.

Secret: the exact text of every error and notice, and the program's display
name.
"""

_PROGRAM = "appctl"


def program_name():
    return _PROGRAM


def _with_suggestion(message, suggestion):
    if suggestion:
        return f"{message}\nDid you mean '{suggestion}'?"
    return message


def unregistered_command(name, suggestion=None):
    return _with_suggestion(
        f"'{name}' is not a registered {_PROGRAM} command. "
        f"See '{_PROGRAM} help' for available commands.",
        suggestion,
    )


def unregistered_subcommand(name, parent, suggestion=None):
    return _with_suggestion(
        f"'{name}' is not a registered subcommand of '{parent}'. "
        f"See '{_PROGRAM} help {parent}' for available subcommands.",
        suggestion,
    )


def too_many_positionals(words):
    return "Too many positional arguments: " + " ".join(words)


def parameter_errors(lines):
    return "Parameter errors:" + "".join(f"\n {line}" for line in lines)


def missing_parameter(key):
    return f"missing --{key} parameter"


def parameter_needs_value(key):
    return f"--{key} parameter needs a value"


def parameter_takes_no_value(key):
    return f"--{key} parameter does not accept a value"


def unknown_parameter(key, suggestion=None):
    message = f"unknown --{key} parameter"
    if suggestion:
        message += f"\nDid you mean '--{suggestion}'?"
    return message


def invalid_synopsis(path, parts):
    return (f"The '{path}' command has an invalid synopsis: "
            + ", ".join(parts))


def global_parameter_error(key, needs_value):
    if needs_value:
        return f"The --{key} global parameter needs a value."
    return f"The --{key} global parameter does not accept a value."


def command_disabled(path):
    return f"The '{path}' command has been disabled."


def deprecated_global_parameter(key):
    return f"The --{key} global parameter is deprecated."


def alias_not_found(name, suggestion=None):
    return _with_suggestion(f"Alias '{name}' not found.", suggestion)


def alias_group_invalid(group, invalid):
    return (f"Group '{group}' contains one or more invalid aliases: "
            + ", ".join(invalid) + ".")


def alias_all_without_aliases():
    return "Cannot use '@all' when no aliases are registered."


def ssh_connection_failed():
    return "Cannot connect over SSH using provided configuration."


def _reason(exc):
    return getattr(exc, "strerror", None) or str(exc)


def config_unwritable(path, exc):
    return f"Unable to write the global config file '{path}': {_reason(exc)}."


def config_unreadable(path, exc):
    return f"Unable to read the config file '{path}': {_reason(exc)}."


def config_unparsable(path, exc):
    return f"Unable to parse the config file '{path}': {exc}"


def invalid_field(name):
    return f"Invalid field: {name}."


def invalid_json(raw):
    return f"Invalid JSON: {raw}"


def redacted():
    return "[redacted]"


def operation_cancelled():
    return "Operation cancelled."


def invalid_format(fmt, supported):
    return f"Invalid format: {fmt}. Supported formats: " + ", ".join(supported)


def directory_uncreatable(path, exc):
    return f"Failed to create directory '{path}': {_reason(exc)}."


def spawned_exit_minus_one():
    return ("Spawned process returned exit code -1, which could be caused by the "
            "signal handling configuration (e.g. SIGCHLD being ignored).")


def unsupported_archive():
    return "Extraction only supported for '.zip' and '.tar.gz' file types."


def archive_not_found(path):
    return f"Archive '{path}' does not exist."


def zip_unavailable():
    return "Extracting a zip file requires a zip archive extension (zipfile)."


def tar_unavailable():
    return "Extracting a tar.gz file requires tar.gz support (tarfile or 'tar')."


def archive_extraction_failed(path, reason):
    return f"Failed to extract '{path}': {reason}"


def tarfile_fallback(reason):
    return f"tarfile extraction failed, falling back to 'tar xz' ({reason})."


def unable_to_copy(relative):
    return f"Unable to copy '{relative}' to current directory."


def overwrite_failed():
    return "There was an error overwriting existing files."


def archive_extracted(archive, destination):
    return f"Extracted '{archive}' to '{destination}'."


def db_connection_failed(details):
    return f"Unable to initialize connection to {_PROGRAM} sqlite database: {details}"


def db_table_creation_failed(details):
    return f"Encountered Error while creating table: {details}"


def container_runtime_missing():
    return ("Container runtime is not installed. "
            "Please install the container runtime to run AppCtl.")


def custom_compose_missing(path):
    return f"File: {path} does not exist. Falling back to default compose file."


def no_compose_file(directory):
    return f"No compose file found in '{directory}'."


def compose_unparsable(path, exc):
    return f"Unable to parse the compose file '{path}': {exc}"


def network_connected(container):
    return f"Site connected to {container}."


def network_connect_failed(container):
    return f"There was some error connecting to {container}."


def network_disconnected(network, container):
    return f"[{network}] Disconnected from Docker network of {container}"


def network_disconnect_failed(container):
    return f"Error in disconnecting from Docker network of {container}"


def migration_file_not_found(path):
    return f"Unable to find migration file at '{path}'."


def migration_without_up(path):
    return f"Migration file '{path}' does not define an up() function."


def migration_failed(name, reason):
    return f"Encountered error while running migration '{name}': {reason}"


def migration_rollback_failed(name, reason):
    return f"Unable to roll back migration '{name}': {reason}"


def migration_source_reserved(path):
    return f"Ignoring migrations of '{path}': the extension name is reserved."


def migration_error():
    return "There was some error while migrating. Please check logs."


def insufficient_disk_space(path, free_gb):
    return (f"Minimum 5GB disk space is required to upgrade. Only {free_gb:.2f}GB is "
            f"available on the filesystem containing '{path}'.")


def image_pull_failed(image):
    return f"Unable to pull {image}. Please check logs for more details."


def image_versions_unreadable(path, reason):
    return f"Unable to read the image versions file '{path}': {reason}"


def compose_upgrade_failed(reason):
    return f"Unable to upgrade the compose tool: {reason}. Keeping the installed version."


def compose_upgraded(old, new):
    return f"Upgraded the compose tool from {old} to {new}."


def project_skipped(name, reason):
    return f"Skipping containers of project '{name}': {reason}"


def cleanup_failed(what, reason):
    return f"Unable to prune old {what}: {reason}"


def upgrade_completed():
    return "Migrations and upgrades completed."


# --- system requirements and startup -------------------------------------------------

_BREW_HINT = "Install it with Homebrew: `brew install --cask docker`."


def container_runtime_unavailable(darwin=False):
    message = ("Container runtime is not installed or not running. "
               "Please install and start the container runtime to run AppCtl.")
    return f"{message} {_BREW_HINT}" if darwin else message


def compose_not_installed():
    return "Compose tool is not installed. Please install the compose tool to run AppCtl."


def compose_too_old(version, minimum):
    found = f" (found {version})" if version is not None else ""
    return f"AppCtl requires compose tool version {minimum} or newer{found}."


def runtime_too_old(version, minimum):
    return f"AppCtl requires Python {minimum} or newer (found {version})."


def first_run_completed():
    return "AppCtl has been set up successfully."


def darwin_runtime_instructions(root_dir):
    return ("To finish setting up the container runtime on macOS, open Docker Desktop, "
            "go to Settings > Resources > File sharing and add "
            f"'{root_dir}' and your projects directory to the shared paths, "
            "then apply and restart Docker Desktop.")


def binary_older_than_database(binary, stored):
    return (f"AppCtl version {binary} is older than the version {stored} "
            "used to set up this system.")


def update_required(binary, stored):
    return (binary_older_than_database(binary, stored)
            + f" Please update AppCtl to {stored} or newer using 'appctl cli update'.")


def auto_update_failed(reason):
    return f"Automatic update failed: {reason}"


def uninstall_dependencies_down():
    return "Unable to proceed with uninstallation. Seems there is a dependency down."


def uninstall_confirmation():
    return ("Are you sure you want to remove AppCtl and all its projects "
            "(along with their data)?\nThis is an irreversible action. No backup will be kept.")


def uninstall_completed():
    return "AppCtl and all its data has been removed successfully."


def uninstall_step_failed(what, reason):
    return f"Unable to remove {what}: {reason}"


# --- self-update -----------------------------------------------------------------

def self_update_unavailable():
    return "Self-update is not available. Please use your system package manager to update."


def releases_unavailable(url, reason):
    return f"Failed to get the latest version from {url}: {reason}"


def no_stable_release():
    return "Unable to find a stable release of AppCtl."


def at_latest_version(update_type=None):
    kind = f" {update_type}" if update_type else ""
    return f"AppCtl is at the latest{kind} version."


def update_confirmation(current, target):
    return f"You have version {current}. Would you like to update to {target}?"


def binary_not_writable(path):
    return f"{path} is not writable by current user."


def download_failed(url, reason):
    return f"Unable to download {url}: {reason}"


def checksum_mismatch(actual, expected):
    return (f"The checksum of the download ({actual}) is different from the "
            f"release checksum ({expected}).")


def update_broken(reason):
    return (f"The downloaded update is broken ({reason}). The installed version was kept; "
            "try running 'appctl cli update' again.")


def update_completed(version):
    return f"Updated AppCtl to {version}."


def invalid_shell(shell, supported):
    return f"Invalid shell: {shell}. Supported shells: " + ", ".join(supported)


def invalid_point(point):
    return f"Point must be an integer, got '{point}'."
