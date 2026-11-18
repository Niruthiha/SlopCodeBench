"""Container, compose project and network commands.

Secret: which project directory a command operates on, how command options
override configuration, and how runtime outcomes map to output and exit
codes.
"""

import os

from . import containers, yaml_lite
from .errors import CliError

_COMPOSE = "[--custom-compose=<file>]"


class _Settings:
    """Effective configuration with command options layered on top."""

    def __init__(self, config, overrides):
        self._config = config
        self._overrides = {k: v for k, v in overrides.items() if v is not None}

    def get(self, name, default=None):
        if name in self._overrides:
            return self._overrides[name]
        return self._config.get(name, default)


def _runtime(ctx):
    overrides = {"custom-compose": ctx.args.option("custom-compose")}
    if ctx.args.option("skip-tty"):
        overrides["skip-tty"] = True
    return containers.Runtime(out=ctx.out, env=ctx.env, cwd=ctx.cwd,
                              config=_Settings(ctx.config, overrides))


def _project_dir(ctx):
    path = ctx.config.path() or ctx.cwd
    return os.path.join(ctx.cwd, os.path.expanduser(str(path)))


def _relay(ctx, result):
    if result.stdout:
        ctx.out.line(result.stdout.rstrip("\n"))
    if result.stderr:
        ctx.out.write_stderr(result.stderr.rstrip("\n"))
    return result.return_code


# --- site -----------------------------------------------------------------------

def _site_config(ctx):
    runtime = _runtime(ctx)
    project = _project_dir(ctx)
    if ctx.args.option("services"):
        for name in runtime.services(project):
            ctx.out.line(name)
        return 0
    definition = runtime.compose_definition(project)
    ctx.out.line(yaml_lite.dump(definition).rstrip("\n") if definition else "{}")
    return 0


def _site_has_service(ctx):
    return 0 if _runtime(ctx).service_exists(_project_dir(ctx), ctx.args.positional(0)) else 1


def _site_up(ctx):
    result = _runtime(ctx).compose_up(_project_dir(ctx), ctx.args.positionals)
    code = _relay(ctx, result)
    if code:
        return code
    ctx.out.success("Services are up.")
    return 0


def _site_down(ctx):
    result = _runtime(ctx).compose_down(_project_dir(ctx))
    code = _relay(ctx, result)
    if code:
        return code
    ctx.out.success("Services are down.")
    return 0


def _site_exec(ctx):
    service, *command = ctx.args.positionals
    return _runtime(ctx).compose_exec(
        _project_dir(ctx), service, command, user=ctx.args.option("exec-user"),
        shell=ctx.args.option("shell"), shell_wrapper=bool(ctx.args.option("shell-wrapper")),
        interactive=True)


# --- container ------------------------------------------------------------------

def _container_status(ctx):
    status = _runtime(ctx).container_status(ctx.args.positional(0))
    ctx.out.line(status or "missing")
    return 0 if status else 1


def _container_boot(ctx):
    runtime = _runtime(ctx)
    service = ctx.args.option("service")
    project = _project_dir(ctx)
    create = lambda: runtime.compose_up(project, [service] if service else []).succeeded
    if not runtime.boot_container(ctx.args.positional(0), create=create):
        raise CliError(f"Unable to boot container '{ctx.args.positional(0)}'.")
    return 0


def _container_action(verb, method):
    def handler(ctx):
        name = ctx.args.positional(0)
        if not getattr(_runtime(ctx), method)(name):
            raise CliError(f"Unable to {verb} container '{name}'.")
        return 0
    return handler


# --- network --------------------------------------------------------------------

def _network_create(ctx):
    project = ctx.args.positional(0)
    if not _runtime(ctx).create_network(project, ctx.args.option("name")):
        raise CliError(f"Unable to create network '{ctx.args.option('name') or project}'.")
    return 0


def _network_exists(ctx):
    exists = _runtime(ctx).network_exists(ctx.args.positional(0))
    ctx.out.line("true" if exists else "false")
    return 0 if exists else 1


def _network_connect(ctx):
    network, container = ctx.args.positionals[:2]
    _runtime(ctx).connect_network(network, container)
    return 0


def _network_disconnect(ctx):
    network, container = ctx.args.positionals[:2]
    _runtime(ctx).disconnect_network(network, container)
    return 0


def _network_remove(ctx):
    name = ctx.args.positional(0)
    if not _runtime(ctx).remove_network(name):
        raise CliError(f"Unable to remove network '{name}'.")
    return 0


def register(tree):
    r = tree.register

    r("site config", _site_config, synopsis=f"[--services] {_COMPOSE}",
      description="Shows the merged compose configuration of the project.")
    r("site down", _site_down, synopsis=_COMPOSE,
      description="Removes the containers, networks and volumes of the project.")
    r("site exec", _site_exec,
      synopsis="<service> <command>... [--exec-user=<user>] [--shell=<shell>] "
               f"[--shell-wrapper] [--skip-tty] {_COMPOSE}",
      description="Runs a command inside a service container.", defaults={"shell": "sh"})
    r("site has-service", _site_has_service, synopsis=f"<service> {_COMPOSE}",
      description="Detects if a service exists in the project.")
    r("site up", _site_up, synopsis=f"[<service>...] {_COMPOSE}",
      description="Starts the services of the project in the background.")

    r("container", description="Inspects, boots, starts, stops and restarts containers.")
    r("container boot", _container_boot, synopsis=f"<name> [--service=<service>] {_COMPOSE}",
      description="Ensures a container is running, creating it when missing.")
    r("container restart", _container_action("restart", "restart_container"),
      synopsis="<name>", description="Restarts a container.")
    r("container start", _container_action("start", "start_container"),
      synopsis="<name>", description="Starts a stopped container.")
    r("container status", _container_status, synopsis="<name>",
      description="Prints whether a container is running, exited or missing.")
    r("container stop", _container_action("stop", "stop_container"),
      synopsis="<name>", description="Stops a running container.")

    r("network", description="Creates, connects, disconnects and removes networks.")
    r("network connect", _network_connect, synopsis="<network> <container>",
      description="Connects a project network to a container.")
    r("network create", _network_create, synopsis="<project> [--name=<name>]",
      description="Creates the network of a project.")
    r("network disconnect", _network_disconnect, synopsis="<network> <container>",
      description="Disconnects a project network from a container.")
    r("network exists", _network_exists, synopsis="<name>",
      description="Detects if a network exists.")
    r("network remove", _network_remove, alias="rm", synopsis="<name>",
      description="Removes a network.")
