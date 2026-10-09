"""Agent 5 (Safety Auditor): deterministic networkx rule engine. ZERO LLM calls.

Graph model (``networkx.DiGraph``):
  * ``tag:<id>``       - every UIR tag
  * ``stmt:<routine>#<n>`` - a rung (RLL) or assignment (ST)
  * ``widget:<id>`` / ``alarm:<id>`` - HMI objects
Edges: tag -> stmt (reads), stmt -> tag (writes, with ``energize`` + gating ``conditions``),
widget/alarm -> tag (binds).

Rules:
  R-001  Motor start outputs must have an E-Stop interlock condition.
  R-002  No duplicate memory addresses in the tag database.
  R-003  HMI widgets (and alarms) must bind to existing tags of a compatible data type.
"""

import re
from collections import defaultdict
from enum import StrEnum
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from app.schemas.uir import (
    Alarm,
    Routine,
    Screen,
    Tag,
    TagDataType,
    UIRProject,
    WidgetType,
)
from app.services.auditor.logic import analyze_routine

RULES: dict[str, str] = {
    "R-001": "Motor start outputs must have an E-Stop interlock condition",
    "R-002": "No duplicate memory addresses in the tag database",
    "R-003": "HMI widgets must bind to existing, valid tags",
}

_MOTOR_NAME = re.compile(r"motor|mtr|pump|fan|contactor|starter|vfd|^m_?\d", re.IGNORECASE)
_MOTOR_DESC = re.compile(r"\b(motor|pump|fan|contactor|starter)\b", re.IGNORECASE)
_NOT_AN_OUTPUT = re.compile(
    r"(fb|feedback|fault|flt|alarm|alm|status|ready|rdy|aux|running|speed|_ok$)", re.IGNORECASE
)
_ESTOP_NAME = re.compile(r"e_?-?stop|estop|emergency|es_ok|safety_ok", re.IGNORECASE)
_ESTOP_DESC = re.compile(r"e-?stop|emergency stop", re.IGNORECASE)
_WIDGET_TYPES: dict[WidgetType, set[TagDataType]] = {
    WidgetType.BUTTON: {TagDataType.BOOL},
    WidgetType.INDICATOR: {TagDataType.BOOL},
    WidgetType.NUMERIC: {TagDataType.INT, TagDataType.DINT, TagDataType.REAL},
}


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"


class Violation(BaseModel):
    rule_id: str
    severity: Severity
    message: str
    location: str
    subjects: list[str] = Field(default_factory=list)
    fingerprint: str


class AuditReport(BaseModel):
    passed: bool
    rules_checked: list[str]
    violations: list[Violation] = Field(default_factory=list)
    preexisting: list[Violation] = Field(default_factory=list)

    def feedback(self) -> str:
        return "\n".join(f"[{v.rule_id}] {v.location}: {v.message}" for v in self.violations)


def load_draft(data: UIRProject | dict[str, Any]) -> UIRProject:
    """Validate each entity but skip project-level integrity checks (R-003 must see bad refs)."""
    if isinstance(data, UIRProject):
        return data
    return UIRProject.model_construct(
        schema_version="1.0",
        name=data.get("name", ""),
        vendor=data.get("vendor"),
        source_filename=data.get("source_filename"),
        tags=[Tag.model_validate(t) for t in data.get("tags", [])],
        routines=[Routine.model_validate(r) for r in data.get("routines", [])],
        screens=[Screen.model_validate(s) for s in data.get("screens", [])],
        alarms=[Alarm.model_validate(a) for a in data.get("alarms", [])],
    )


def is_motor_output(tag: Tag) -> bool:
    if tag.data_type is not TagDataType.BOOL or _NOT_AN_OUTPUT.search(tag.name):
        return False
    if tag.address and ":I." in tag.address:
        return False
    return bool(_MOTOR_NAME.search(tag.name) or _MOTOR_DESC.search(tag.description or ""))


def is_estop(tag: Tag) -> bool:
    return bool(_ESTOP_NAME.search(tag.name) or _ESTOP_DESC.search(tag.description or ""))


