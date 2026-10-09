from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.uir import Tag, UIRProject
from app.services.uir import build_mock_uir, hash_uir


def _mock() -> dict[str, Any]:
    return build_mock_uir("P", "SIEMENS", "x.xml").model_dump(mode="json")


def test_mock_uir_round_trips() -> None:
    data = _mock()
    assert UIRProject.model_validate(data).model_dump(mode="json") == data


def test_extra_fields_forbidden() -> None:
    data = _mock()
    data["tags"][0]["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        UIRProject.model_validate(data)


def test_tag_scope_rules() -> None:
    with pytest.raises(ValidationError, match="require 'program'"):
        Tag(id="t", name="A", data_type="BOOL", scope="PROGRAM")
    with pytest.raises(ValidationError, match="must not set 'program'"):
        Tag(id="t", name="A", data_type="BOOL", scope="CONTROLLER", program="P")
    with pytest.raises(ValidationError):
        Tag(id="t", name="1bad", data_type="BOOL", scope="CONTROLLER")


def test_unresolved_tag_reference_rejected() -> None:
    data = _mock()
    data["alarms"][0]["tag_ref"] = "Nope"
    with pytest.raises(ValidationError, match="unresolved tag references: Nope"):
        UIRProject.model_validate(data)


def test_duplicate_tag_in_same_scope_rejected() -> None:
    data = _mock()
    dup = dict(data["tags"][0], id="other")
    data["tags"].append(dup)
    with pytest.raises(ValidationError, match="duplicate tag"):
        UIRProject.model_validate(data)


def test_hash_is_order_independent() -> None:
    assert hash_uir({"a": 1, "b": [1, 2]}) == hash_uir({"b": [1, 2], "a": 1})
    assert len(hash_uir(_mock())) == 64
