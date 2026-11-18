"""Error hierarchy; each error kind maps to a diagnostic type and exit code."""


class MTLError(Exception):
    kind = "runtime_error"
    exit_code = 4

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def diagnostic(self):
        msg = " ".join(str(self.message).split())
        return f"ERROR:{self.kind}:{msg}"


class DSLSyntaxError(MTLError):
    kind = "bad_dsl"
    exit_code = 1


class TypeCheckError(MTLError):
    kind = "type_error"
    exit_code = 2


class IOFailure(MTLError):
    kind = "bad_io"
    exit_code = 3


class RuntimeFailure(MTLError):
    kind = "runtime_error"
    exit_code = 4


class ConfigError(MTLError):
    kind = "config_error"
    exit_code = 5
