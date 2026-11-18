---
name: test-env-docker
description: The workspace has a real docker client with the daemon down and compose 2.26.1; tests must use a fake docker on PATH
metadata:
  node_type: memory
  type: project
  originSessionId: 5a74fb44-4271-430f-973f-06a4b3cdda3e
  modified: 2026-11-11T04:41:07.870Z
---

In /workspace the host has a real `/usr/bin/docker` (daemon NOT running, `docker ps` fails) and
`/usr/bin/docker-compose` / `docker compose` at 2.26.1-4, below appctl's 2.27.0 minimum. `/bin`
is a symlink to `/usr/bin`, so the legacy compose binary is always on a normal PATH.

Run the code with `.venv/bin/python`; system python lacks PyYAML.

**Why:** appctl's system requirement checks (every command outside the cli/config/help
families) fail against the real host, and first-run setup prints to STDOUT on a fresh root.

**How to apply:** in subprocess tests put `tests/helpers.py` `runtime_env()` (fake docker that
reports compose 2.29.7) first on PATH, and call `initialize()` to complete the first run before
asserting exact output. To simulate "compose missing", use a PATH holding only the fake bin plus a
dir with a `/bin/sh` symlink.
