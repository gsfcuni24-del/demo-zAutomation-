"""Deterministic stand-ins for LLM answers (LLM_MODE=mock / no API keys).

They are returned through LiteLLM's ``mock_response`` and then parsed and validated by Instructor
exactly like a live model answer. The first logic draft intentionally omits the E-stop interlock so
the auditor -> logic-drafter retry loop is exercised; the retry adds it once R-001 is reported.
"""

import re

from app.ai.agents.context import TabularSource, estop_tags, target_program
from app.ai.agents.schemas import (
    DraftRung,
    HMILayoutPlan,
    IOListExtraction,
    LogicDraft,
    NamedTag,
    RoutineEdit,
    SignalDirection,
    SignalSpec,
    TagNamingPlan,
    WidgetPlacement,
)
from app.schemas.uir import (
    RoutineLanguage,
    RoutineType,
    TagDataType,
    TagScope,
    UIRProject,
    WidgetType,
)
from app.schemas.uir.models import PLC_IDENTIFIER

_EQUIPMENT_ID = re.compile(r"\b([A-Z]{1,4})-?(\d{2,4})\b")
_KINDS = ("pump", "motor", "fan", "mixer", "agitator", "compressor", "conveyor", "blower")
_TYPES = {t.value: t for t in TagDataType}


def equipment(prompt: str) -> tuple[str, str]:
    """('P101', 'pump') from 'add pump P-101 ...'; defaults to ('Motor_1', 'motor')."""
    lowered = prompt.lower()
    kind = next((k for k in _KINDS if k in lowered), "motor")
    if match := _EQUIPMENT_ID.search(prompt):
        return f"{match.group(1)}{match.group(2)}", kind
    return f"{kind.capitalize()}_1", kind


def _rows_to_signals(source: TabularSource) -> list[SignalSpec]:
    if not source.rows:
        return []
    header = [h.lower() for h in source.rows[0]]

    def col(*names: str) -> int | None:
        return next((i for i, h in enumerate(header) if any(n in h for n in names)), None)

    i_name, i_type = col("tag", "name", "signal"), col("type")
    i_desc, i_addr = col("desc", "comment"), col("address", "addr", "io", "channel")
    if i_name is None:
        return []
    out: list[SignalSpec] = []
    for row in source.rows[1:]:

        def cell(i: int | None, row: list[str] = row) -> str:
            return row[i].strip() if i is not None and i < len(row) else ""

        name = cell(i_name)
        if not name:
            continue
        address = cell(i_addr) or None
        dtype = _TYPES.get(cell(i_type).upper(), TagDataType.BOOL)
        direction = (
            SignalDirection.OUTPUT
            if address and (":O" in address.upper() or address.upper().startswith("O"))
            else SignalDirection.INPUT
            if address
            else SignalDirection.INTERNAL
        )
        out.append(
            SignalSpec(
                role=name.lower(),
                name_hint=name,
                description=cell(i_desc) or name.replace("_", " "),
                data_type=dtype,
                direction=direction,
                address=address,
            )
        )
    return out


def extract(prompt: str, uir: UIRProject, source: TabularSource | None) -> IOListExtraction:
    signals = _rows_to_signals(source) if source else []
    if not signals or _EQUIPMENT_ID.search(prompt) or any(k in prompt.lower() for k in _KINDS):
        eq, kind = equipment(prompt)
        signals += [
            SignalSpec(equipment=eq, role="start_pb", description=f"{eq} {kind} start push button",
                       data_type=TagDataType.BOOL, direction=SignalDirection.INPUT),
            SignalSpec(equipment=eq, role="stop_pb", description=f"{eq} {kind} stop push button (NC)",  # noqa: E501
                       data_type=TagDataType.BOOL, direction=SignalDirection.INPUT),
            SignalSpec(equipment=eq, role="run_cmd", description=f"{eq} {kind} motor run command",
                       data_type=TagDataType.BOOL, direction=SignalDirection.OUTPUT),
        ]  # fmt: skip
        if "speed" in prompt.lower():
            signals.append(
                SignalSpec(equipment=eq, role="speed_sp", description=f"{eq} speed setpoint (%)",
                           data_type=TagDataType.REAL, direction=SignalDirection.INTERNAL,
                           initial_value=0.0)
            )  # fmt: skip
        if not estop_tags(uir, target_program(uir)):
            signals.append(
                SignalSpec(role="estop_ok", description="E-stop safety relay healthy",
                           data_type=TagDataType.BOOL, direction=SignalDirection.INPUT)
            )  # fmt: skip
    return IOListExtraction(signals=signals, notes="mock extraction")


_SUFFIX = {"start_pb": "Start_PB", "stop_pb": "Stop_PB", "run_cmd": "Run", "speed_sp": "Speed_SP"}


def _identifier(raw: str) -> str:
    name = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", raw)).strip("_")[:40] or "Tag"
    return name if re.match(PLC_IDENTIFIER, name) and not name[0].isdigit() else f"T_{name}"[:40]


