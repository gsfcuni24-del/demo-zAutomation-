"""Pydantic response models for the four AI agents (enforced through Instructor).

Validators use the Instructor ``context`` (existing tags/routines) so a model answer that
references unknown tags, collides with existing names or violates syntax is rejected and re-asked.
"""

import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from app.schemas.uir import (
    Routine,
    RoutineLanguage,
    RoutineType,
    Rung,
    TagDataType,
    TagScope,
    WidgetType,
)
from app.schemas.uir.models import PLC_IDENTIFIER
from app.services.auditor.logic import analyze_routine

Scalar = bool | int | float | str | None


def _ctx(info: ValidationInfo) -> dict[str, Any]:
    return info.context if isinstance(info.context, dict) else {}


# --- Agent 1: Excel / IO-list parser ---------------------------------------------------------


class SignalDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    INTERNAL = "INTERNAL"


class SignalSpec(BaseModel):
    """One signal the user asked for or that appears in an uploaded IO list."""

    equipment: str | None = Field(None, description="Equipment identifier, e.g. 'P101'")
    role: str = Field(min_length=1, description="Signal function, e.g. 'start_pb', 'run_cmd'")
    name_hint: str | None = Field(None, description="Tag name given in the source, if any")
    description: str = Field(min_length=1)
    data_type: TagDataType
    direction: SignalDirection
    address: str | None = Field(None, description="Physical IO address only if explicitly given")
    initial_value: Scalar = None


class IOListExtraction(BaseModel):
    signals: list[SignalSpec] = Field(default_factory=list, max_length=200)
    notes: str | None = None


# --- Agent 2: Tag namer ----------------------------------------------------------------------


class NamedTag(BaseModel):
    signal_index: int = Field(ge=0, description="Index into the extracted signals list")
    name: str = Field(pattern=PLC_IDENTIFIER, max_length=40)
    data_type: TagDataType
    scope: TagScope
    program: str | None = None
    description: str
    address: str | None = None
    initial_value: Scalar = None

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.scope is TagScope.PROGRAM and not self.program:
            raise ValueError(f"{self.name}: PROGRAM-scoped tags need 'program'")
        if self.scope is TagScope.CONTROLLER and self.program:
            raise ValueError(f"{self.name}: CONTROLLER-scoped tags must not set 'program'")
        if "__" in self.name or self.name.endswith("_"):
            raise ValueError(f"{self.name}: no consecutive or trailing underscores (IEC 61131-3)")
        return self


class TagNamingPlan(BaseModel):
    tags: list[NamedTag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self, info: ValidationInfo) -> Self:
        ctx = _ctx(info)
        existing = {n.lower() for n in ctx.get("existing_names", [])}
        signal_count = ctx.get("signal_count")
        seen: set[str] = set()
        for tag in self.tags:
            key = tag.name.lower()
            if key in existing:
                raise ValueError(f"tag name {tag.name!r} already exists in the project")
            if key in seen:
                raise ValueError(f"tag name {tag.name!r} is used twice in this plan")
            if signal_count is not None and tag.signal_index >= signal_count:
                raise ValueError(f"{tag.name}: signal_index {tag.signal_index} out of range")
            seen.add(key)
        return self


# --- Agent 3: Logic drafter ------------------------------------------------------------------

_ST_BUILTINS = {
    "ABS", "SQRT", "MIN", "MAX", "LIMIT", "SEL", "MUX", "TRUNC", "SIN", "COS", "TAN", "LN", "LOG",
    "EXP", "TON", "TOF", "RTO", "CTU", "CTD", "R_TRIG", "F_TRIG", "JSR",
}  # fmt: skip


class DraftRung(BaseModel):
    logic: str = Field(min_length=1, description="RLL rung text or one ST source line")
    comment: str | None = None


