"""Streaming Rockwell Studio 5000 ``.L5X`` parser -> UIR.

Parses controller/program tags, RLL and ST routines and the zAutomation HMI extension block
(``<HMIDisplays>`` / ``<HMIAlarms>`` under ``<Controller>``; plain L5X carries no HMI data).

The document is consumed with ``lxml.etree.iterparse`` and each processed subtree is cleared
immediately, so memory stays bounded by the largest single tag/routine rather than the file.
DTDs and entities are refused (``defusedxml`` policy) before any content is read.
"""

import re
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import IO, Any

import defusedxml
from lxml import etree
from pydantic import ValidationError

from app.schemas.uir import (
    Alarm,
    AlarmSeverity,
    Routine,
    RoutineLanguage,
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
from app.services.parsers.base import ParseError, ParseResult, UnsafeXMLError

ROOT_ELEMENT = "RSLogix5000Content"
VENDOR = "ROCKWELL"
_BIT_ALIAS = re.compile(r"\.\d+$")
_SUPPORTED_TYPES = {t.value for t in TagDataType}

Source = str | Path | bytes | IO[bytes]


def _text(element: etree._Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _int_attr(element: etree._Element, name: str, default: int | None = None) -> int:
    raw = element.get(name)
    if raw is None:
        if default is None:
            raise ParseError(f"<{element.tag}> is missing required attribute {name!r}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ParseError(f"<{element.tag}> attribute {name}={raw!r} is not an integer") from exc


def _coerce_value(data_type: TagDataType, raw: str) -> bool | int | float | str:
    if data_type is TagDataType.BOOL:
        return raw.strip() not in {"0", "false", "False", ""}
    if data_type in (TagDataType.INT, TagDataType.DINT):
        return int(raw)
    if data_type is TagDataType.REAL:
        return float(raw)
    return raw


def _initial_value(
    tag_el: etree._Element, data_type: TagDataType
) -> bool | int | float | str | None:
    for data in tag_el.iterchildren("Data"):
        fmt = data.get("Format")
        if fmt == "Decorated":
            value_el = data.find("DataValue")
            if value_el is not None and value_el.get("Value") is not None:
                return _coerce_value(data_type, value_el.get("Value", ""))
        elif fmt == "String":
            raw = _text(data)
            if raw is not None:
                if len(raw) >= 2 and raw[0] == raw[-1] == "'":
                    raw = raw[1:-1]
                return raw
    return None


class _L5XStreamParser:
    def __init__(self, source_filename: str | None) -> None:
        self.source_filename = source_filename
        self.warnings: list[str] = []
        self.controller_name: str | None = None
        self.program: str | None = None
        self.main_routine: str | None = None
        self.tags: list[Tag] = []
        self.routines: list[Routine] = []
        self.screens: list[Screen] = []
        self.alarms: list[Alarm] = []

    # --- element handlers -------------------------------------------------------------------

    def tag(self, el: etree._Element) -> None:
        name = el.get("Name", "")
        where = f"{self.program}.{name}" if self.program else name
        if el.get("Dimensions"):
            self.warnings.append(f"tag {where}: arrays are not supported yet, skipped")
            return
        raw_type = el.get("DataType")
        alias_for = el.get("AliasFor")
        if raw_type is None and alias_for and _BIT_ALIAS.search(alias_for):
            raw_type = "BOOL"
        if raw_type not in _SUPPORTED_TYPES:
            self.warnings.append(f"tag {where}: data type {raw_type!r} not supported, skipped")
            return
        data_type = TagDataType(raw_type)
        try:
            self.tags.append(
                Tag(
                    id=f"{self.program or 'ctrl'}.{name}",
                    name=name,
                    data_type=data_type,
                    scope=TagScope.PROGRAM if self.program else TagScope.CONTROLLER,
                    program=self.program,
                    description=_text(el.find("Description")),
                    address=alias_for,
                    initial_value=None if alias_for else _initial_value(el, data_type),
                )
            )
        except (ValidationError, ValueError) as exc:
            self.warnings.append(f"tag {where}: invalid ({_first_error(exc)}), skipped")

    def routine(self, el: etree._Element) -> None:
        name = el.get("Name", "")
        program = self.program or ""
        kind = el.get("Type")
        rungs: list[Rung] = []
        if kind == "RLL":
            for rung in el.iterfind("RLLContent/Rung"):
                logic = (_text(rung.find("Text")) or "").rstrip()
                rungs.append(
                    Rung(
                        number=_int_attr(rung, "Number"),
                        logic=logic[:-1].rstrip() if logic.endswith(";") else logic,
                        comment=_text(rung.find("Comment")),
                    )
                )
        elif kind == "ST":
            for line in el.iterfind("STContent/Line"):
                text = (line.text or "").strip("\r\n")
                rungs.append(Rung(number=_int_attr(line, "Number"), logic=text.rstrip()))
        else:
            self.warnings.append(f"routine {program}.{name}: type {kind!r} not supported, skipped")
            return
        try:
            self.routines.append(
                Routine(
                    id=f"{program}.{name}",
                    name=name,
                    program=program,
                    type=RoutineType.MAIN if name == self.main_routine else RoutineType.SUBROUTINE,
                    language=RoutineLanguage(kind),
                    rungs=rungs,
                )
            )
        except ValidationError as exc:
            self.warnings.append(
                f"routine {program}.{name}: invalid ({_first_error(exc)}), skipped"
            )

    def display(self, el: etree._Element) -> None:
        widgets: list[Widget] = []
        for obj in el.iterfind("Object"):
            try:
                widgets.append(
                    Widget(
                        id=obj.get("ID", ""),
                        type=WidgetType(obj.get("Type", "").upper()),
                        label=obj.get("Label", ""),
                        tag_ref=obj.get("Tag", ""),
                        x=_int_attr(obj, "X"),
                        y=_int_attr(obj, "Y"),
                        width=_int_attr(obj, "Width"),
                        height=_int_attr(obj, "Height"),
                    )
                )
            except (ValidationError, ValueError) as exc:
                self.warnings.append(f"HMI object {obj.get('ID')!r}: invalid ({_first_error(exc)})")
        try:
            self.screens.append(
                Screen(
                    id=el.get("ID") or el.get("Name", ""),
                    name=el.get("Name", ""),
                    width=_int_attr(el, "Width", 1280),
                    height=_int_attr(el, "Height", 800),
                    widgets=widgets,
                )
            )
        except ValidationError as exc:
            self.warnings.append(f"HMI display {el.get('Name')!r}: invalid ({_first_error(exc)})")

    def alarm(self, el: etree._Element) -> None:
        try:
            self.alarms.append(
                Alarm(
                    id=el.get("ID", ""),
                    tag_ref=el.get("Tag", ""),
                    message=_text(el.find("Message")) or "",
                    severity=AlarmSeverity(el.get("Severity", "MEDIUM").upper()),
                )
            )
        except (ValidationError, ValueError) as exc:
            self.warnings.append(f"HMI alarm {el.get('ID')!r}: invalid ({_first_error(exc)})")

    # --- driver -----------------------------------------------------------------------------

    def run(self, stream: IO[bytes]) -> ParseResult:
        stack: list[str] = []
        try:
            for event, el in self._events(stream):
                if event == "start":
                    if not stack:
                        self._check_root(el)
                    stack.append(el.tag)
                    if el.tag == "Controller" and len(stack) == 2:
                        self.controller_name = el.get("Name")
                    elif el.tag == "Program" and stack[-2:] == ["Programs", "Program"]:
                        self.program = el.get("Name")
                        self.main_routine = el.get("MainRoutineName")
                    continue

                stack.pop()
                parent = stack[-1] if stack else None
                handled = True
                if el.tag == "Tag" and parent == "Tags":
                    self.tag(el)
                elif el.tag == "Routine" and parent == "Routines":
                    self.routine(el)
                elif el.tag == "Display" and parent == "HMIDisplays":
                    self.display(el)
                elif el.tag == "Alarm" and parent == "HMIAlarms":
                    self.alarm(el)
                elif el.tag == "Program" and parent == "Programs":
                    self.program = self.main_routine = None
                else:
                    handled = False
                if handled:
                    _release(el)
        except etree.XMLSyntaxError as exc:
            raise ParseError(f"Malformed XML: {exc}") from exc

        if self.controller_name is None:
            raise ParseError("L5X file has no <Controller> element")
        try:
            project = UIRProject(
                name=self.controller_name,
                vendor=VENDOR,
                source_filename=self.source_filename,
                tags=self.tags,
                routines=self.routines,
                screens=self.screens,
                alarms=self.alarms,
            )
        except ValidationError as exc:
            raise ParseError(f"L5X content is not a valid UIR: {_first_error(exc)}") from exc
        return ParseResult(project=project, warnings=self.warnings)

    @staticmethod
    def _events(stream: IO[bytes]) -> Iterator[tuple[str, Any]]:
        return iter(
            etree.iterparse(
                stream,
                events=("start", "end"),
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                huge_tree=False,
                remove_comments=True,
                remove_pis=True,
            )
        )

    @staticmethod
    def _check_root(el: etree._Element) -> None:
        docinfo = el.getroottree().docinfo
        if docinfo.doctype or docinfo.internalDTD is not None:
            raise UnsafeXMLError(
                "DTDs are not allowed in uploaded XML"
            ) from defusedxml.DTDForbidden(docinfo.doctype, docinfo.system_url, docinfo.public_id)
        if el.tag != ROOT_ELEMENT:
            raise ParseError(f"Not a Rockwell L5X export (root element is <{el.tag}>)")


def _release(el: etree._Element) -> None:
    el.clear(keep_tail=True)
    parent = el.getparent()
    if parent is not None:
        while el.getprevious() is not None:
            del parent[0]


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err["loc"])
        return f"{loc}: {err['msg']}" if loc else str(err["msg"])
    return str(exc)


def parse_l5x(source: Source, *, source_filename: str | None = None) -> ParseResult:
    """Parse an L5X document (path, raw bytes or binary stream) into a validated UIR project."""
    parser = _L5XStreamParser(source_filename)
    if isinstance(source, bytes):
        return parser.run(BytesIO(source))
    if isinstance(source, str | Path):
        path = Path(source)
        with path.open("rb") as fh:
            parser.source_filename = source_filename or path.name
            return parser.run(fh)
    return parser.run(source)


def looks_like_l5x(head: bytes) -> bool:
    return ROOT_ELEMENT.encode() in head