def name_tags(signals: IOListExtraction, uir: UIRProject) -> TagNamingPlan:
    program = target_program(uir)
    taken = {t.name.lower() for t in uir.tags}
    tags: list[NamedTag] = []
    for i, s in enumerate(signals.signals):
        if s.role == "estop_ok":
            base = "EStop_OK"
        elif s.equipment and s.role in _SUFFIX:
            base = f"{s.equipment}_{_SUFFIX[s.role]}"
        else:
            base = _identifier(s.name_hint or s.role)
        name, n = base, 2
        while name.lower() in taken:
            name, n = f"{base[:37]}_{n}", n + 1
        taken.add(name.lower())
        internal = s.direction is SignalDirection.INTERNAL
        tags.append(
            NamedTag(
                signal_index=i,
                name=name,
                data_type=s.data_type,
                scope=TagScope.PROGRAM if internal else TagScope.CONTROLLER,
                program=program if internal else None,
                description=s.description,
                address=s.address,
                initial_value=s.initial_value,
            )
        )
    return TagNamingPlan(tags=tags)


def draft_logic(
    signals: IOListExtraction, plan: TagNamingPlan, uir: UIRProject, feedback: list[str]
) -> LogicDraft:
    program = target_program(uir)
    by_role = {signals.signals[t.signal_index].role: t.name for t in plan.tags}
    estop = by_role.get("estop_ok") or next((t.name for t in estop_tags(uir, program)), None)
    interlock = f" XIC({estop})" if estop and any("R-001" in f for f in feedback) else ""
    rungs: list[DraftRung] = []
    eq = next((s.equipment for s in signals.signals if s.equipment), None)
    if {"start_pb", "stop_pb", "run_cmd"} <= by_role.keys():
        start, stop, run = by_role["start_pb"], by_role["stop_pb"], by_role["run_cmd"]
        rungs.append(
            DraftRung(
                logic=f"BST XIC({start}) NXB XIC({run}) BND XIC({stop}){interlock} OTE({run})",
                comment=f"{eq} start/stop seal-in",
            )
        )
    inputs = [
        t.name
        for t in plan.tags
        if t.data_type is TagDataType.BOOL and t.address and t.name not in by_role.values()
    ]
    for t in plan.tags:
        role = signals.signals[t.signal_index].role
        if role in _SUFFIX or t.data_type is not TagDataType.BOOL:
            continue
        if signals.signals[t.signal_index].direction is SignalDirection.OUTPUT and inputs:
            rungs.append(
                DraftRung(logic=f"XIC({inputs[0]}){interlock} OTE({t.name})", comment=t.description)
            )
    if not rungs:
        first = next(t.name for t in plan.tags if t.data_type is TagDataType.BOOL)
        rungs.append(DraftRung(logic=f"XIC({first}) OTE({first})", comment="placeholder"))
    routine = f"{eq or 'IO'}_Control"
    edits = [RoutineEdit(action="create", routine_name=routine, program=program, rungs=rungs)]
    main = next(
        (r for r in uir.routines if r.program == program and r.type is RoutineType.MAIN), None
    )
    if main is None or main.language is RoutineLanguage.RLL:
        edits.append(
            RoutineEdit(
                action="append" if main else "create",
                routine_name=main.name if main else "MainRoutine",
                program=program,
                type=RoutineType.MAIN,
                rungs=[DraftRung(logic=f"JSR({routine},0)", comment=f"Call {routine}")],
            )
        )
    note = " Added E-stop interlock after auditor feedback." if interlock else ""
    return LogicDraft(edits=edits, rationale=f"Seal-in start/stop circuit for {eq}.{note}")


def layout_hmi(plan: TagNamingPlan, uir: UIRProject) -> HMILayoutPlan:
    screen = uir.screens[0] if uir.screens else None
    top = max((w.y + w.height for w in screen.widgets), default=0) + 20 if screen else 40
    if screen is None or top + 60 > screen.height:
        screen_id, screen_name, top = "scr_main", "Main", 40
    else:
        screen_id, screen_name = screen.id, screen.name
    widgets: list[WidgetPlacement] = []
    for t in plan.tags:
        if t.data_type is TagDataType.BOOL:
            wtype = WidgetType.BUTTON if t.name.endswith("_PB") else WidgetType.INDICATOR
        elif t.data_type in (TagDataType.INT, TagDataType.DINT, TagDataType.REAL):
            wtype = WidgetType.NUMERIC
        else:
            continue
        if t.name == "EStop_OK":
            continue
        x = 40 + len(widgets) * 170
        if x + 150 > 1280:
            break
        widgets.append(
            WidgetPlacement(type=wtype, label=t.name.replace("_", " "), tag_ref=t.name,
                            x=x, y=top, width=150, height=60)
        )  # fmt: skip
    return HMILayoutPlan(screen_id=screen_id, screen_name=screen_name, widgets=widgets)
