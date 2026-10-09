"""UIR helpers: canonical hashing and the Phase 2 mock document generator."""

import hashlib
import json
from typing import Any

from app.schemas.uir import (
    Alarm,
    AlarmSeverity,
    Routine,
    RoutineType,
    Rung,
    Screen,
    Tag,
    TagDataType,
    TagScope,
    UIRProject,
    Widget,
    WidgetType,
)


def hash_uir(uir_json: dict[str, Any]) -> str:
    canonical = json.dumps(uir_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tag(
    name: str,
    data_type: TagDataType,
    program: str | None = None,
    description: str | None = None,
    address: str | None = None,
    initial_value: bool | int | float | str | None = None,
) -> Tag:
    scope = TagScope.PROGRAM if program else TagScope.CONTROLLER
    return Tag(
        id=f"{program or 'ctrl'}.{name}",
        name=name,
        data_type=data_type,
        scope=scope,
        program=program,
        description=description,
        address=address,
        initial_value=initial_value,
    )


def build_mock_uir(project_name: str, vendor: str | None, source_filename: str) -> UIRProject:
    """Stub UIR returned for every upload until real parsers land in Phase 3."""
    b, i, d, r, s = (
        TagDataType.BOOL,
        TagDataType.INT,
        TagDataType.DINT,
        TagDataType.REAL,
        TagDataType.STRING,
    )
    tags = [
        _tag("Start_PB", b, description="Line start push button", address="I:0/0"),
        _tag("Stop_PB", b, description="Line stop push button (NC)", address="I:0/1"),
        _tag("EStop_OK", b, description="E-stop circuit healthy", address="I:0/2"),
        _tag("Motor_Run", b, description="Main conveyor motor contactor", address="O:0/0"),
        _tag("Line_Speed", r, description="Conveyor speed setpoint (m/min)", initial_value=12.5),
        _tag("Batch_Count", d, description="Completed batches", initial_value=0),
        _tag("Recipe_Name", s, description="Active recipe", initial_value="DEFAULT"),
        _tag("Seq_Step", i, "MainProgram", "Sequencer step number", initial_value=0),
        _tag("Fault_Code", i, "MainProgram", "Active fault code", initial_value=0),
        _tag("Start_Delay_ms", d, "MainProgram", "Start warning horn delay", initial_value=3000),
        _tag("Jam_Detected", b, "Conveyor", "Photo-eye jam detection", address="I:1/4"),
        _tag("Belt_Load_Pct", r, "Conveyor", "Belt load from VFD", initial_value=0.0),
    ]
    routines = [
        Routine(
            id="MainProgram.MainRoutine",
            name="MainRoutine",
            program="MainProgram",
            type=RoutineType.MAIN,
            rungs=[
                Rung(
                    number=0,
                    logic=(
                        "XIC(Start_PB)XIC(Stop_PB)XIC(EStop_OK)"
                        "BST XIC(Motor_Run)NXB BND OTE(Motor_Run)"
                    ),
                    comment="Start/stop seal-in with E-stop permissive",
                ),
                Rung(number=1, logic="JSR(Conveyor_Logic)", comment="Call conveyor subroutine"),
            ],
        ),
        Routine(
            id="Conveyor.Conveyor_Logic",
            name="Conveyor_Logic",
            program="Conveyor",
            type=RoutineType.SUBROUTINE,
            rungs=[
                Rung(number=0, logic="XIC(Jam_Detected)OTU(Motor_Run)", comment="Stop on jam"),
            ],
        ),
    ]
    screens = [
        Screen(
            id="scr_overview",
            name="Overview",
            widgets=[
                Widget(
                    id="w_start",
                    type=WidgetType.BUTTON,
                    label="Start",
                    tag_ref="Start_PB",
                    x=40,
                    y=40,
                    width=120,
                    height=48,
                ),
                Widget(
                    id="w_stop",
                    type=WidgetType.BUTTON,
                    label="Stop",
                    tag_ref="Stop_PB",
                    x=180,
                    y=40,
                    width=120,
                    height=48,
                ),
                Widget(
                    id="w_run",
                    type=WidgetType.INDICATOR,
                    label="Motor Running",
                    tag_ref="Motor_Run",
                    x=40,
                    y=120,
                    width=48,
                    height=48,
                ),
                Widget(
                    id="w_speed",
                    type=WidgetType.NUMERIC,
                    label="Line Speed",
                    tag_ref="Line_Speed",
                    x=180,
                    y=120,
                    width=160,
                    height=48,
                ),
            ],
        )
    ]
    alarms = [
        Alarm(
            id="alm_jam",
            tag_ref="Jam_Detected",
            message="Conveyor jam",
            severity=AlarmSeverity.HIGH,
        ),
        Alarm(
            id="alm_estop",
            tag_ref="EStop_OK",
            message="E-stop pressed",
            severity=AlarmSeverity.CRITICAL,
        ),
    ]
    return UIRProject(
        name=project_name,
        vendor=vendor,
        source_filename=source_filename,
        tags=tags,
        routines=routines,
        screens=screens,
        alarms=alarms,
    )
