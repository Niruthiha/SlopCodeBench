import io
import os
import subprocess
import sys

import pytest

from appctl_core.app import run
from appctl_core.command_tree import CommandTree
from appctl_core.suggest import suggest
from appctl_core.synopsis import Synopsis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def call(*argv, env=None, tree=None):
    out, err = io.StringIO(), io.StringIO()
    code = run(list(argv), env or {}, out, err, tree=tree)
    return code, out.getvalue(), err.getvalue()


# --- entry point ---------------------------------------------------------

def test_script_runs_as_subprocess():
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "appctl.py"), "sit"],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    assert proc.stderr == ("Error: 'sit' is not a registered appctl command. "
                           "See 'appctl help' for available commands.\n"
                           "Did you mean 'site'?\n")


def test_no_arguments_lists_sorted_aligned_commands():
    code, out, err = call()
    assert code == 0 and err == ""
    lines = [l for l in out.splitlines() if l.startswith("  ")]
    names = [l.split()[0] for l in lines]
    assert names == sorted(names, key=str.casefold)
    assert {"site", "cli", "help"} <= set(names)
    desc_cols = {len(l) - len(l[2:].split(None, 1)[1]) for l in lines}
    assert len(desc_cols) == 1


def test_help_command_matches_no_args():
    assert call("help")[1] == call()[1]


# --- rewrites ----------------------------------------------------------------

def test_version_rewrite():
    assert call("--version") == call("cli", "version")
    assert call("--version")[1] == "1.0.0\n"


def test_help_flag_rewrite():
    assert call("site", "create", "--help") == call("help", "site", "create")
    code, out, _ = call("site", "--help")
    assert code == 0 and "SUBCOMMANDS" in out and "create" in out


def test_help_flag_on_unknown_command():
    code, _, err = call("sitez", "--help")
    assert code == 1 and "'sitez' is not a registered appctl command" in err


# --- dispatch ----------------------------------------------------------------

def test_group_without_handler_prints_usage_with_subcommands():
    code, out, _ = call("site")
    assert code == 0
    assert out.startswith("usage: appctl site archive")
    assert "   or: appctl site create <site-name>" in out


def test_unknown_subcommand_with_suggestion():
    code, out, err = call("site", "creat", "foo")
    assert code == 1 and out == ""
    assert err == ("Error: 'creat' is not a registered subcommand of 'site'. "
                   "See 'appctl help site' for available subcommands.\n"
                   "Did you mean 'create'?\n")


def test_unknown_command_without_suggestion():
    code, _, err = call("zzzzzz")
    assert code == 1 and "Did you mean" not in err


def test_alias_dispatches_without_synonym_suggestion():
    code, out, err = call("site", "new", "foo")
    assert code == 0 and err == "" and "Site 'foo' created" in out
    assert call("cfg", "get", "DB_NAME")[1] == "app\n"


def test_synonym_suggestion_only_when_registered():
    assert "Did you mean 'delete'?" in call("post", "trash", "1")[2]
    assert "Did you mean" not in call("plugin", "add", "x")[2]


# --- validation ---------------------------------------------------------------

def test_missing_positional_prints_usage():
    code, out, err = call("site", "create")
    assert code == 1 and err == ""
    assert out.startswith("usage: appctl site create <site-name> [--type=<type>]")


def test_too_many_positionals():
    code, _, err = call("site", "create", "a", "b", "c")
    assert code == 1 and err == "Error: Too many positional arguments: b c\n"


def test_repeating_positional_accepts_many():
    assert call("site", "archive", "a", "b", "c")[0] == 0


def test_missing_and_unknown_associative_errors_are_collected():
    code, _, err = call("user", "create", "bob", "--email=", "--rol=x", "--zzz")
    assert code == 1
    assert err == ("Error: Parameter errors:\n"
                   " missing --email parameter\n"
                   " unknown --rol parameter\n"
                   "Did you mean '--role'?\n"
                   " unknown --zzz parameter\n")


def test_unknown_flag_rejected():
    code, _, err = call("site", "create", "foo", "--forse")
    assert code == 1 and "unknown --forse parameter" in err


def test_defaults_applied():
    assert "type: standard" in call("site", "create", "foo")[1]
    assert "type: blog" in call("site", "create", "foo", "--type=blog")[1]
    assert call("cache", "incr", "k")[1].splitlines()[0] == "1"


def test_negated_flag():
    assert call("config", "set", "A", "1", "--no-raw")[0] == 0
    assert "(raw)" in call("config", "set", "A", "1", "--raw")[1]


def test_generic_field_accepts_any_key():
    code, out, _ = call("site", "update", "foo", "--anything=1")
    assert code == 0 and "anything=1" in out


def test_malformed_synopsis_rejected():
    tree = CommandTree()
    tree.register("bad", lambda ctx: 0, synopsis="<ok> --=oops")
    code, _, err = call("bad", "x", tree=tree)
    assert code == 1 and "--=oops" in err


# --- strict mode ------------------------------------------------------------

def test_global_flag_anywhere_without_strict_mode():
    assert call("site", "create", "foo", "--url=x")[0] == 0


def test_strict_mode_treats_later_args_as_command_specific():
    env = {"APPCTL_STRICT_ARGS_MODE": "1"}
    code, _, err = call("site", "create", "foo", "--url=x", env=env)
    assert code == 1 and "unknown --url parameter" in err
    assert call("--url=x", "site", "create", "foo", env=env)[0] == 0
    assert call("site", "create", "foo", "--url=x", env={"APPCTL_STRICT_ARGS_MODE": ""})[0] == 0


# --- units ------------------------------------------------------------------

def test_synopsis_classification():
    s = Synopsis("<a> [<b>...] --k=<v> [--f] [--[no-]c] [--<field>=<value>] bogus")
    assert s.required_positional_count() == 1
    assert s.positional_limit() is None
    assert s.option_names() == ["k", "f", "c"]
    assert s.required_option_names() == ["k"]
    assert s.accepts_any_option()
    assert s.malformed_parts() == ["bogus"]
    assert s.interpret("no-c", None) == ("c", False, Synopsis.OK)


def test_suggest_is_deterministic():
    assert suggest("cat", ["car", "bat"]) == "bat"
    assert suggest("cat", ["bat", "car"]) == "bat"
    assert suggest("xyzzy", ["create"]) is None


def test_case_insensitive_suggestion():
    assert "Did you mean 'site'?" in call("SITE")[2]
