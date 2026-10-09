"""LangGraph DAG wiring the AI agents (1-4) to the deterministic engines (5-6).

  excel_parser -> tag_namer -> standards_retriever -> logic_drafter -> hmi_layouter* -> merge
      -> safety_auditor --pass--> vendor_compiler -> diff_engine -> END
                        --fail (retries < max)--> logic_drafter (with auditor feedback)
                        --fail (retries exhausted)--> END (failed)
  (* first pass only)

Agents 5 (safety auditor) and 6 (vendor compiler) are pure Python: no LLM calls.
Progress is reported through an async ``emit`` callback as :class:`SynthesisEvent` objects.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from app.ai.agents import agents
from app.ai.agents.context import TabularSource
from app.ai.agents.schemas import HMILayoutPlan, IOListExtraction, LogicDraft, TagNamingPlan
from app.ai.apply import MergeError, apply_changes
from app.ai.llm import LLMClient, LLMError
from app.ai.rag import StandardSnippet, StandardsRetriever
from app.core.config import settings
from app.schemas.uir import UIRProject
from app.services.auditor import AuditReport, audit
from app.services.compilers import CompileError, compile_rockwell_l5x
from app.services.diff_engine import DiffResult, diff_uir
from app.services.parsers import ParseError, parse_l5x

logger = structlog.get_logger(__name__)


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    EXCEL_PARSER = "excel_parser"
    TAG_NAMER = "tag_namer"
    STANDARDS_RETRIEVER = "standards_retriever"
    LOGIC_DRAFTER = "logic_drafter"
    HMI_LAYOUTER = "hmi_layouter"
    MERGE = "uir_merge"
    SAFETY_AUDITOR = "safety_auditor"
    VENDOR_COMPILER = "vendor_compiler"
    DIFF_ENGINE = "diff_engine"


class EventStatus(StrEnum):
    CONNECTED = "connected"
    STARTED = "started"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"


class SynthesisEvent(BaseModel):
    agent: AgentName
    status: EventStatus
    message: str
    attempt: int | None = None
    data: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


Emit = Callable[[SynthesisEvent], Awaitable[None]]


class SynthesisError(RuntimeError):
    pass


class SynthesisOutcome(BaseModel):
    status: Literal["completed", "failed"]
    uir: UIRProject | None = None
    diff: DiffResult | None = None
    audit: AuditReport | None = None
    retries: int = 0
    error: str | None = None


class SynthesisState(TypedDict, total=False):
    prompt: str
    base: UIRProject
    source: TabularSource | None
    signals: IOListExtraction
    plan: TagNamingPlan
    standards: list[StandardSnippet]
    draft: LogicDraft
    hmi: HMILayoutPlan | None
    candidate: UIRProject | None
    audit: AuditReport | None
    feedback: list[str]
    retries: int
    drafts: int
    diff: DiffResult
    compiled_bytes: int
    failed: bool


def build_graph(
    llm: LLMClient,
    retriever: StandardsRetriever,
    emit: Emit,
    *,
    max_retries: int = settings.LOGIC_DRAFTER_MAX_AUDIT_LOOPS,
) -> Any:
    async def say(
        agent: AgentName,
        status: EventStatus,
        message: str,
        *,
        attempt: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        await emit(
            SynthesisEvent(agent=agent, status=status, message=message, attempt=attempt, data=data)
        )

    async def guarded(agent: AgentName, coro: Awaitable[Any], attempt: int | None = None) -> Any:
        try:
            return await coro
        except LLMError as exc:
            await say(agent, EventStatus.FAILED, str(exc), attempt=attempt)
            raise SynthesisError(str(exc)) from exc

    async def excel_parser(state: SynthesisState) -> SynthesisState:
        source = state.get("source")
        what = f"request and {source.filename} ({len(source.rows)} rows)" if source else "request"
        await say(AgentName.EXCEL_PARSER, EventStatus.STARTED, f"Extracting signals from {what}...")
        signals = await guarded(
            AgentName.EXCEL_PARSER, agents.excel_parser(llm, state["prompt"], state["base"], source)
        )
        await say(
            AgentName.EXCEL_PARSER,
            EventStatus.COMPLETED,
            f"Extracted {len(signals.signals)} signal(s)",
            data={"signals": [s.description for s in signals.signals]},
        )
        return {"signals": signals}

    async def tag_namer(state: SynthesisState) -> SynthesisState:
        await say(AgentName.TAG_NAMER, EventStatus.STARTED, "Naming tags (IEC 61131-3)...")
        plan = await guarded(
            AgentName.TAG_NAMER, agents.tag_namer(llm, state["signals"], state["base"])
        )
        names = [t.name for t in plan.tags]
        await say(
            AgentName.TAG_NAMER,
            EventStatus.COMPLETED,
            f"Named {len(names)} tag(s): {', '.join(names)}" if names else "No new tags needed",
            data={"tags": names},
        )
        return {"plan": plan}

    async def standards_retriever(state: SynthesisState) -> SynthesisState:
        await say(
            AgentName.STANDARDS_RETRIEVER, EventStatus.STARTED, "Retrieving IEC 61131-3 guidance..."
        )
        query = " ".join([state["prompt"], *(s.description for s in state["signals"].signals)])
        standards = await retriever.retrieve(query, k=4)
        await say(
            AgentName.STANDARDS_RETRIEVER,
            EventStatus.COMPLETED,
            f"Retrieved {len(standards)} reference(s) via {retriever.backend}",
            data={"titles": [s.title for s in standards]},
        )
        return {"standards": standards}

    async def logic_drafter(state: SynthesisState) -> SynthesisState:
        attempt = state.get("drafts", 0) + 1
        feedback = state.get("feedback", [])
        msg = (
            "Drafting logic..."
            if not feedback
            else f"Redrafting logic to fix {len(feedback)} issue(s)..."
        )
        await say(AgentName.LOGIC_DRAFTER, EventStatus.STARTED, msg, attempt=attempt)
        draft = await guarded(
            AgentName.LOGIC_DRAFTER,
            agents.logic_drafter(
                llm,
                state["prompt"],
                state["base"],
                state["signals"],
                state["plan"],
                state["standards"],
                feedback,
            ),
            attempt,
        )
        rungs = sum(len(e.rungs) for e in draft.edits)
        await say(
            AgentName.LOGIC_DRAFTER,
            EventStatus.COMPLETED,
            f"Drafted {rungs} rung(s) in {len(draft.edits)} routine edit(s)",
            attempt=attempt,
            data={
                "rationale": draft.rationale,
                "edits": [
                    {
                        "action": e.action,
                        "routine": f"{e.program}.{e.routine_name}",
                        "rungs": [r.logic for r in e.rungs],
                    }
                    for e in draft.edits
                ],
            },
        )
        return {"draft": draft, "drafts": attempt}

    async def hmi_layouter(state: SynthesisState) -> SynthesisState:
        if not state["plan"].tags:
            return {"hmi": None}
        await say(AgentName.HMI_LAYOUTER, EventStatus.STARTED, "Laying out HMI widgets...")
        hmi = await guarded(
            AgentName.HMI_LAYOUTER,
            agents.hmi_layouter(llm, state["prompt"], state["base"], state["plan"]),
        )
        await say(
            AgentName.HMI_LAYOUTER,
            EventStatus.COMPLETED,
            f"Placed {len(hmi.widgets)} widget(s) on screen '{hmi.screen_name}'",
            data={"widgets": [w.tag_ref for w in hmi.widgets]},
        )
        return {"hmi": hmi}

    async def merge(state: SynthesisState) -> SynthesisState:
        try:
            candidate = apply_changes(
                state["base"], state["plan"], state["draft"], state.get("hmi")
            )
        except (MergeError, ValidationError) as exc:
            detail = str(exc).splitlines()
            reason = detail[-1] if isinstance(exc, ValidationError) and detail else str(exc)
            await say(
                AgentName.MERGE, EventStatus.FAILED, f"Draft does not fit the project: {reason}"
            )
            return {"candidate": None, "audit": None, "feedback": [f"[MERGE] {reason}"]}
        await say(AgentName.MERGE, EventStatus.COMPLETED, "Merged draft into candidate UIR")
        return {"candidate": candidate}

    async def safety_auditor(state: SynthesisState) -> SynthesisState:
        candidate = state.get("candidate")
        if candidate is None:
            return {}
        await say(
            AgentName.SAFETY_AUDITOR, EventStatus.STARTED, "Running safety rules R-001..R-003..."
        )
        report = audit(candidate, baseline=state["base"])
        if report.passed:
            note = (
                f" ({len(report.preexisting)} pre-existing issue(s) ignored)"
                if report.preexisting
                else ""
            )
            await say(
                AgentName.SAFETY_AUDITOR, EventStatus.COMPLETED, f"All safety rules passed{note}",
                data=report.model_dump(mode="json"),
            )  # fmt: skip
            return {"audit": report, "feedback": []}
        await say(
            AgentName.SAFETY_AUDITOR,
            EventStatus.FAILED,
            f"{len(report.violations)} violation(s): "
            + "; ".join(
                f"{v.rule_id} {v.subjects[0] if v.subjects else ''}".strip()
                for v in report.violations
            ),
            data=report.model_dump(mode="json"),
        )
        return {"audit": report, "feedback": report.feedback().splitlines()}

    def route_after_audit(state: SynthesisState) -> str:
        report = state.get("audit")
        if state.get("candidate") is not None and report is not None and report.passed:
            return "vendor_compiler"
        return "retry" if state.get("retries", 0) < max_retries else "give_up"

    async def retry(state: SynthesisState) -> SynthesisState:
        retries = state.get("retries", 0) + 1
        await say(
            AgentName.LOGIC_DRAFTER,
            EventStatus.RETRY,
            f"Sending auditor feedback to Logic Drafter (retry {retries}/{max_retries})",
            attempt=retries,
            data={"feedback": state.get("feedback", [])},
        )
        return {"retries": retries}

    async def give_up(state: SynthesisState) -> SynthesisState:
        await say(
            AgentName.ORCHESTRATOR,
            EventStatus.FAILED,
            f"Safety audit still failing after {max_retries} retries; changes were not applied",
            data={"feedback": state.get("feedback", [])},
        )
        return {"failed": True}

    async def vendor_compiler(state: SynthesisState) -> SynthesisState:
        candidate = state["candidate"]
        assert candidate is not None
        await say(
            AgentName.VENDOR_COMPILER, EventStatus.STARTED, "Compiling Rockwell L5X (Jinja2)..."
        )
        try:
            xml = compile_rockwell_l5x(candidate)
            parse_l5x(xml.encode())
        except (CompileError, ParseError) as exc:
            await say(AgentName.VENDOR_COMPILER, EventStatus.FAILED, f"Compilation failed: {exc}")
            raise SynthesisError(f"vendor compiler: {exc}") from exc
        size = len(xml.encode())
        await say(
            AgentName.VENDOR_COMPILER,
            EventStatus.COMPLETED,
            f"Compiled L5X ({size / 1024:.1f} KB), round-trip OK",
            data={"bytes": size},
        )  # fmt: skip
        return {"compiled_bytes": size}

    async def diff_engine(state: SynthesisState) -> SynthesisState:
        candidate = state["candidate"]
        assert candidate is not None
        result = diff_uir(state["base"], candidate)
        s = result.summary
        await say(
            AgentName.DIFF_ENGINE, EventStatus.COMPLETED,
            f"{s.added} added, {s.removed} removed, {s.modified} modified",
            data=s.model_dump(),
        )  # fmt: skip
        return {"diff": result}

    def after_draft(state: SynthesisState) -> str:
        return "merge" if "hmi" in state else "hmi_layouter"

    g: StateGraph[SynthesisState] = StateGraph(SynthesisState)
    for name, fn in [
        ("excel_parser", excel_parser),
        ("tag_namer", tag_namer),
        ("standards_retriever", standards_retriever),
        ("logic_drafter", logic_drafter),
        ("hmi_layouter", hmi_layouter),
        ("merge", merge),
        ("safety_auditor", safety_auditor),
        ("retry", retry),
        ("give_up", give_up),
        ("vendor_compiler", vendor_compiler),
        ("diff_engine", diff_engine),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "excel_parser")
    g.add_edge("excel_parser", "tag_namer")
    g.add_edge("tag_namer", "standards_retriever")
    g.add_edge("standards_retriever", "logic_drafter")
    g.add_conditional_edges("logic_drafter", after_draft, ["hmi_layouter", "merge"])
    g.add_edge("hmi_layouter", "merge")
    g.add_edge("merge", "safety_auditor")
    g.add_conditional_edges(
        "safety_auditor", route_after_audit, ["vendor_compiler", "retry", "give_up"]
    )
    g.add_edge("retry", "logic_drafter")
    g.add_edge("give_up", END)
    g.add_edge("vendor_compiler", "diff_engine")
    g.add_edge("diff_engine", END)
    return g.compile()


async def run_synthesis(
    prompt: str,
    base: UIRProject,
    *,
    emit: Emit,
    llm: LLMClient,
    retriever: StandardsRetriever,
    source: TabularSource | None = None,
    max_retries: int = settings.LOGIC_DRAFTER_MAX_AUDIT_LOOPS,
) -> SynthesisOutcome:
    graph = build_graph(llm, retriever, emit, max_retries=max_retries)
    try:
        state: SynthesisState = await graph.ainvoke(
            {"prompt": prompt, "base": base, "source": source, "retries": 0, "drafts": 0},
            {"recursion_limit": 25 + 5 * max_retries},
        )
    except SynthesisError as exc:
        return SynthesisOutcome(status="failed", error=str(exc))
    if state.get("failed"):
        return SynthesisOutcome(
            status="failed",
            audit=state.get("audit"),
            retries=state.get("retries", 0),
            error="Safety audit failed after maximum retries: "
            + "; ".join(state.get("feedback", [])),
        )
    return SynthesisOutcome(
        status="completed",
        uir=state["candidate"],
        diff=state["diff"],
        audit=state["audit"],
        retries=state.get("retries", 0),
    )
