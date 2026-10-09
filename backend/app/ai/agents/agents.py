"""Agents 1-4. Each one calls the LLM through Instructor with a Pydantic response model."""

import json

from app.ai.agents import mock
from app.ai.agents.context import TabularSource, target_program, uir_summary
from app.ai.agents.schemas import HMILayoutPlan, IOListExtraction, LogicDraft, TagNamingPlan
from app.ai.llm import LLMClient
from app.ai.rag import StandardSnippet
from app.schemas.uir import UIRProject

_SHARED = (
    "You are part of zAutomation, an industrial automation copilot that edits a vendor-neutral "
    "PLC/HMI model (UIR). Reply ONLY with JSON matching the provided schema."
)


def _msgs(system: str, user: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": f"{_SHARED}\n\n{system}"},
        {"role": "user", "content": user},
    ]


async def excel_parser(
    llm: LLMClient, prompt: str, uir: UIRProject, source: TabularSource | None
) -> IOListExtraction:
    """Agent 1: turn the request and/or an uploaded IO list into structured signals."""
    system = (
        "Agent 1 (IO-list parser). Extract every NEW signal needed for the request. Use the IO "
        "list rows when given (first row is usually a header). Only set 'address' when the source "
        "gives one. Do not repeat signals that already exist in the project. If the project has no "
        "E-stop healthy input and motors are requested, include one (role 'estop_ok')."
    )
    user = f"Request:\n{prompt}\n\nProject:\n{uir_summary(uir)}"
    if source:
        user += f"\n\nIO list {source.filename}:\n{source.as_text()}"
    return await llm.structured(
        "excel_parser",
        IOListExtraction,
        _msgs(system, user),
        mock=lambda: mock.extract(prompt, uir, source),
    )


async def tag_namer(llm: LLMClient, signals: IOListExtraction, uir: UIRProject) -> TagNamingPlan:
    """Agent 2: IEC 61131-3 compliant, collision-free tag names for the extracted signals."""
    existing = [t.name for t in uir.tags]
    system = (
        "Agent 2 (tag namer). Give each signal exactly one tag. Names: IEC 61131-3 identifiers, "
        "max 40 chars, equipment prefix + function (e.g. P101_Start_PB, P101_Run, P101_Speed_SP), "
        "no consecutive/trailing underscores, never reuse an existing name. Physical IO is "
        f"CONTROLLER scope; internal values are PROGRAM scope in program "
        f"'{target_program(uir)}'."
    )
    user = (
        f"Signals (index order):\n{signals.model_dump_json(indent=1)}\n\n"
        f"Existing tag names: {json.dumps(existing)}"
    )
    return await llm.structured(
        "tag_namer",
        TagNamingPlan,
        _msgs(system, user),
        mock=lambda: mock.name_tags(signals, uir),
        context={"existing_names": existing, "signal_count": len(signals.signals)},
    )


async def logic_drafter(
    llm: LLMClient,
    prompt: str,
    uir: UIRProject,
    signals: IOListExtraction,
    plan: TagNamingPlan,
    standards: list[StandardSnippet],
    feedback: list[str],
) -> LogicDraft:
    """Agent 3: Rockwell RLL / ST routine edits implementing the request."""
    system = (
        "Agent 3 (logic drafter). Write Rockwell RLL rung text (XIC, XIO, OTE, OTL, OTU, TON, MOV, "
        "JSR, BST/NXB/BND) or Structured Text lines. Prefer one subroutine per equipment called "
        "from the program MainRoutine via JSR. Every motor/pump/fan output MUST be gated in series "
        "(never in a parallel branch) by the E-stop healthy contact. Only reference existing tags "
        "or tags from the naming plan. Actions: 'create' a new routine, 'append' rungs to an "
        "existing one, or 'replace' all rungs of an existing one."
    )
    knowledge = "\n".join(f"- [{s.source}] {s.title}: {s.text}" for s in standards)
    user = (
        f"Request:\n{prompt}\n\nProject:\n{uir_summary(uir)}\n\n"
        f"New tags:\n{plan.model_dump_json(indent=1)}\n\nStandards:\n{knowledge}"
    )
    if feedback:
        user += "\n\nThe safety auditor REJECTED the previous draft. Fix ALL of:\n" + "\n".join(
            f"- {f}" for f in feedback
        )
    tag_names = [t.name for t in uir.tags] + [t.name for t in plan.tags]
    return await llm.structured(
        "logic_drafter",
        LogicDraft,
        _msgs(system, user),
        mock=lambda: mock.draft_logic(signals, plan, uir, feedback),
        context={"tag_names": tag_names, "routine_ids": [r.id for r in uir.routines]},
    )


async def hmi_layouter(
    llm: LLMClient, prompt: str, uir: UIRProject, plan: TagNamingPlan
) -> HMILayoutPlan:
    """Agent 4: place HMI widgets for the new tags (ISA-101 style)."""
    screen = uir.screens[0] if uir.screens else None
    size = (screen.width, screen.height) if screen else (1280, 800)
    system = (
        "Agent 4 (HMI layouter). Add widgets for the new tags: BUTTON for push buttons, INDICATOR "
        "for BOOL status/commands, NUMERIC for INT/DINT/REAL. Group by equipment, do not overlap "
        f"existing or new widgets, stay inside {size[0]}x{size[1]}. Reuse an existing screen id "
        "when there is room, otherwise create a new snake_case screen id."
    )
    user = (
        f"Request:\n{prompt}\n\nProject:\n{uir_summary(uir)}\n\n"
        f"New tags:\n{plan.model_dump_json(indent=1)}"
    )
    tag_types = {t.name: t.data_type.value for t in uir.tags} | {
        t.name: t.data_type.value for t in plan.tags
    }
    return await llm.structured(
        "hmi_layouter",
        HMILayoutPlan,
        _msgs(system, user),
        mock=lambda: mock.layout_hmi(plan, uir),
        context={"tag_types": tag_types, "screen_size": size},
    )
