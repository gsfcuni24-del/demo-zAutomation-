"""Deterministically merge agent outputs into a candidate UIR document."""

from typing import Any

from app.ai.agents.schemas import HMILayoutPlan, LogicDraft, TagNamingPlan
from app.schemas.uir import Rung, Screen, Tag, UIRProject, Widget


class MergeError(ValueError):
    pass


def apply_changes(
    base: UIRProject, plan: TagNamingPlan, draft: LogicDraft, hmi: HMILayoutPlan | None
) -> UIRProject:
    """Return a new validated UIRProject. Raises MergeError / pydantic.ValidationError."""
    doc = base.model_copy(deep=True)
    for t in plan.tags:
        doc.tags.append(
            Tag(
                id=f"{t.program or 'ctrl'}.{t.name}",
                name=t.name,
                data_type=t.data_type,
                scope=t.scope,
                program=t.program,
                description=t.description,
                address=t.address,
                initial_value=t.initial_value,
            )
        )
    routines = {r.id: r for r in doc.routines}
    for edit in draft.edits:
        rid = f"{edit.program}.{edit.routine_name}"
        if edit.action == "create":
            if rid in routines:
                raise MergeError(f"routine {rid} already exists")
            routines[rid] = edit.as_routine()
            doc.routines.append(routines[rid])
            continue
        target = routines.get(rid)
        if target is None:
            raise MergeError(f"routine {rid} not found for {edit.action}")
        if target.language is not edit.language:
            raise MergeError(f"routine {rid} is {target.language.value}, not {edit.language.value}")
        start = (
            0 if edit.action == "replace" else max((r.number for r in target.rungs), default=-1) + 1
        )
        new = [
            Rung(number=start + i, logic=r.logic, comment=r.comment)
            for i, r in enumerate(edit.rungs)
        ]
        target.rungs = new if edit.action == "replace" else [*target.rungs, *new]
    if hmi and hmi.widgets:
        screen = next((s for s in doc.screens if s.id == hmi.screen_id), None)
        if screen is None:
            screen = Screen(id=hmi.screen_id, name=hmi.screen_name)
            doc.screens.append(screen)
        used = {w.id for s in doc.screens for w in s.widgets}
        for w in hmi.widgets:
            wid, n = f"w_{w.tag_ref.lower()}", 2
            while wid in used:
                wid, n = f"w_{w.tag_ref.lower()}_{n}", n + 1
            used.add(wid)
            screen.widgets.append(Widget(id=wid, **w.model_dump()))
    payload: dict[str, Any] = doc.model_dump(mode="json")
    return UIRProject.model_validate(payload)
