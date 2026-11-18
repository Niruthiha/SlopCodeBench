"""Recursive-descent parser turning DSL source into a Program."""
from . import dtypes
from .ast_nodes import (POST_AGG, PRE, AggItem, Aggregate, Apply, Binary, Calc, Call, Cast,
                        ColumnRef, FieldDecl, Filter, GroupBy, InExpr, Literal, ParamDecl,
                        Program, SchemaDecl, Unary, Window)
from .errors import DSLSyntaxError
from .functions import ARITY, STRING_PREDICATES, WINDOW_FUNCTIONS
from .lexer import DURATION, DURATION_UNITS, EOF, IDENT, NUMBER, STRING, Token
from .lexer import split_statements, tokenize

AGG_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")
COMPARISON_OPS = ("<", "<=", ">", ">=", "==", "!=")
RESERVED = ("true", "false", "in")
TYPE_NAMES = (dtypes.STRING, dtypes.INT, dtypes.FLOAT, dtypes.BOOL, dtypes.TIMESTAMP)
STAGES = (PRE, POST_AGG)


def parse_program(source):
    """Parse a DSL file: either bare Part 1 statements or schema/pipeline blocks."""
    return _DocumentParser(split_statements(tokenize(source))).parse()


def _build_program(statements, **extra):
    row_ops, calcs, group_by, window, aggregate = [], [], None, None, None
    for stmt in statements:
        if isinstance(stmt, (Filter, Apply)):
            row_ops.append(stmt)
        elif isinstance(stmt, Calc):
            calcs.append(stmt)
        elif isinstance(stmt, GroupBy):
            if group_by is not None:
                raise DSLSyntaxError(f"line {stmt.line}: group_by may appear at most once")
            group_by = stmt
        elif isinstance(stmt, Window):
            if window is not None:
                raise DSLSyntaxError(f"line {stmt.line}: window may appear at most once")
            window = stmt
        elif isinstance(stmt, Aggregate):
            if aggregate is not None:
                raise DSLSyntaxError(f"line {stmt.line}: aggregate must appear exactly once")
            aggregate = stmt
    if aggregate is None:
        raise DSLSyntaxError("missing required aggregate statement")

    _check_output_names(group_by, aggregate, window, calcs)
    return Program(row_ops, group_by, window, aggregate, calcs=calcs, **extra)


def _check_output_names(group_by, aggregate, window, calcs):
    reserved = {"window_start", "window_end"} if window else set()
    taken = set()
    if group_by:
        for col in group_by.columns:
            if col in reserved:
                raise DSLSyntaxError(f"line {group_by.line}: group_by column '{col}' "
                                     "clashes with a window output field")
            taken.add(col)
    for item in aggregate.items:
        if item.alias in taken or item.alias in reserved:
            raise DSLSyntaxError(f"line {item.line}: output name '{item.alias}' is not unique")
        taken.add(item.alias)

    calc_names = set()
    for calc in calcs:
        if calc.name in calc_names:
            raise DSLSyntaxError(f"line {calc.line}: duplicate calc '{calc.name}'")
        calc_names.add(calc.name)
        if calc.stage == POST_AGG and (calc.name in taken or calc.name in reserved):
            raise DSLSyntaxError(f"line {calc.line}: calc '{calc.name}' collides with an "
                                 "existing output field")


