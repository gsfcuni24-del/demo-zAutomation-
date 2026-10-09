import copy
from pathlib import Path
from typing import Any

from app.services.diff_engine import ChangeType, diff_uir
from app.services.parsers import parse_l5x

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"


def _doc() -> dict[str, Any]:
    return parse_l5x(SAMPLE).project.model_dump(mode="json")


def test_identical_snapshots_have_no_changes() -> None:
    result = diff_uir(_doc(), _doc())
    assert result.changes == [] and result.summary.model_dump() == {
        "added": 0,
        "removed": 0,
        "modified": 0,
    }


def test_added_removed_modified_with_exact_paths() -> None:
    old = _doc()
    new = copy.deepcopy(old)
    new["tags"].insert(0, {**new["tags"][0], "id": "ctrl.Aux_PB", "name": "Aux_PB"})
    removed = new["tags"].pop(5)  # ctrl.Fault_Reset_PB (index 4 in old)
    new["tags"][3]["description"] = "E-stop relay OK"  # ctrl.EStop_OK (index 2 in old, 3 in new)
    new["routines"][0]["rungs"][3]["logic"] = "XIC(EStop_OK) OTE(Conveyor_Motor_Run)"

    result = diff_uir(old, new)
    by_type = {c.change_type: [] for c in result.changes}  # type: ignore[var-annotated]
    for c in result.changes:
        by_type[c.change_type].append(c)

    (added,) = by_type[ChangeType.ADDED]
    assert added.path == "$.tags[0]" and added.entity_id == "ctrl.Aux_PB"
    assert added.new_value["name"] == "Aux_PB" and added.old_value is None

    (gone,) = by_type[ChangeType.REMOVED]
    assert gone.path == "$.tags[4]" and gone.entity_id == removed["id"]
    assert gone.old_value == removed

    modified = {c.path: c for c in by_type[ChangeType.MODIFIED]}
    assert modified["$.tags[3].description"].old_value == "E-stop safety relay healthy"
    assert modified["$.tags[3].description"].field == "description"
    rung = modified["$.routines[0].rungs[3].logic"]
    assert rung.entity_id == "MainProgram.MainRoutine" and rung.field == "rungs.3.logic"
    assert result.summary.model_dump() == {"added": 1, "removed": 1, "modified": 2}


def test_null_to_value_is_modified_and_first_snapshot_is_all_added() -> None:
    old = _doc()
    new = copy.deepcopy(old)
    new["tags"][0]["initial_value"] = True
    (change,) = diff_uir(old, new).changes
    assert change.change_type is ChangeType.MODIFIED and change.path == "$.tags[0].initial_value"

    first = diff_uir(None, old)
    assert {c.change_type for c in first.changes} == {ChangeType.ADDED}
    assert first.summary.added == len(old["tags"]) + len(old["routines"]) + 1 + 2