class SafetyRuleEngine:
    def __init__(self, project: UIRProject) -> None:
        self.project = project
        self.tags_by_id = {t.id: t for t in project.tags}
        self.graph: nx.DiGraph = nx.DiGraph()
        self._build_graph()

    # --- graph ------------------------------------------------------------------------------

    def _resolve(self, name: str, program: str | None) -> str | None:
        for candidate in (f"{program}.{name}", f"ctrl.{name}"):
            if candidate in self.tags_by_id:
                return candidate
        return None

    def _build_graph(self) -> None:
        g = self.graph
        for tag in self.project.tags:
            g.add_node(f"tag:{tag.id}", kind="tag", tag=tag)
        for routine in self.project.routines:
            for stmt in analyze_routine(routine):
                node = f"stmt:{routine.id}#{stmt.number}"
                g.add_node(node, kind="stmt", routine=routine, statement=stmt)
                for name in stmt.reads:
                    if tag_id := self._resolve(name, routine.program):
                        g.add_edge(f"tag:{tag_id}", node, kind="reads")
                for write in stmt.writes:
                    if tag_id := self._resolve(write.tag, routine.program):
                        conditions = [
                            c for n in write.conditions if (c := self._resolve(n, routine.program))
                        ]
                        g.add_edge(
                            node,
                            f"tag:{tag_id}",
                            kind="writes",
                            energize=write.energize,
                            conditions=conditions,
                        )
        names = {t.name: t.id for t in self.project.tags}
        for screen in self.project.screens:
            for widget in screen.widgets:
                node = f"widget:{widget.id}"
                g.add_node(node, kind="widget", widget=widget, screen=screen)
                if widget.tag_ref in names:
                    g.add_edge(node, f"tag:{names[widget.tag_ref]}", kind="binds")
        for alarm in self.project.alarms:
            node = f"alarm:{alarm.id}"
            g.add_node(node, kind="alarm", alarm=alarm)
            if alarm.tag_ref in names:
                g.add_edge(node, f"tag:{names[alarm.tag_ref]}", kind="binds")

    def _estop_derived(self, tag_id: str, visiting: frozenset[str] = frozenset()) -> bool:
        """True if the tag is an E-stop, or every energizing write to it is E-stop gated."""
        tag = self.tags_by_id[tag_id]
        if is_estop(tag):
            return True
        if tag_id in visiting or tag.data_type is not TagDataType.BOOL:
            return False
        writers = [
            data
            for _, _, data in self.graph.in_edges(f"tag:{tag_id}", data=True)
            if data.get("kind") == "writes" and data["energize"]
        ]
        return bool(writers) and all(
            any(
                self._estop_derived(c, visiting | {tag_id})
                for c in data["conditions"]
                if c != tag_id
            )
            for data in writers
        )

    # --- rules ------------------------------------------------------------------------------

    def r001_motor_estop(self) -> list[Violation]:
        out: list[Violation] = []
        for stmt_node, tag_node, data in self.graph.edges(data=True):
            if data.get("kind") != "writes" or not data["energize"]:
                continue
            tag = self.graph.nodes[tag_node]["tag"]
            if not is_motor_output(tag):
                continue
            if any(self._estop_derived(c) for c in data["conditions"]):
                continue
            stmt = self.graph.nodes[stmt_node]["statement"]
            routine = self.graph.nodes[stmt_node]["routine"]
            unit = "line" if routine.language.value == "ST" else "rung"
            out.append(
                Violation(
                    rule_id="R-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Motor output {tag.name!r} is energized without an E-Stop interlock in "
                        f"series (statement: {stmt.text.strip()!r}). Gate it with an E-stop "
                        "healthy contact, e.g. XIC(EStop_OK) or IF EStop_OK AND ... THEN."
                    ),
                    location=f"routines[{routine.id}].rungs[{stmt.number}] ({unit})",
                    subjects=[tag.name],
                    fingerprint=f"R-001|{routine.id}|{tag.id}|{stmt.text.strip()}",
                )
            )
        return out

    def r002_duplicate_addresses(self) -> list[Violation]:
        by_address: dict[str, list[Tag]] = defaultdict(list)
        for tag in self.project.tags:
            if tag.address:
                by_address[tag.address.strip().upper()].append(tag)
        return [
            Violation(
                rule_id="R-002",
                severity=Severity.HIGH,
                message=(
                    f"Address {tags[0].address!r} is assigned to {len(tags)} tags: "
                    + ", ".join(t.id for t in tags)
                ),
                location=f"tags[address={tags[0].address}]",
                subjects=[t.name for t in tags],
                fingerprint=f"R-002|{address}|{','.join(sorted(t.id for t in tags))}",
            )
            for address, tags in by_address.items()
            if len(tags) > 1
        ]

    def r003_hmi_bindings(self) -> list[Violation]:
        out: list[Violation] = []
        for node, attrs in self.graph.nodes(data=True):
            if attrs["kind"] not in ("widget", "alarm"):
                continue
            obj = attrs.get("widget") or attrs["alarm"]
            label = f"{attrs['kind']} {obj.id!r}"
            location = (
                f"screens[{attrs['screen'].id}].widgets[{obj.id}]"
                if attrs["kind"] == "widget"
                else f"alarms[{obj.id}]"
            )
            targets = list(self.graph.successors(node))
            if not targets:
                message = f"{label} binds to unknown tag {obj.tag_ref!r}"
            elif attrs["kind"] == "widget" and (
                self.graph.nodes[targets[0]]["tag"].data_type not in _WIDGET_TYPES[obj.type]
            ):
                dt = self.graph.nodes[targets[0]]["tag"].data_type.value
                message = f"{label} ({obj.type.value}) cannot bind to {dt} tag {obj.tag_ref!r}"
            else:
                continue
            out.append(
                Violation(
                    rule_id="R-003",
                    severity=Severity.HIGH,
                    message=message,
                    location=location,
                    subjects=[obj.tag_ref],
                    fingerprint=f"R-003|{location}|{obj.tag_ref}",
                )
            )
        return out

    def run(self) -> list[Violation]:
        return [
            *self.r001_motor_estop(),
            *self.r002_duplicate_addresses(),
            *self.r003_hmi_bindings(),
        ]


def audit(
    project: UIRProject | dict[str, Any],
    *,
    baseline: UIRProject | dict[str, Any] | None = None,
) -> AuditReport:
    """Run R-001..R-003. Violations already present in ``baseline`` are reported as preexisting
    and do not fail the audit, so AI changes are only blocked for problems they introduce."""
    violations = SafetyRuleEngine(load_draft(project)).run()
    known = (
        {v.fingerprint for v in SafetyRuleEngine(load_draft(baseline)).run()} if baseline else set()
    )
    new = [v for v in violations if v.fingerprint not in known]
    old = [v for v in violations if v.fingerprint in known]
    return AuditReport(passed=not new, rules_checked=list(RULES), violations=new, preexisting=old)