class _DocumentParser:
    """Splits logical statements into schema blocks, one pipeline block, or bare statements."""

    def __init__(self, statements):
        self.statements = statements
        self.pos = 0

    def parse(self):
        schemas = {}
        pipeline = None
        loose = []
        while self.pos < len(self.statements):
            stmt = self._next()
            head = stmt[0]
            if head.is_ident("schema"):
                decl = self._parse_schema(stmt)
                if decl.name in schemas:
                    raise DSLSyntaxError(f"line {head.line}: duplicate schema '{decl.name}'")
                schemas[decl.name] = decl
            elif head.is_ident("pipeline"):
                if pipeline is not None:
                    raise DSLSyntaxError(f"line {head.line}: only one pipeline block is allowed")
                pipeline = self._parse_pipeline(stmt)
            elif head.is_op("{", "}"):
                _unexpected(head)
            else:
                loose.append(stmt)

        if not schemas and pipeline is None:
            return _build_program([_StatementParser(s).parse_statement() for s in loose])
        if loose:
            raise DSLSyntaxError(f"line {loose[0][0].line}: statements must appear inside "
                                 "the pipeline block")
        if pipeline is None:
            raise DSLSyntaxError("missing pipeline block")
        name, schema_name, params, body = pipeline
        if schema_name not in schemas:
            raise DSLSyntaxError(f"pipeline '{name}' uses unknown schema '{schema_name}'")
        return _build_program(body, params=params, schema_name=schema_name,
                              schemas=schemas, name=name)

    def _next(self):
        stmt = self.statements[self.pos]
        self.pos += 1
        return stmt

    def _header(self, stmt):
        """Return a block header's tokens without its opening '{'."""
        if stmt[-1].is_op("{"):
            return stmt[:-1]
        if self.pos < len(self.statements):
            nxt = self.statements[self.pos]
            if len(nxt) == 1 and nxt[0].is_op("{"):
                self.pos += 1
                return stmt
        last = stmt[-1]
        raise DSLSyntaxError(f"line {last.line}: expected '{{' after '{stmt[0].value}' header")

    def _block(self, opener):
        """Yield the statements of a block up to (and consuming) its closing '}'."""
        while self.pos < len(self.statements):
            stmt = self._next()
            if len(stmt) == 1 and stmt[0].is_op("}"):
                return
            yield stmt
        raise DSLSyntaxError(f"line {opener.line}: unclosed '{opener.value}' block")

    def _parse_schema(self, stmt):
        head = stmt[0]
        p = _StatementParser(self._header(stmt))
        p.advance()
        name = p.expect_ident("a schema name")
        base = None
        if p.tok.is_ident("extends"):
            p.advance()
            base = p.expect_ident("a base schema name")
            if p.tok.is_op(","):
                p.error("multiple inheritance is not allowed")
        p.expect_end()

        fields = []
        seen = set()
        for field_stmt in self._block(head):
            field = _StatementParser(field_stmt).parse_field()
            if field.name in seen:
                raise DSLSyntaxError(f"line {field.line}: duplicate field '{field.name}' "
                                     f"in schema '{name}'")
            seen.add(field.name)
            fields.append(field)
        return SchemaDecl(name, base, fields, head.line)

    def _parse_pipeline(self, stmt):
        head = stmt[0]
        p = _StatementParser(self._header(stmt))
        p.advance()
        name = p.expect_ident("a pipeline name")
        if not p.tok.is_ident("using"):
            p.error(f"expected 'using <SchemaName>' but found {p.tok.describe()}")
        p.advance()
        schema_name = p.expect_ident("a schema name")
        p.expect_end()

        params = None
        body = []
        for body_stmt in self._block(head):
            first = body_stmt[0]
            if first.is_ident("params") and (body_stmt[-1].is_op("{") or len(body_stmt) == 1):
                if params is not None:
                    raise DSLSyntaxError(f"line {first.line}: params may appear at most once")
                params = self._parse_params(body_stmt)
            elif first.is_ident("schema", "pipeline"):
                raise DSLSyntaxError(f"line {first.line}: '{first.value}' blocks cannot be nested")
            elif first.is_op("{", "}") or body_stmt[-1].is_op("{"):
                _unexpected(body_stmt[-1] if not first.is_op("{", "}") else first)
            else:
                body.append(_StatementParser(body_stmt).parse_statement())
        return name, schema_name, params or [], body

    def _parse_params(self, stmt):
        head = stmt[0]
        p = _StatementParser(self._header(stmt))
        p.advance()
        p.expect_end()
        params = []
        seen = set()
        for param_stmt in self._block(head):
            decl = _StatementParser(param_stmt).parse_param_decl()
            if decl.name in seen:
                raise DSLSyntaxError(f"line {decl.line}: duplicate parameter '{decl.name}'")
            seen.add(decl.name)
            params.append(decl)
        return params


def _unexpected(tok):
    raise DSLSyntaxError(f"line {tok.line}:{tok.col}: unexpected {tok.describe()}")


