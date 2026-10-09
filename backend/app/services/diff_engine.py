"""Structured UIR diff (deepdiff) with ADDED / REMOVED / MODIFIED entries and exact JSON paths.

Collections are keyed by their stable identifier before diffing so that inserting a tag does not
show up as every following tag being "modified". Reported paths point into the real documents:
the new document for ADDED/MODIFIED entries and the old document for REMOVED entries.
"""

from enum import StrEnum
from typing import Any

from deepdiff import DeepDiff
from pydantic import BaseModel, Field

from app.schemas.uir import UIRProject

# collection -> key field; nested collections are addressed as (parent, child)
_TOP_LEVEL_KEYS: dict[str, str] = {"tags": "id", "routines": "id", "screens": "id", "alarms": "id"}
_NESTED_KEYS: dict[tuple[str, str], str] = {
    ("routines", "rungs"): "number",
    ("screens", "widgets"): "id",
}
_COLLECTION_ORDER = ["tags", "routines", "screens", "alarms"]


class ChangeType(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class DiffEntry(BaseModel):
    change_type: ChangeType
    path: str
    collection: str | None
    entity_id: str | None
    field: str | None
    old_value: Any = None
    new_value: Any = None


class DiffSummary(BaseModel):
    added: int = 0
    removed: int = 0
    modified: int = 0


class DiffResult(BaseModel):
    summary: DiffSummary = Field(default_factory=DiffSummary)
    changes: list[DiffEntry] = Field(default_factory=list)


UIRInput = UIRProject | dict[str, Any] | None


def _as_json(doc: UIRInput) -> dict[str, Any]:
    if doc is None:
        return {}
    if isinstance(doc, UIRProject):
        return doc.model_dump(mode="json")
    return doc


def _keyed(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in doc.items():
        key_field = _TOP_LEVEL_KEYS.get(key)
        if key_field is None or not isinstance(value, list):
            out[key] = value
            continue
        items: dict[str, Any] = {}
        for item in value:
            entity = dict(item)
            for (parent, child), child_key in _NESTED_KEYS.items():
                if parent == key and isinstance(entity.get(child), list):
                    entity[child] = {str(c[child_key]): c for c in entity[child]}
            items[str(entity[key_field])] = entity
        out[key] = items
    return out


def _index_of(items: list[Any], key_field: str, key: str) -> int:
    for i, item in enumerate(items):
        if str(item.get(key_field)) == key:
            return i
    raise KeyError(key)


def _real_path(keys: list[Any], doc: dict[str, Any]) -> str:
    """Translate a keyed-document path into a JSONPath over the original document."""
    parts = ["$"]
    node: Any = doc
    parent_collection: str | None = None
    i = 0
    while i < len(keys):
        key = keys[i]
        parts.append(f".{key}" if isinstance(key, str) else f"[{key}]")
        node = node[key]
        collection_key = None
        if parent_collection is None and key in _TOP_LEVEL_KEYS:
            collection_key = _TOP_LEVEL_KEYS[key]
        elif parent_collection is not None:
            collection_key = _NESTED_KEYS.get((parent_collection, key))
        if collection_key is not None and isinstance(node, list) and i + 1 < len(keys):
            idx = _index_of(node, collection_key, str(keys[i + 1]))
            parts.append(f"[{idx}]")
            node = node[idx]
            if parent_collection is None:
                parent_collection = key
            i += 2
            continue
        i += 1
    return "".join(parts)


def _classify(keys: list[Any]) -> tuple[str | None, str | None, str | None]:
    if not keys or keys[0] not in _TOP_LEVEL_KEYS:
        return None, None, str(keys[0]) if keys else None
    collection = str(keys[0])
    entity_id = str(keys[1]) if len(keys) > 1 else None
    rest = [str(k) for k in keys[2:]]
    return collection, entity_id, ".".join(rest) or None


def _is_emptied_collection(t1: Any, t2: Any) -> bool:
    """DeepDiff reports ``{} -> {...}`` as one value change; split it into per-item entries."""
    return isinstance(t1, dict) and isinstance(t2, dict) and (not t1 or not t2)


_REPORT_TYPES: dict[str, ChangeType] = {
    "dictionary_item_added": ChangeType.ADDED,
    "iterable_item_added": ChangeType.ADDED,
    "dictionary_item_removed": ChangeType.REMOVED,
    "iterable_item_removed": ChangeType.REMOVED,
    "values_changed": ChangeType.MODIFIED,
    "type_changes": ChangeType.MODIFIED,
}


def diff_uir(old: UIRInput, new: UIRInput) -> DiffResult:
    """Compare two UIR snapshots. ``old=None`` treats every entity in ``new`` as ADDED."""
    old_doc, new_doc = _as_json(old), _as_json(new)
    if not old_doc:
        old_doc = {k: [] for k in _TOP_LEVEL_KEYS} | {
            k: v for k, v in new_doc.items() if k not in _TOP_LEVEL_KEYS
        }
    tree = DeepDiff(_keyed(old_doc), _keyed(new_doc), view="tree", verbose_level=2)
    result = DiffResult()
    for report_type, change_type in _REPORT_TYPES.items():
        for level in tree.get(report_type, []):
            keys = level.path(output_format="list")
            if change_type is ChangeType.MODIFIED and _is_emptied_collection(level.t1, level.t2):
                for key, kind in [(k, ChangeType.REMOVED) for k in level.t1 or {}] + [
                    (k, ChangeType.ADDED) for k in level.t2 or {}
                ]:
                    sub = [*keys, key]
                    item = (level.t1 if kind is ChangeType.REMOVED else level.t2)[key]
                    collection, entity_id, field = _classify(sub)
                    result.changes.append(
                        DiffEntry(
                            change_type=kind,
                            path=_real_path(
                                sub, old_doc if kind is ChangeType.REMOVED else new_doc
                            ),
                            collection=collection,
                            entity_id=entity_id,
                            field=field,
                            old_value=item if kind is ChangeType.REMOVED else None,
                            new_value=item if kind is ChangeType.ADDED else None,
                        )
                    )
                continue
            doc = old_doc if change_type is ChangeType.REMOVED else new_doc
            collection, entity_id, field = _classify(keys)
            result.changes.append(
                DiffEntry(
                    change_type=change_type,
                    path=_real_path(keys, doc),
                    collection=collection,
                    entity_id=entity_id,
                    field=field,
                    old_value=None if change_type is ChangeType.ADDED else level.t1,
                    new_value=None if change_type is ChangeType.REMOVED else level.t2,
                )
            )
    result.changes.sort(
        key=lambda c: (
            _COLLECTION_ORDER.index(c.collection) if c.collection in _COLLECTION_ORDER else -1,
            c.entity_id or "",
            c.path,
        )
    )
    for change in result.changes:
        if change.change_type is ChangeType.ADDED:
            result.summary.added += 1
        elif change.change_type is ChangeType.REMOVED:
            result.summary.removed += 1
        else:
            result.summary.modified += 1
    return result
