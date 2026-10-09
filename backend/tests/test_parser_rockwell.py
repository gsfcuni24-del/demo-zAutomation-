from pathlib import Path

import pytest

from app.schemas.uir import RoutineLanguage, RoutineType, TagDataType, TagScope, UIRProject
from app.services.parsers import ParseError, UnsafeXMLError, parse_file, parse_l5x

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"


def test_sample_parses_into_valid_uir() -> None:
    result = parse_l5x(SAMPLE)
    project = result.project
    UIRProject.model_validate(project.model_dump(mode="json"))
    assert project.name == "Packaging_Line_3"
    assert project.vendor == "ROCKWELL"
    assert project.source_filename == "test_project.xml"
    assert len(project.tags) == 17
    assert result.warnings == [
        "tag MainProgram.Start_Timer: data type 'TIMER' not supported, skipped"
    ]


def test_tag_fields_scopes_and_values() -> None:
    tags = {t.id: t for t in parse_l5x(SAMPLE).project.tags}
    estop = tags["ctrl.EStop_OK"]
    assert estop.scope is TagScope.CONTROLLER and estop.program is None
    assert estop.address == "Local:1:I.Data.2"
    assert estop.description == "E-stop safety relay healthy"
    assert tags["ctrl.Line_Speed"].data_type is TagDataType.REAL
    assert tags["ctrl.Line_Speed"].initial_value == 12.5
    assert tags["ctrl.Recipe_Name"].initial_value == "DEFAULT"
    assert tags["MainProgram.Start_Delay_ms"].initial_value == 3000
    seq = tags["MainProgram.Seq_Step"]
    assert seq.scope is TagScope.PROGRAM and seq.program == "MainProgram"
    assert tags["Conveyor.Jam_Alarm"].initial_value is False


def test_routines_rungs_and_st_lines() -> None:
    routines = {r.id: r for r in parse_l5x(SAMPLE).project.routines}
    main = routines["MainProgram.MainRoutine"]
    assert main.type is RoutineType.MAIN and main.language is RoutineLanguage.RLL
    assert [r.number for r in main.rungs] == [0, 1, 2, 3]
    assert main.rungs[3].logic.endswith("OTE(Conveyor_Motor_Run)")
    assert main.rungs[0].comment == "Run request seal-in with stop and E-stop permissives"
    st = routines["Conveyor.Speed_Calc"]
    assert st.type is RoutineType.SUBROUTINE and st.language is RoutineLanguage.ST
    assert st.rungs[2].logic == "    Belt_Load_Pct := Line_Speed * 4.0;"


def test_hmi_bindings() -> None:
    project = parse_l5x(SAMPLE).project
    (screen,) = project.screens
    assert screen.name == "Overview"
    assert {w.tag_ref for w in screen.widgets} >= {"Start_PB", "Line_Speed", "EStop_OK"}
    assert {a.id: a.severity.value for a in project.alarms} == {
        "alm_jam": "HIGH",
        "alm_estop": "CRITICAL",
    }


def test_rejects_dtd_and_entities() -> None:
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<RSLogix5000Content><Controller Name='C'/></RSLogix5000Content>"
    )
    with pytest.raises(UnsafeXMLError):
        parse_l5x(evil)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"<Controller/>", "Not a Rockwell L5X"),
        (b"<RSLogix5000Content><Controller", "Malformed XML"),
        (b"<RSLogix5000Content/>", "no <Controller>"),
    ],
)
def test_invalid_documents(payload: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_l5x(payload)


def test_unresolved_hmi_reference_is_rejected() -> None:
    xml = SAMPLE.read_bytes().replace(b'Tag="Line_Speed"', b'Tag="Ghost_Tag"')
    with pytest.raises(ParseError, match="Ghost_Tag"):
        parse_l5x(xml)


def test_parse_file_dispatch(tmp_path: Path) -> None:
    l5x = tmp_path / "line.L5X"
    l5x.write_bytes(SAMPLE.read_bytes())
    assert parse_file(l5x).project.source_filename == "line.L5X"
    other = tmp_path / "tia.xml"
    other.write_bytes(b"<Document/>")
    with pytest.raises(ParseError, match="Unsupported XML"):
        parse_file(other)
    csv = tmp_path / "io.csv"
    csv.write_text("a,b")
    with pytest.raises(ParseError, match="AI assistant"):
        parse_file(csv)
