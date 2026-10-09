from pathlib import Path
from typing import Any

import pytest

from app.ai.agents import mock
from app.ai.agents.schemas import HMILayoutPlan, LogicDraft, TagNamingPlan
from app.ai.llm import LLMClient, LLMError
from app.ai.orchestrator import AgentName, EventStatus, SynthesisEvent, run_synthesis
from app.ai.rag.retriever import HashingEmbedder, StandardsRetriever
from app.schemas.uir import UIRProject
from app.services.auditor import audit
from app.services.parsers import parse_l5x

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"
PROMPT = "Add pump P-101 with start/stop buttons, run indicator and speed setpoint"


@pytest.fixture
def llm() -> LLMClient:
    return LLMClient(mock=True)


@pytest.fixture
def retriever() -> StandardsRetriever:
    return StandardsRetriever(None, HashingEmbedder(), "test")


def _base() -> UIRProject:
    return parse_l5x(SAMPLE).project


async def _run(
    llm: LLMClient, retriever: StandardsRetriever, base: UIRProject, **kw: Any
) -> tuple[Any, list[SynthesisEvent]]:
    events: list[SynthesisEvent] = []

    async def emit(e: SynthesisEvent) -> None:
        events.append(e)

    return await run_synthesis(PROMPT, base, emit=emit, llm=llm, retriever=retriever, **kw), events


async def test_instructor_validates_and_rejects(llm: LLMClient) -> None:
    ok = await llm.structured(
        "tag_namer", TagNamingPlan, [{"role": "user", "content": "x"}],
        mock=lambda: TagNamingPlan.model_validate({"tags": []}),
    )  # fmt: skip
    assert ok.tags == []
    bad = TagNamingPlan.model_construct(
        tags=[
            mock.name_tags(mock.extract(PROMPT, _base(), None), _base())
            .tags[0]
            .model_copy(update={"name": "Start_PB"})
        ]
    )
    with pytest.raises(LLMError):
        await llm.structured(
            "tag_namer", TagNamingPlan, [{"role": "user", "content": "x"}],
            mock=lambda: bad, context={"existing_names": ["Start_PB"], "signal_count": 5},
        )  # fmt: skip


def test_logic_draft_rejects_unknown_tags_and_bad_syntax() -> None:
    edit = {
        "action": "create",
        "routine_name": "R",
        "program": "MainProgram",
        "rungs": [{"logic": "XIC(Ghost) OTE(Horn)"}],
    }
    ctx = {"tag_names": ["Horn", "Start_PB"], "routine_ids": []}
    with pytest.raises(ValueError, match="unknown tag 'Ghost'"):
        LogicDraft.model_validate({"edits": [edit], "rationale": "x"}, context=ctx)
    edit["rungs"] = [{"logic": "BST XIC(Start_PB) OTE(Horn)"}]
    with pytest.raises(ValueError, match="BND"):
        LogicDraft.model_validate({"edits": [edit], "rationale": "x"}, context=ctx)


def test_hmi_plan_rejects_bad_binding() -> None:
    widget = {
        "type": "NUMERIC",
        "label": "x",
        "tag_ref": "Horn",
        "x": 0,
        "y": 0,
        "width": 10,
        "height": 10,
    }
    with pytest.raises(ValueError, match="cannot bind BOOL"):
        HMILayoutPlan.model_validate(
            {"screen_id": "s", "screen_name": "S", "widgets": [widget]},
            context={"tag_types": {"Horn": "BOOL"}},
        )


async def test_pipeline_retries_once_then_passes(
    llm: LLMClient, retriever: StandardsRetriever
) -> None:
    base = _base()
    outcome, events = await _run(llm, retriever, base)
    assert outcome.status == "completed" and outcome.retries == 1
    assert outcome.audit.passed and audit(outcome.uir, baseline=base).passed
    order = [(e.agent, e.status) for e in events]
    assert order[0] == (AgentName.EXCEL_PARSER, EventStatus.STARTED)
    assert (AgentName.SAFETY_AUDITOR, EventStatus.FAILED) in order
    assert (AgentName.LOGIC_DRAFTER, EventStatus.RETRY) in order
    assert order[-1] == (AgentName.DIFF_ENGINE, EventStatus.COMPLETED)
    names = {t.name for t in outcome.uir.tags}
    assert {"P101_Start_PB", "P101_Stop_PB", "P101_Run", "P101_Speed_SP"} <= names
    routine = next(r for r in outcome.uir.routines if r.name == "P101_Control")
    assert "XIC(EStop_OK)" in routine.rungs[0].logic
    main = next(r for r in outcome.uir.routines if r.id == "MainProgram.MainRoutine")
    assert main.rungs[-1].logic == "JSR(P101_Control,0)"
    assert outcome.diff.summary.added > 0 and outcome.diff.summary.removed == 0


async def test_empty_project_gets_estop_tag(llm: LLMClient, retriever: StandardsRetriever) -> None:
    outcome, _ = await _run(llm, retriever, UIRProject(name="Empty"))
    assert outcome.status == "completed"
    assert "EStop_OK" in {t.name for t in outcome.uir.tags}
    assert {r.name for r in outcome.uir.routines} == {"P101_Control", "MainRoutine"}


async def test_retry_exhaustion_fails_gracefully(
    llm: LLMClient, retriever: StandardsRetriever, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = mock.draft_logic
    monkeypatch.setattr(mock, "draft_logic", lambda s, p, u, f: original(s, p, u, []))
    outcome, events = await _run(llm, retriever, _base(), max_retries=3)
    assert outcome.status == "failed" and outcome.retries == 3
    assert "R-001" in outcome.error
    drafts = [
        e for e in events if e.agent is AgentName.LOGIC_DRAFTER and e.status is EventStatus.STARTED
    ]
    assert len(drafts) == 4
    assert events[-1].agent is AgentName.ORCHESTRATOR and events[-1].status is EventStatus.FAILED


async def test_retriever_ranks_estop_guidance(retriever: StandardsRetriever) -> None:
    hits = await retriever.retrieve("emergency stop interlock for motor run output", k=3)
    assert "safety-estop-07" in [h.id for h in hits]
    assert retriever.backend == "memory"


async def test_retriever_qdrant_integration() -> None:
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url="http://localhost:6333", timeout=2, check_compatibility=False)
    try:
        await client.get_collections()
    except Exception:
        pytest.skip("Qdrant not reachable")
    r = StandardsRetriever(client, HashingEmbedder(), "pytest_standards")
    hits = await r.retrieve("emergency stop interlock for motor run output", k=3)
    assert r.backend == "qdrant" and "safety-estop-07" in [h.id for h in hits]
    await client.delete_collection(r.collection)
