"""Static analysis of RLL rungs and ST routines: which tags each statement reads and writes.

Used by the deterministic Safety Auditor (Agent 5). No LLM involvement.
"""

import re
from dataclasses import dataclass, field

from app.schemas.uir import Routine, RoutineLanguage


@dataclass(slots=True)
class Write:
    tag: str
    energize: bool
    conditions: list[str]  # tags that gate this write (series contacts / IF conditions / RHS)


@dataclass(slots=True)
class Statement:
    routine_id: str
    number: int  # rung number (RLL) or line number (ST)
    text: str
    reads: set[str] = field(default_factory=set)
    writes: list[Write] = field(default_factory=list)


_RLL_TOKEN = re.compile(r"\b(BST|NXB|BND)\b|([A-Z][A-Z0-9_]*)\(([^()]*)\)")
_CONDITIONS = {"XIC", "XIO", "EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ", "LIM", "CMP", "ONS"}
_ENERGIZE = {"OTE", "OTL"}
_DEENERGIZE = {"OTU"}
_NON_TAG_OPERANDS = {"JSR", "JMP", "LBL", "SBR", "RET"}
_OPERAND = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*")


def base_name(operand: str) -> str | None:
    """``Timer.DN`` -> ``Timer``; ``Arr[3].x`` -> ``Arr``; literals / ``?`` -> None."""
    match = _OPERAND.match(operand.strip())
    return match.group(0) if match else None


def analyze_rll(routine: Routine) -> list[Statement]:
    statements: list[Statement] = []
    for rung in routine.rungs:
        stmt = Statement(routine.id, rung.number, rung.logic)
        legs: list[list[str]] = [[]]
        for match in _RLL_TOKEN.finditer(rung.logic):
            keyword, instr, args = match.groups()
            if keyword == "BST":
                legs.append([])
                continue
            if keyword == "NXB":
                legs[-1] = []
                continue
            if keyword == "BND":
                if len(legs) > 1:
                    legs.pop()
                continue
            if instr in _NON_TAG_OPERANDS:
                continue
            operands = [n for n in (base_name(a) for a in args.split(",")) if n]
            stmt.reads.update(operands if instr not in _ENERGIZE | _DEENERGIZE else [])
            if instr in _CONDITIONS:
                legs[-1].extend(operands)
            elif instr in _ENERGIZE | _DEENERGIZE and operands:
                series = [tag for leg in legs for tag in leg]
                stmt.writes.append(Write(operands[0], instr in _ENERGIZE, series))
        statements.append(stmt)
    return statements


_ST_KEYWORDS = {
    "IF", "THEN", "ELSIF", "ELSE", "END_IF", "CASE", "OF", "END_CASE", "FOR", "TO", "BY", "DO",
    "END_FOR", "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT", "AND", "OR", "XOR", "NOT",
    "MOD", "TRUE", "FALSE", "RETURN", "EXIT",
}  # fmt: skip
_ST_TOKEN = re.compile(
    r"(?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[[^\]]*\])*)"
    r"|(?P<assign>:=)|(?P<semi>;)|(?P<lparen>\()|(?P<rparen>\))|(?P<other>\S)"
)
_ST_COMMENT = re.compile(r"\(\*.*?\*\)|//[^\n]*|'[^']*'", re.DOTALL)
_OPENERS = {"IF": "THEN", "WHILE": "DO", "FOR": "DO", "CASE": "OF"}
_CLOSERS = {"END_IF", "END_WHILE", "END_FOR", "END_CASE"}


def _st_tokens(routine: Routine) -> list[tuple[str, str, int]]:
    lines = [(r.number, r.logic) for r in routine.rungs]
    source = "\n".join(text for _, text in lines)
    source = _ST_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), source)
    tokens: list[tuple[str, str, int]] = []
    for idx, text in enumerate(source.split("\n")):
        number = lines[idx][0] if idx < len(lines) else idx
        for m in _ST_TOKEN.finditer(text):
            kind = m.lastgroup or "other"
            value = m.group(0)
            if kind == "ident" and value.upper() in _ST_KEYWORDS:
                kind, value = "kw", value.upper()
            tokens.append((kind, value, number))
    return tokens


def analyze_st(routine: Routine) -> list[Statement]:
    tokens = _st_tokens(routine)
    text_by_line = {r.number: r.logic for r in routine.rungs}
    statements: list[Statement] = []
    cond_stack: list[set[str]] = []
    i = 0

    def collect_until(stop: set[str], start: int) -> tuple[set[str], int]:
        names: set[str] = set()
        j = start
        while j < len(tokens) and tokens[j][1] not in stop:
            if tokens[j][0] == "ident" and (name := base_name(tokens[j][1])):
                names.add(name)
            j += 1
        return names, j

    while i < len(tokens):
        kind, value, line = tokens[i]
        if kind == "kw" and value in _OPENERS:
            names, i = collect_until({_OPENERS[value]}, i + 1)
            cond_stack.append(names)
        elif kind == "kw" and value == "ELSIF":
            names, i = collect_until({"THEN"}, i + 1)
            if cond_stack:
                cond_stack[-1] |= names
        elif kind == "kw" and value == "REPEAT":
            cond_stack.append(set())
        elif kind == "kw" and (value in _CLOSERS or value == "END_REPEAT"):
            if cond_stack:
                cond_stack.pop()
        elif kind == "ident" and i + 1 < len(tokens) and tokens[i + 1][0] == "assign":
            rhs_tokens: list[tuple[str, str, int]] = []
            j = i + 2
            while j < len(tokens) and tokens[j][0] != "semi" and tokens[j][1] not in _CLOSERS:
                rhs_tokens.append(tokens[j])
                j += 1
            rhs = {n for k, v, _ in rhs_tokens if k == "ident" and (n := base_name(v))}
            literal = [v.upper() for _, v, _ in rhs_tokens]
            target = base_name(value)
            stmt = Statement(routine.id, line, text_by_line.get(line, "").strip(), reads=set(rhs))
            if target:
                gates = sorted(set().union(*cond_stack, rhs)) if cond_stack else sorted(rhs)
                stmt.reads.update(gates)
                stmt.writes.append(Write(target, literal not in (["FALSE"], ["0"]), gates))
            statements.append(stmt)
            i = j
        elif kind == "ident" and i + 1 < len(tokens) and tokens[i + 1][0] == "lparen":
            depth, j = 0, i + 1
            reads: set[str] = set()
            while j < len(tokens):
                if tokens[j][0] == "lparen":
                    depth += 1
                elif tokens[j][0] == "rparen":
                    depth -= 1
                    if depth == 0:
                        break
                elif tokens[j][0] == "ident" and (n := base_name(tokens[j][1])):
                    reads.add(n)
                j += 1
            if n := base_name(value):
                reads.add(n)
            stmt = Statement(routine.id, line, text_by_line.get(line, "").strip(), reads=reads)
            statements.append(stmt)
            i = j
        i += 1
    return statements


def analyze_routine(routine: Routine) -> list[Statement]:
    if routine.language is RoutineLanguage.ST:
        return analyze_st(routine)
    return analyze_rll(routine)
