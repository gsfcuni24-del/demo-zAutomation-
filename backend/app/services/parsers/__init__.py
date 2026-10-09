"""Vendor file parsers producing UIR documents."""

from pathlib import Path

from app.services.parsers.base import ParseError, ParseResult, UnsafeXMLError
from app.services.parsers.rockwell_l5x import looks_like_l5x, parse_l5x

__all__ = ["ParseError", "ParseResult", "UnsafeXMLError", "parse_file", "parse_l5x"]

_SNIFF_BYTES = 4096


def parse_file(path: Path, *, source_filename: str | None = None) -> ParseResult:
    """Pick a parser by extension/content sniffing and parse ``path``."""
    suffix = path.suffix.lower()
    with path.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)
    if suffix == ".l5x" or (suffix == ".xml" and looks_like_l5x(head)):
        return parse_l5x(path, source_filename=source_filename or path.name)
    if suffix == ".xml":
        raise ParseError(
            "Unsupported XML export: only Rockwell L5X (<RSLogix5000Content>) is supported"
        )
    raise ParseError(
        f"No parser for {suffix or 'extensionless'} files. Upload an .L5X/.xml export; "
        "Excel/CSV IO lists are imported through the AI assistant."
    )
