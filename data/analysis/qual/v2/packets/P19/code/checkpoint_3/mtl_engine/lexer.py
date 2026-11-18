"""Tokenizer for the MTL DSL, including logical-line joining."""
import re

from .errors import DSLSyntaxError

# Token kinds
IDENT = "IDENT"
NUMBER = "NUMBER"
STRING = "STRING"
DURATION = "DURATION"
OP = "OP"
NEWLINE = "NEWLINE"
EOF = "EOF"

_NUMBER_RE = re.compile(r"(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SUFFIX_RE = re.compile(r"[A-Za-z0-9_]+")
_OPERATORS = ("<=", ">=", "==", "!=", "<", ">", "&", "|", "!",
              "(", ")", "[", "]", ",", "*", "+", "-", "/", "%",
              "{", "}", ":", "=", "@")
DURATION_UNITS = {"m": 60, "h": 3600, "d": 86400}


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def is_op(self, *ops):
        return self.kind == OP and self.value in ops

    def is_ident(self, *names):
        return self.kind == IDENT and self.value in names

    def describe(self):
        if self.kind == EOF:
            return "end of input"
        if self.kind == NEWLINE:
            return "end of line"
        if self.kind == STRING:
            return f"string '{self.value}'"
        if self.kind == DURATION:
            return f"duration '{self.value[0]}{self.value[1]}'"
        return f"'{self.value}'"

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


def tokenize(source):
    """Turn DSL source into a list of tokens (with NEWLINE separators, ending in EOF)."""
    tokens = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        _tokenize_line(line, lineno, tokens)
        tokens.append(Token(NEWLINE, "\n", lineno, len(line) + 1))
    last_line = tokens[-1].line if tokens else 1
    tokens.append(Token(EOF, None, last_line, 0))
    return tokens


def _tokenize_line(line, lineno, out):
    pos = 0
    n = len(line)
    while pos < n:
        ch = line[pos]
        col = pos + 1
        if ch in " \t\r\f\v":
            pos += 1
        elif ch == "#":
            return
        elif ch in "'\"":
            end = line.find(ch, pos + 1)
            if end < 0:
                raise DSLSyntaxError(f"line {lineno}:{col}: unterminated string literal")
            value = line[pos + 1:end]
            if "\\" in value:
                raise DSLSyntaxError(
                    f"line {lineno}:{col}: escape sequences are not allowed in string literals"
                )
            out.append(Token(STRING, value, lineno, col))
            pos = end + 1
        elif ch.isdigit() or (ch == "." and pos + 1 < n and line[pos + 1].isdigit()):
            pos = _lex_number(line, pos, lineno, out)
        elif ch.isalpha() or ch == "_":
            m = _IDENT_RE.match(line, pos)
            out.append(Token(IDENT, m.group(0), lineno, col))
            pos = m.end()
        else:
            for op in _OPERATORS:
                if line.startswith(op, pos):
                    out.append(Token(OP, op, lineno, col))
                    pos += len(op)
                    break
            else:
                raise DSLSyntaxError(f"line {lineno}:{col}: unexpected character {ch!r}")


def _lex_number(line, pos, lineno, out):
    col = pos + 1
    m = _NUMBER_RE.match(line, pos)
    text = m.group(0)
    end = m.end()
    suffix_m = _SUFFIX_RE.match(line, end)
    if suffix_m:
        suffix = suffix_m.group(0)
        if text.isdigit() and suffix in DURATION_UNITS:
            out.append(Token(DURATION, (int(text), suffix), lineno, col))
            return suffix_m.end()
        raise DSLSyntaxError(f"line {lineno}:{col}: invalid literal '{text}{suffix}'")
    if "." in text or "e" in text or "E" in text:
        out.append(Token(NUMBER, float(text), lineno, col))
    else:
        out.append(Token(NUMBER, int(text), lineno, col))
    return end


def split_statements(tokens):
    """Group tokens into logical statements, joining continuation lines.

    A NEWLINE does not end a statement when brackets are open, when the
    previous token is ',' or a lone leading 'aggregate', or when the next
    token is ','. Outside brackets, '{' ends the statement it closes (a block
    header) and '}' always forms a statement of its own.
    """
    statements = []
    current = []
    depth = 0
    for i, tok in enumerate(tokens):
        if tok.kind == EOF:
            break
        if tok.kind == NEWLINE:
            if not current:
                continue
            nxt = _next_significant(tokens, i + 1)
            continues = (
                depth > 0
                or current[-1].is_op(",")
                or (len(current) == 1 and current[0].is_ident("aggregate"))
                or (nxt is not None and nxt.is_op(","))
            )
            if not continues:
                statements.append(current)
                current = []
            continue
        if depth == 0 and tok.is_op("{"):
            current.append(tok)
            statements.append(current)
            current = []
            continue
        if depth == 0 and tok.is_op("}"):
            if current:
                statements.append(current)
            statements.append([tok])
            current = []
            continue
        if tok.is_op("(", "["):
            depth += 1
        elif tok.is_op(")", "]"):
            depth -= 1
            if depth < 0:
                raise DSLSyntaxError(f"line {tok.line}:{tok.col}: unbalanced '{tok.value}'")
        current.append(tok)
    if current:
        if depth > 0:
            raise DSLSyntaxError(f"line {current[0].line}: unclosed bracket in statement")
        statements.append(current)
    return statements


def _next_significant(tokens, start):
    for tok in tokens[start:]:
        if tok.kind == NEWLINE:
            continue
        if tok.kind == EOF:
            return None
        return tok
    return None
