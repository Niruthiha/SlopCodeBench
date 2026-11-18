"""Lazily-described completion candidates.

An entry stands for whatever a name refers to; its value and description are
only computed when the name survives prefix filtering.
"""
from .describe import (
    describe_class,
    describe_function,
    describe_module,
    describe_param,
    describe_value,
)

_UNSET = object()


class BindingEntry:
    """A name bound by a statement in parsed source."""

    def __init__(self, binding, inferrer):
        self.binding = binding
        self.inferrer = inferrer

    def value(self):
        return self.inferrer.infer_binding(self.binding)

    def describe(self, name):
        kind = self.binding.kind
        if kind == "param":
            return describe_param(name)
        if kind == "def":
            return describe_function(name)
        if kind == "class":
            return describe_class(name)
        if kind == "import":
            return describe_module(name)
        return describe_value(name, self.value())


class ValueEntry:
    """A name whose value is produced on demand by a factory."""

    def __init__(self, factory):
        self._factory = factory
        self._value = _UNSET

    def value(self):
        if self._value is _UNSET:
            try:
                self._value = self._factory()
            except Exception:
                self._value = None
        return self._value

    def describe(self, name):
        return describe_value(name, self.value())
