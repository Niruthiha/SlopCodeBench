"""Execution context handed to command handlers."""

from dataclasses import dataclass, field


@dataclass
class Context:
    root: object
    command: object
    output: object
    runtime: dict = field(default_factory=dict)
    strict: bool = False
    config: object = None
    alias: str = None
    cwd: str = None
    environ: dict = None
