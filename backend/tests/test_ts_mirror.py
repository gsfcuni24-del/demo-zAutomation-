"""Guards that frontend/src/types/*.ts mirror the backend Pydantic contracts exactly."""

import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.models import FileParseStatus, ProjectStatus
from app.schemas import project as api
from app.schemas import uir
from app.services import auditor
from app.services import diff_engine as diff

TYPES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types"

pytestmark = pytest.mark.skipif(
    not TYPES_DIR.is_dir(), reason="frontend sources not available (e.g. inside the api container)"
)

UIR_MODELS: list[type[BaseModel]] = [
    uir.Tag,
    uir.Rung,
    uir.Routine,
    uir.Widget,
    uir.Screen,
    uir.Alarm,
    uir.UIRProject,
]
UIR_ENUMS: dict[str, type[StrEnum]] = {
    "TAG_DATA_TYPES": uir.TagDataType,
    "TAG_SCOPES": uir.TagScope,
    "ROUTINE_TYPES": uir.RoutineType,
    "ROUTINE_LANGUAGES": uir.RoutineLanguage,
    "WIDGET_TYPES": uir.WidgetType,
    "ALARM_SEVERITIES": uir.AlarmSeverity,
}
API_MODELS: list[type[BaseModel]] = [
    api.ProjectCreate,
    api.ProjectRead,
    api.FileRead,
    api.UIRSnapshotSummary,
    api.UIRSnapshotRead,
    api.FileUploadResponse,
    api.UIRDiffResponse,
    diff.DiffEntry,
    diff.DiffSummary,
    auditor.AuditReport,
    auditor.Violation,
]
API_ENUMS: dict[str, type[StrEnum]] = {
    "PROJECT_STATUSES": ProjectStatus,
    "FILE_PARSE_STATUSES": FileParseStatus,
    "CHANGE_TYPES": diff.ChangeType,
    "VIOLATION_SEVERITIES": auditor.Severity,
}

_INTERFACE = re.compile(
    r"export interface (\w+)(?: extends (\w+))? \{(.*?)^\}", re.DOTALL | re.MULTILINE
)
_FIELD = re.compile(r"^\s*(\w+)\??:", re.MULTILINE)
_CONST = re.compile(r"export const (\w+) = \[(.*?)\] as const;", re.DOTALL)


def _interfaces(source: str) -> dict[str, set[str]]:
    raw = {m[1]: (m[2], set(_FIELD.findall(m[3]))) for m in _INTERFACE.finditer(source)}

    def resolve(name: str) -> set[str]:
        parent, fields = raw[name]
        return fields | (resolve(parent) if parent else set())

    return {name: resolve(name) for name in raw}


def _consts(source: str) -> dict[str, list[str]]:
    return {m[1]: re.findall(r'"([^"]+)"', m[2]) for m in _CONST.finditer(source)}


@pytest.mark.parametrize(
    ("ts_file", "models", "enums"),
    [("uir.ts", UIR_MODELS, UIR_ENUMS), ("api.ts", API_MODELS, API_ENUMS)],
)
def test_typescript_mirrors_pydantic(
    ts_file: str, models: list[type[BaseModel]], enums: dict[str, type[StrEnum]]
) -> None:
    source = (TYPES_DIR / ts_file).read_text()
    interfaces = _interfaces(source)
    for model in models:
        assert model.__name__ in interfaces, f"{ts_file} is missing interface {model.__name__}"
        assert interfaces[model.__name__] == set(model.model_fields), model.__name__
    consts = _consts(source)
    for const_name, enum in enums.items():
        assert consts.get(const_name) == [member.value for member in enum], const_name