class RoutineEdit(BaseModel):
    action: Literal["create", "append", "replace"]
    routine_name: str = Field(pattern=PLC_IDENTIFIER)
    program: str = Field(pattern=PLC_IDENTIFIER)
    type: RoutineType = RoutineType.SUBROUTINE
    language: RoutineLanguage = RoutineLanguage.RLL
    rungs: list[DraftRung] = Field(min_length=1)

    @model_validator(mode="after")
    def _syntax(self) -> Self:
        if self.language is RoutineLanguage.RLL:
            for i, rung in enumerate(self.rungs):
                text = rung.logic
                if text.count("(") != text.count(")"):
                    raise ValueError(f"{self.routine_name} rung {i}: unbalanced parentheses")
                opened = len(re.findall(r"\bBST\b", text))
                if opened != len(re.findall(r"\bBND\b", text)):
                    raise ValueError(f"{self.routine_name} rung {i}: every BST needs a BND")
                if not re.search(r"[A-Z]{2,}\(", text):
                    raise ValueError(f"{self.routine_name} rung {i}: no RLL instruction found")
        return self

    def as_routine(self) -> Routine:
        return Routine(
            id=f"{self.program}.{self.routine_name}",
            name=self.routine_name,
            program=self.program,
            type=self.type,
            language=self.language,
            rungs=[
                Rung(number=i, logic=r.logic, comment=r.comment) for i, r in enumerate(self.rungs)
            ],
        )


class LogicDraft(BaseModel):
    edits: list[RoutineEdit] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> Self:
        ctx = _ctx(info)
        tag_names = {n.lower() for n in ctx.get("tag_names", [])}
        routines = {r.lower() for r in ctx.get("routine_ids", [])}
        if not tag_names:
            return self
        created = {
            f"{e.program}.{e.routine_name}".lower() for e in self.edits if e.action == "create"
        }
        for edit in self.edits:
            rid = f"{edit.program}.{edit.routine_name}".lower()
            if edit.action == "create" and rid in routines:
                raise ValueError(f"routine {rid} already exists; use 'append' or 'replace'")
            if edit.action != "create" and rid not in routines:
                raise ValueError(f"routine {rid} does not exist; use 'create'")
            for stmt in analyze_routine(edit.as_routine()):
                names = stmt.reads | {w.tag for w in stmt.writes}
                for name in names:
                    if name.upper() in _ST_BUILTINS:
                        continue
                    if name.lower() not in tag_names:
                        raise ValueError(
                            f"{edit.routine_name}: unknown tag {name!r}; only use existing tags or "
                            "tags from the naming plan"
                        )
            for jsr in re.findall(r"JSR\((\w+)", " ".join(r.logic for r in edit.rungs)):
                target = f"{edit.program}.{jsr}".lower()
                if target not in routines and target not in created:
                    raise ValueError(f"JSR target {jsr!r} does not exist in {edit.program}")
        return self


# --- Agent 4: HMI layouter -------------------------------------------------------------------

_WIDGET_TYPES = {
    WidgetType.BUTTON: {TagDataType.BOOL},
    WidgetType.INDICATOR: {TagDataType.BOOL},
    WidgetType.NUMERIC: {TagDataType.INT, TagDataType.DINT, TagDataType.REAL},
}


class WidgetPlacement(BaseModel):
    type: WidgetType
    label: str = Field(min_length=1, max_length=40)
    tag_ref: str = Field(pattern=PLC_IDENTIFIER)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0, le=1280)
    height: int = Field(gt=0, le=800)


class HMILayoutPlan(BaseModel):
    screen_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    screen_name: str = Field(min_length=1)
    widgets: list[WidgetPlacement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bindings(self, info: ValidationInfo) -> Self:
        ctx = _ctx(info)
        types: dict[str, str] = ctx.get("tag_types", {})
        width, height = ctx.get("screen_size", (1280, 800))
        for i, w in enumerate(self.widgets):
            if types and w.tag_ref not in types:
                raise ValueError(f"widget {w.label!r}: unknown tag {w.tag_ref!r}")
            if types and TagDataType(types[w.tag_ref]) not in _WIDGET_TYPES[w.type]:
                raise ValueError(
                    f"widget {w.label!r}: {w.type.value} cannot bind {types[w.tag_ref]} tag"
                )
            if w.x + w.width > width or w.y + w.height > height:
                raise ValueError(f"widget {w.label!r} is outside the {width}x{height} screen")
            for other in self.widgets[i + 1 :]:
                if (
                    w.x < other.x + other.width
                    and other.x < w.x + w.width
                    and w.y < other.y + other.height
                    and other.y < w.y + w.height
                ):
                    raise ValueError(f"widgets {w.label!r} and {other.label!r} overlap")
        return self
