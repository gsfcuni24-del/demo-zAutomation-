"""Shared parser types."""

from dataclasses import dataclass, field

from app.schemas.uir import UIRProject


class ParseError(ValueError):
    """The source file could not be converted into a valid UIR document."""


class UnsafeXMLError(ParseError):
    """XML with DTDs/entities, rejected to prevent XXE and entity-expansion attacks."""


@dataclass(slots=True)
class ParseResult:
    project: UIRProject
    warnings: list[str] = field(default_factory=list)
