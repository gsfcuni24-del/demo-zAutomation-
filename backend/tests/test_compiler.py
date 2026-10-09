from pathlib import Path

from lxml import etree

from app.schemas.uir import Routine, RoutineType, Rung, UIRProject
from app.services.compilers import compile_rockwell_l5x
from app.services.parsers import parse_l5x

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"


def _without_export_date(xml: str) -> list[str]:
    return [line for line in xml.splitlines() if "ExportDate" not in line]


def test_round_trip_is_lossless() -> None:
    original = parse_l5x(SAMPLE).project
    xml = compile_rockwell_l5x(original)
    reparsed = parse_l5x(xml.encode(), source_filename=original.source_filename)
    assert reparsed.warnings == []
    assert reparsed.project == original
    # and a second pass is byte-stable apart from the export timestamp
    again = compile_rockwell_l5x(reparsed.project)
    assert _without_export_date(again) == _without_export_date(xml)


def test_output_is_well_formed_l5x() -> None:
    xml = compile_rockwell_l5x(parse_l5x(SAMPLE).project)
    root = etree.fromstring(xml.encode())
    assert root.tag == "RSLogix5000Content"
    assert root.find("Controller").get("Name") == "Packaging_Line_3"
    programs = root.findall("Controller/Programs/Program")
    assert [p.get("MainRoutineName") for p in programs] == ["MainRoutine", "Conveyor_Logic"]
    assert root.find(".//Routine[@Name='Speed_Calc']").get("Type") == "ST"
    rung = root.find(".//Routine[@Name='MainRoutine']/RLLContent/Rung[@Number='3']/Text")
    assert rung.text.strip().endswith("OTE(Conveyor_Motor_Run);")


def test_special_characters_are_escaped() -> None:
    project = parse_l5x(SAMPLE).project.model_copy(deep=True)
    project.tags[0].description = 'Start <PB> & "quoted" ]]> end'
    project.screens[0].widgets[0].label = 'A&B <"x">'
    project.routines.append(
        Routine(
            id="MainProgram.Extra",
            name="Extra",
            program="MainProgram",
            type=RoutineType.SUBROUTINE,
            rungs=[Rung(number=0, logic="XIC(Start_PB)OTE(Horn)", comment="a ]]> b")],
        )
    )
    project = UIRProject.model_validate(project.model_dump())
    reparsed = parse_l5x(compile_rockwell_l5x(project).encode()).project
    assert reparsed.tags[0].description == 'Start <PB> & "quoted" ]]> end'
    assert reparsed.screens[0].widgets[0].label == 'A&B <"x">'
    extra = next(r for r in reparsed.routines if r.id == "MainProgram.Extra")
    assert extra.rungs[0].comment == "a ]]> b"


def test_project_name_is_sanitised_to_controller_identifier() -> None:
    project = parse_l5x(SAMPLE).project.model_copy(update={"name": "3 Line / Packaging"})
    root = etree.fromstring(compile_rockwell_l5x(project).encode())
    assert root.find("Controller").get("Name") == "_3_Line___Packaging"
