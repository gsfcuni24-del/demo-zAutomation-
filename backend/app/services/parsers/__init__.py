"""Vendor file parsers producing UIR documents."""

import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.uir import UIRProject
from app.services.parsers.base import ParseError, ParseResult, UnsafeXMLError
from app.services.parsers.rockwell_l5x import looks_like_l5x, parse_l5x

__all__ = [
    "AI_INGEST_EXTENSIONS",
    "ParseError",
    "ParseResult",
    "UnsafeXMLError",
    "parse_file",
    "parse_l5x",
    "requires_ai_ingestion",
]

_SNIFF_BYTES = 4096
# Unstructured inputs (IO lists, specs) are converted to UIR by the Excel Parser agent.
AI_INGEST_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".txt"})


def requires_ai_ingestion(path: Path) -> bool:
    return path.suffix.lower() in AI_INGEST_EXTENSIONS


def _parse_uir_json(path: Path, source_filename: str) -> ParseResult:
    try:
        data = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"Malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError("UIR JSON must be an object")
    try:
        project = UIRProject.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise ParseError(f"Invalid UIR JSON at {loc or '$'}: {first['msg']}") from exc
    return ParseResult(project.model_copy(update={"source_filename": source_filename}))


def parse_file(path: Path, *, source_filename: str | None = None) -> ParseResult:
    """Pick a deterministic parser by extension/content sniffing and parse ``path``."""
    name = source_filename or path.name
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_uir_json(path, name)
    with path.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)
    if suffix == ".l5x" or (suffix == ".xml" and looks_like_l5x(head)):
        return parse_l5x(path, source_filename=name)
    if suffix == ".xml":
        raise ParseError(
            "Unsupported XML export: only Rockwell L5X (<RSLogix5000Content>) is supported"
        )
    raise ParseError(
        f"No parser for {suffix or 'extensionless'} files. Upload an .L5X/.xml export; "
        "Excel/CSV IO lists are imported through the AI assistant."
    )
