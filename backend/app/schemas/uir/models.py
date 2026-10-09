"""UIR in-memory contract. Mirrored 1:1 in frontend/src/types/uir.ts."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.uir.enums import (
    AlarmSeverity,
    RoutineLanguage,
    RoutineType,
    TagDataType,
    TagScope,
    WidgetType,
)

PLC_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"


class UIRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tag(UIRModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(pattern=PLC_IDENTIFIER, max_length=40)
    data_type: TagDataType
    scope: TagScope
    program: str | None = None
    description: str | None = None
    address: str | None = None
    initial_value: bool | int | float | str | None = None

    @model_validator(mode="after")
    def _check_program_scope(self) -> Self:
        if self.scope is TagScope.PROGRAM and not self.program:
            raise ValueError(f"tag {self.name!r}: program-scoped tags require 'program'")
        if self.scope is TagScope.CONTROLLER and self.program is not None:
            raise ValueError(f"tag {self.name!r}: controller-scoped tags must not set 'program'")
        return self


class Rung(UIRModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=0)
    logic: str
    comment: str | None = None


class Routine(UIRModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(pattern=PLC_IDENTIFIER)
    program: str
    type: RoutineType
    language: RoutineLanguage = RoutineLanguage.RLL
    # RLL: one entry per rung. ST: one entry per source line (number = line number).
    rungs: list[Rung] = Field(default_factory=list)


class Widget(UIRModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: WidgetType
    label: str
    tag_ref: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Screen(UIRModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str
    width: int = Field(default=1280, gt=0)
    height: int = Field(default=800, gt=0)
    widgets: list[Widget] = Field(default_factory=list)


class Alarm(UIRModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tag_ref: str
    message: str
    severity: AlarmSeverity


class UIRProject(UIRModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    name: str
    vendor: str | None = None
    source_filename: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    routines: list[Routine] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    alarms: list[Alarm] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_integrity(self) -> Self:
        seen: set[tuple[str | None, str]] = set()
        for tag in self.tags:
            key = (tag.program, tag.name)
            if key in seen:
                raise ValueError(
                    f"duplicate tag {tag.name!r} in scope {tag.program or 'CONTROLLER'}"
                )
            seen.add(key)
        if len({tag.id for tag in self.tags}) != len(self.tags):
            raise ValueError("tag ids must be unique")
        tag_names = {tag.name for tag in self.tags}
        refs = [w.tag_ref for s in self.screens for w in s.widgets] + [
            a.tag_ref for a in self.alarms
        ]
        unknown = sorted({ref for ref in refs if ref not in tag_names})
        if unknown:
            raise ValueError(f"unresolved tag references: {', '.join(unknown)}")
        return self
