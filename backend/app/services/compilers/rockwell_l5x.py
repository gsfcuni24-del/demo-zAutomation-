"""Agent 6 (Vendor Compiler): render a validated UIRProject to Rockwell L5X with Jinja2.

Pure templating - no LLM calls. The output round-trips through ``parse_l5x``.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.schemas.uir import Routine, RoutineType, Tag, TagDataType, UIRProject

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "vendor"
_NON_IDENT = re.compile(r"[^A-Za-z0-9_]")


class CompileError(ValueError):
    pass


@dataclass
class _Program:
    name: str
    tags: list[Tag] = field(default_factory=list)
    routines: list[Routine] = field(default_factory=list)

    @property
    def main_routine(self) -> str | None:
        return next((r.name for r in self.routines if r.type is RoutineType.MAIN), None)


def _cdata(value: object) -> Markup:
    text = str(value).replace("]]>", "]]]]><![CDATA[>")
    return Markup(f"<![CDATA[{text}]]>")  # noqa: S704 - CDATA payload is split-escaped above


def _radix(data_type: TagDataType) -> str:
    return "Float" if data_type is TagDataType.REAL else "Decimal"


def _decorated_value(tag: Tag) -> str:
    value = tag.initial_value
    if tag.data_type is TagDataType.BOOL:
        return "1" if value is True or value in (1, "1") else "0"
    if tag.data_type is TagDataType.REAL:
        return repr(float(value))  # type: ignore[arg-type]
    return str(int(value))  # type: ignore[arg-type]


def _rung_text(logic: str) -> str:
    logic = logic.strip()
    return logic if logic.endswith(";") else f"{logic};"


def controller_identifier(name: str) -> str:
    ident = _NON_IDENT.sub("_", name.strip()) or "Controller"
    if not (ident[0].isalpha() or ident[0] == "_"):
        ident = f"_{ident}"
    return ident[:40]


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(
        cdata=_cdata, radix=_radix, decorated_value=_decorated_value, rung_text=_rung_text
    )
    return env


_ENV = _environment()


def compile_rockwell_l5x(project: UIRProject, *, export_date: datetime | None = None) -> str:
    """Render ``project`` as an L5X document string."""
    programs: dict[str, _Program] = {}
    for tag in project.tags:
        if tag.program:
            programs.setdefault(tag.program, _Program(tag.program)).tags.append(tag)
    for routine in project.routines:
        programs.setdefault(routine.program, _Program(routine.program)).routines.append(routine)
    for program in programs.values():
        mains = [r for r in program.routines if r.type is RoutineType.MAIN]
        if len(mains) > 1:
            raise CompileError(f"program {program.name!r} has {len(mains)} MAIN routines")

    stamp = (export_date or datetime.now(UTC)).strftime("%a %b %d %H:%M:%S %Y")
    return _ENV.get_template("rockwell/project.l5x.j2").render(
        project=project,
        controller_name=controller_identifier(project.name),
        controller_tags=[t for t in project.tags if not t.program],
        programs=list(programs.values()),
        export_date=stamp,
        software_revision="33.01",
        processor_type="1769-L33ER",
        major_rev=33,
        minor_rev=11,
    )
