import copy
from pathlib import Path
from typing import Any

import pytest

from app.services.auditor import audit
from app.services.parsers import parse_l5x

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"


@pytest.fixture
def doc() -> dict[str, Any]:
    return parse_l5x(SAMPLE).project.model_dump(mode="json")


def _rules(report: Any) -> list[str]:
    return sorted(v.rule_id for v in report.violations)


def _add_rung(doc: dict[str, Any], logic: str) -> None:
    rungs = doc["routines"][0]["rungs"]
    rungs.append({"number": len(rungs), "logic": logic, "comment": None})


def _st_routine(doc: dict[str, Any], *lines: str) -> None:
    doc["routines"].append(
        {
            "id": "MainProgram.Pump_ST",
            "name": "Pump_ST",
            "program": "MainProgram",
            "type": "SUBROUTINE",
            "language": "ST",
            "rungs": [{"number": i, "logic": ln, "comment": None} for i, ln in enumerate(lines)],
        }
    )


def test_sample_project_passes_all_rules(doc: dict[str, Any]) -> None:
    report = audit(doc)
    assert report.passed and report.violations == []
    assert report.rules_checked == ["R-001", "R-002", "R-003"]


# --- R-001 -------------------------------------------------------------------------------------


def test_r001_motor_without_estop(doc: dict[str, Any]) -> None:
    _add_rung(doc, "XIC(Start_PB) OTE(Conveyor_Motor_Run)")
    report = audit(doc)
    assert not report.passed and _rules(report) == ["R-001"]
    assert report.violations[0].severity == "CRITICAL"
    assert report.violations[0].subjects == ["Conveyor_Motor_Run"]
    assert "rungs[4]" in report.violations[0].location


def test_r001_estop_in_parallel_branch_is_not_an_interlock(doc: dict[str, Any]) -> None:
    _add_rung(doc, "BST XIC(Start_PB) NXB XIC(EStop_OK) BND OTL(Conveyor_Motor_Run)")
    assert _rules(audit(doc)) == ["R-001"]


def test_r001_estop_derived_permissive_and_unlatch(doc: dict[str, Any]) -> None:
    # Run_Request is sealed in through XIC(EStop_OK) -> acts as an E-stop-derived permissive.
    _add_rung(doc, "XIC(Run_Request) OTE(Conveyor_Motor_Run)")
    _add_rung(doc, "XIC(Jam_Detected) OTU(Conveyor_Motor_Run)")
    _add_rung(doc, "XIO(EStop_OK) XIC(Start_PB) BST OTE(Horn) NXB OTL(Conveyor_Motor_Run) BND")
    assert audit(doc).passed


def test_r001_structured_text(doc: dict[str, Any]) -> None:
    doc["tags"].append(
        {
            "id": "MainProgram.P101_Run",
            "name": "P101_Run",
            "data_type": "BOOL",
            "scope": "PROGRAM",
            "program": "MainProgram",
            "description": "Transfer pump run command",
            "address": None,
            "initial_value": None,
        }
    )
    _st_routine(
        doc,
        "(* pump control *)",
        "IF Start_PB AND EStop_OK THEN",
        "    P101_Run := TRUE;",
        "ELSIF Stop_PB THEN",
        "    P101_Run := FALSE;",
        "END_IF;",
        "P101_Run := Start_PB; // unsafe direct drive",
    )
    report = audit(doc)
    assert _rules(report) == ["R-001"]
    assert "rungs[6]" in report.violations[0].location


# --- R-002 -------------------------------------------------------------------------------------


def test_r002_duplicate_addresses(doc: dict[str, Any]) -> None:
    doc["tags"][1]["address"] = "local:1:i.data.0"  # same as Start_PB, different case
    report = audit(doc)
    assert _rules(report) == ["R-002"]
    assert sorted(report.violations[0].subjects) == ["Start_PB", "Stop_PB"]


# --- R-003 -------------------------------------------------------------------------------------


def test_r003_unknown_tag_binding(doc: dict[str, Any]) -> None:
    doc["screens"][0]["widgets"][0]["tag_ref"] = "Ghost"
    doc["alarms"][0]["tag_ref"] = "Missing_Alarm_Tag"
    report = audit(doc)
    assert _rules(report) == ["R-003", "R-003"]
    assert {v.location for v in report.violations} == {
        "screens[scr_overview].widgets[w_start]",
        "alarms[alm_jam]",
    }


def test_r003_incompatible_widget_type(doc: dict[str, Any]) -> None:
    doc["screens"][0]["widgets"][3]["tag_ref"] = "Recipe_Name"  # NUMERIC -> STRING
    doc["screens"][0]["widgets"][2]["tag_ref"] = "Line_Speed"  # INDICATOR -> REAL
    report = audit(doc)
    assert _rules(report) == ["R-003", "R-003"]
    assert any("cannot bind to STRING" in v.message for v in report.violations)


# --- baseline ----------------------------------------------------------------------------------


def test_preexisting_violations_do_not_block(doc: dict[str, Any]) -> None:
    _add_rung(doc, "XIC(Start_PB) OTE(Conveyor_Motor_Run)")
    baseline = copy.deepcopy(doc)
    doc["tags"][0]["description"] = "unrelated edit"
    report = audit(doc, baseline=baseline)
    assert report.passed and report.violations == []
    assert [v.rule_id for v in report.preexisting] == ["R-001"]

    doc["screens"][0]["widgets"][0]["tag_ref"] = "Ghost"
    report = audit(doc, baseline=baseline)
    assert not report.passed and _rules(report) == ["R-003"]