class _StatementParser:
    """Parses the tokens of one logical statement."""

    def __init__(self, tokens):
        self.tokens = tokens + [Token(EOF, None, tokens[-1].line, 0)]
        self.pos = 0

    # -- token helpers -------------------------------------------------
    @property
    def tok(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != EOF:
            self.pos += 1
        return tok

    def error(self, message, tok=None):
        tok = tok or self.tok
        raise DSLSyntaxError(f"line {tok.line}:{tok.col}: {message}")

    def expect_op(self, op):
        if not self.tok.is_op(op):
            self.error(f"expected '{op}' but found {self.tok.describe()}")
        return self.advance()

    def expect_ident(self, what):
        tok = self.tok
        if tok.kind != IDENT or tok.value in RESERVED:
            self.error(f"expected {what} but found {tok.describe()}")
        return self.advance().value

    def expect_column(self, what="a column name"):
        """A column name, written bare or as a string literal."""
        if self.tok.kind == STRING:
            return self.advance().value
        return self.expect_ident(what)

    def expect_end(self):
        if self.tok.kind != EOF:
            self.error(f"unexpected {self.tok.describe()}")

    # -- statements ----------------------------------------------------
    def parse_statement(self):
        head = self.tok
        if head.kind != IDENT:
            self.error(f"expected a statement but found {head.describe()}")
        handler = {
            "filter": self.parse_filter,
            "apply": self.parse_apply,
            "group_by": self.parse_group_by,
            "window": self.parse_window,
            "aggregate": self.parse_aggregate,
            "calc": self.parse_calc,
        }.get(head.value)
        if handler is None:
            self.error(f"unknown statement '{head.value}'")
        self.advance()
        stmt = handler(head.line)
        self.expect_end()
        return stmt

    def parse_type(self):
        tok = self.tok
        if tok.kind != IDENT or tok.value not in TYPE_NAMES:
            self.error(f"expected a type ({', '.join(TYPE_NAMES)}) but found {tok.describe()}")
        self.advance()
        return tok.value

    def parse_field(self):
        """`name: type [= expr]` inside a schema block."""
        tok = self.tok
        name = self.expect_ident("a field name")
        self.expect_op(":")
        field_type = self.parse_type()
        expr = None
        if self.tok.is_op("="):
            self.advance()
            expr = self.parse_expr()
        self.expect_end()
        return FieldDecl(name, field_type, expr, tok.line)

    def parse_param_decl(self):
        """`name [: type] [= literal]` inside a params block."""
        tok = self.tok
        name = self.expect_ident("a parameter name")
        param_type = None
        default = None
        if self.tok.is_op(":"):
            self.advance()
            param_type = self.parse_type()
        if self.tok.is_op("="):
            self.advance()
            lit_tok = self.tok
            default = self.parse_unary()
            if not isinstance(default, Literal):
                self.error("parameter default must be a literal", lit_tok)
        self.expect_end()
        return ParamDecl(name, param_type, default, tok.line)

    def parse_calc(self, line):
        name = self.expect_ident("a calc name")
        self.expect_op("=")
        expr = self.parse_expr()
        self.expect_op(":")
        declared = self.parse_type()
        stage = PRE
        if self.tok.is_op("@"):
            self.advance()
            if not self.tok.is_ident("stage"):
                self.error(f"expected 'stage' after '@' but found {self.tok.describe()}")
            self.advance()
            self.expect_op("(")
            tok = self.tok
            if tok.kind != IDENT or tok.value not in STAGES:
                self.error(f"expected a stage (pre or post_agg) but found {tok.describe()}")
            self.advance()
            stage = tok.value
            self.expect_op(")")
        return Calc(name, expr, declared, stage, line)

    def parse_filter(self, line):
        self.expect_op("(")
        expr = self.parse_expr()
        self.expect_op(")")
        return Filter(expr, line)

    def parse_apply(self, line):
        self.expect_op("(")
        expr = self.parse_expr()
        self.expect_op(",")
        name = self.expect_ident("a new column name")
        self.expect_op(")")
        return Apply(expr, name, line)

    def parse_group_by(self, line):
        self.expect_op("(")
        if self.tok.is_op("["):
            self.advance()
            columns = [self.expect_column()]
            while self.tok.is_op(","):
                self.advance()
                columns.append(self.expect_column())
            self.expect_op("]")
        else:
            columns = [self.expect_column()]
        self.expect_op(")")
        if len(set(columns)) != len(columns):
            raise DSLSyntaxError(f"line {line}: duplicate column in group_by")
        return GroupBy(columns, line)

    def parse_window(self, line):
        self.expect_op("(")
        tok = self.tok
        if tok.is_ident("param"):
            call = self.parse_primary()
            if not isinstance(call, Call):
                self.error("expected param(\"<name>\") or a duration literal", tok)
            self.expect_op(")")
            return Window(None, None, None, line, param=call.args[0].value)
        if tok.kind != DURATION:
            self.error(f"expected a duration literal like 10m, 1h or 7d but found {tok.describe()}")
        self.advance()
        amount, unit = tok.value
        if amount <= 0:
            self.error("window duration must be positive", tok)
        self.expect_op(")")
        return Window(amount, unit, amount * DURATION_UNITS[unit], line)

    def parse_aggregate(self, line):
        items = [self.parse_agg_item()]
        while self.tok.is_op(","):
            self.advance()
            items.append(self.parse_agg_item())
        return Aggregate(items, line)

    def parse_agg_item(self):
        tok = self.tok
        if tok.kind != IDENT:
            self.error(f"expected an aggregate function but found {tok.describe()}")
        if tok.value not in AGG_FUNCTIONS:
            self.error(f"unknown aggregate function '{tok.value}'")
        self.advance()
        self.expect_op("(")
        if self.tok.is_op("*"):
            self.advance()
            column = None
        else:
            column = self.expect_column("a column name or '*'")
        self.expect_op(")")
        if not self.tok.is_ident("as"):
            self.error(f"expected 'as <alias>' but found {self.tok.describe()}")
        self.advance()
        alias = self.expect_ident("an alias")
        return AggItem(tok.value, column, alias, tok.line)

    # -- expressions ---------------------------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.tok.is_op("|"):
            op = self.advance()
            left = Binary("|", left, self.parse_and(), op.line)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.tok.is_op("&"):
            op = self.advance()
            left = Binary("&", left, self.parse_not(), op.line)
        return left

    def parse_not(self):
        if self.tok.is_op("!"):
            op = self.advance()
            return Unary("!", self.parse_not(), op.line)
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.tok
        if tok.kind == "OP" and tok.value in COMPARISON_OPS:
            self.advance()
            node = Binary(tok.value, left, self.parse_additive(), tok.line)
        elif tok.is_ident("in"):
            self.advance()
            node = InExpr(left, self.parse_additive(), tok.line)
        elif tok.is_ident(*STRING_PREDICATES):
            self.advance()
            node = Call(tok.value, [left, self.parse_additive()], tok.line)
        else:
            return left
        nxt = self.tok
        if ((nxt.kind == "OP" and nxt.value in COMPARISON_OPS)
                or nxt.is_ident("in", *STRING_PREDICATES)):
            self.error("comparisons cannot be chained; use parentheses and '&'")
        return node

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.tok.is_op("+", "-"):
            op = self.advance()
            left = Binary(op.value, left, self.parse_multiplicative(), op.line)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.tok.is_op("*", "/", "%"):
            op = self.advance()
            left = Binary(op.value, left, self.parse_unary(), op.line)
        return left

    def parse_unary(self):
        if self.tok.is_op("-", "+"):
            op = self.advance()
            operand = self.parse_unary()
            if isinstance(operand, Literal) and dtypes.is_numeric(operand.type):
                value = -operand.value if op.value == "-" else operand.value
                return Literal(value, operand.type)
            return Unary(op.value, operand, op.line)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.tok
        if tok.kind == NUMBER:
            self.advance()
            return Literal(tok.value, dtypes.FLOAT if isinstance(tok.value, float) else dtypes.INT)
        if tok.kind == STRING:
            self.advance()
            return Literal(tok.value, dtypes.STRING)
        if tok.is_op("("):
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind == IDENT:
            if tok.value in ("true", "false"):
                self.advance()
                return Literal(tok.value == "true", dtypes.BOOL)
            if tok.value == "in":
                self.error("unexpected 'in'")
            self.advance()
            if self.tok.is_op("("):
                return self.parse_call(tok)
            return ColumnRef(tok.value, tok.line)
        self.error(f"expected an expression but found {tok.describe()}")

    def parse_call(self, name_tok):
        name = name_tok.value
        if name == "cast":
            return self.parse_cast(name_tok)
        if name not in ARITY:
            self.error(f"unknown function '{name}'", name_tok)
        self.expect_op("(")
        args = []
        if not self.tok.is_op(")"):
            args.append(self.parse_expr())
            while self.tok.is_op(","):
                self.advance()
                args.append(self.parse_expr())
        self.expect_op(")")
        lo, hi = ARITY[name]
        if not lo <= len(args) <= hi:
            expected = str(lo) if lo == hi else f"{lo} to {hi}"
            self.error(f"{name}() takes {expected} argument(s), got {len(args)}", name_tok)
        if name == "param":
            if not (isinstance(args[0], Literal) and args[0].type == dtypes.STRING):
                self.error("param() expects a parameter name as a string literal", name_tok)
        elif name in WINDOW_FUNCTIONS:
            k = args[1]
            is_param = isinstance(k, Call) and k.name == "param"
            is_positive_int = (isinstance(k, Literal) and k.type == dtypes.INT and k.value > 0)
            if not (is_param or is_positive_int):
                self.error(f"{name}() offset must be a positive integer literal "
                           "or an int param()", name_tok)
        return Call(name, args, name_tok.line)

    def parse_cast(self, name_tok):
        self.expect_op("(")
        operand = self.parse_expr()
        if not self.tok.is_ident("as"):
            self.error(f"expected 'as <type>' in cast() but found {self.tok.describe()}")
        self.advance()
        target = self.parse_type()
        self.expect_op(")")
        return Cast(operand, target, name_tok.line)
