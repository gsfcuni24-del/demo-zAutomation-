import json
import uuid
from pathlib import Path

import anyio
from httpx import AsyncClient
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog, File, FileParseStatus, UIRSnapshot
from app.schemas.uir import UIRProject
from app.services.parsers import parse_l5x
from tests.conftest import SAMPLE_L5X, TEST_MAX_UPLOAD_BYTES

SAMPLE = SAMPLE_L5X.read_bytes()
TIMER_WARNING = "tag MainProgram.Start_Timer: data type 'TIMER' not supported, skipped"


async def _create_project(client: AsyncClient, name: str = "Line 1") -> dict[str, object]:
    response = await client.post(
        "/api/v1/projects", json={"name": name, "original_vendor": "ROCKWELL"}
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def test_create_and_list_projects(api_client: AsyncClient) -> None:
    created = await _create_project(api_client, "  Packaging Line  ")
    assert created["name"] == "Packaging Line"
    assert created["status"] == "DRAFT"
    assert created["original_vendor"] == "ROCKWELL"

    response = await api_client.get("/api/v1/projects")
    assert response.status_code == 200
    assert created["id"] in [p["id"] for p in response.json()]

    detail = await api_client.get(f"/api/v1/projects/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Packaging Line"


async def test_create_project_validation(api_client: AsyncClient) -> None:
    assert (await api_client.post("/api/v1/projects", json={"name": "   "})).status_code == 422
    response = await api_client.post("/api/v1/projects", json={"name": "x", "bogus": 1})
    assert response.status_code == 422


async def test_upload_file_creates_records_and_snapshot(
    api_client: AsyncClient, db_session: AsyncSession, upload_dir: Path
) -> None:
    project = await _create_project(api_client)
    project_id = project["id"]

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("../../etc/plc export.xml", SAMPLE, "application/xml")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file"]["filename"] == "plc_export.xml"
    assert body["file"]["file_size_bytes"] == len(SAMPLE)
    assert body["file"]["parse_status"] == "SUCCESS"
    assert body["warnings"] == [TIMER_WARNING]
    assert body["snapshot"]["version"] == 1
    assert body["snapshot"]["parent_version_hash"] is None

    file = await db_session.get(File, uuid.UUID(body["file"]["id"]))
    assert file is not None
    assert file.parse_status is FileParseStatus.SUCCESS
    stored = anyio.Path(file.local_path)
    assert await stored.is_file()
    assert await stored.read_bytes() == SAMPLE
    assert Path(stored.parent) == upload_dir / str(project_id)

    latest = await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")
    assert latest.status_code == 200
    snapshot = latest.json()
    assert snapshot["version"] == 1
    uir = UIRProject.model_validate(snapshot["uir"])
    assert uir.source_filename == "plc_export.xml"
    assert uir.name == "Packaging_Line_3"
    assert len(uir.tags) == 17 and uir.tags[0].name == "Start_PB"
    assert {t.scope.value for t in uir.tags} == {"CONTROLLER", "PROGRAM"}

    project_after = (await api_client.get(f"/api/v1/projects/{project_id}")).json()
    assert project_after["status"] == "READY"

    files = (await api_client.get(f"/api/v1/projects/{project_id}/files")).json()
    assert [f["id"] for f in files] == [body["file"]["id"]]

    actions = (
        await db_session.exec(
            select(AuditLog.action)
            .where(AuditLog.project_id == uuid.UUID(str(project_id)))
            .order_by(col(AuditLog.created_at))
        )
    ).all()
    assert list(actions) == ["project.created", "file.uploaded"]


async def test_second_upload_chains_snapshot_versions(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    project_id = (await _create_project(api_client))["id"]
    url = f"/api/v1/projects/{project_id}/files"
    first = (await api_client.post(url, files={"file": ("a.xml", SAMPLE)})).json()["snapshot"]
    second = (await api_client.post(url, files={"file": ("b.L5X", SAMPLE)})).json()["snapshot"]
    assert second["version"] == 2
    assert second["parent_version_hash"] == first["version_hash"]

    latest = (await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")).json()
    assert latest["version"] == 2
    assert latest["uir"]["source_filename"] == "b.L5X"

    count = (
        await db_session.exec(
            select(UIRSnapshot).where(UIRSnapshot.project_id == uuid.UUID(str(project_id)))
        )
    ).all()
    assert len(count) == 2


async def test_upload_rejections_leave_no_records(
    api_client: AsyncClient, db_session: AsyncSession, upload_dir: Path
) -> None:
    project_id = (await _create_project(api_client))["id"]
    url = f"/api/v1/projects/{project_id}/files"

    bad_type = await api_client.post(url, files={"file": ("payload.exe", b"MZ")})
    assert bad_type.status_code == 422
    too_big = await api_client.post(
        url, files={"file": ("big.xml", b"x" * (TEST_MAX_UPLOAD_BYTES + 1))}
    )
    assert too_big.status_code == 413
    empty = await api_client.post(url, files={"file": ("empty.xml", b"")})
    assert empty.status_code == 422

    files = (
        await db_session.exec(select(File).where(File.project_id == uuid.UUID(str(project_id))))
    ).all()
    assert files == []
    project_dir = anyio.Path(upload_dir / str(project_id))
    assert not await project_dir.exists() or not [p async for p in project_dir.iterdir()]


async def test_latest_uir_404_and_unknown_project(api_client: AsyncClient) -> None:
    project_id = (await _create_project(api_client))["id"]
    response = await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")
    assert response.status_code == 404

    missing = uuid.uuid4()
    assert (await api_client.get(f"/api/v1/projects/{missing}")).status_code == 404
    assert (await api_client.get(f"/api/v1/projects/{missing}/uir/latest")).status_code == 404
    upload = await api_client.post(
        f"/api/v1/projects/{missing}/files", files={"file": ("a.txt", b"x")}
    )
    assert upload.status_code == 404


async def _actions(db_session: AsyncSession, project_id: object) -> list[str]:
    rows = await db_session.exec(
        select(AuditLog.action)
        .where(AuditLog.project_id == uuid.UUID(str(project_id)))
        .order_by(col(AuditLog.created_at))
    )
    return list(rows.all())


async def test_unparseable_xml_is_rejected_but_recorded(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    project_id = (await _create_project(api_client))["id"]
    url = f"/api/v1/projects/{project_id}/files"
    response = await api_client.post(url, files={"file": ("tia.xml", b"<Document/>")})
    assert response.status_code == 422
    assert "Unsupported XML export" in response.json()["detail"]
    xxe = b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><RSLogix5000Content/>'
    response = await api_client.post(url, files={"file": ("evil.l5x", xxe)})
    assert response.status_code == 422
    assert "DTD" in response.json()["detail"]

    files = (await api_client.get(f"/api/v1/projects/{project_id}/files")).json()
    assert [f["parse_status"] for f in files] == ["FAILED", "FAILED"]
    assert (await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")).status_code == 404
    assert (await api_client.get(f"/api/v1/projects/{project_id}")).json()["status"] == "DRAFT"
    assert await _actions(db_session, project_id) == [
        "project.created",
        "file.parse_failed",
        "file.parse_failed",
    ]


async def test_csv_upload_is_pending_for_ai_ingestion(api_client: AsyncClient) -> None:
    project_id = (await _create_project(api_client))["id"]
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("io_list.csv", b"tag,type\nStart_PB,BOOL\n")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file"]["parse_status"] == "PENDING"
    assert body["snapshot"] is None and body["warnings"] == []
    assert (await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")).status_code == 404


async def test_uir_json_upload(api_client: AsyncClient) -> None:
    project_id = (await _create_project(api_client))["id"]
    url = f"/api/v1/projects/{project_id}/files"
    doc = parse_l5x(SAMPLE).project.model_dump_json().encode()
    response = await api_client.post(url, files={"file": ("uir.json", doc)})
    assert response.status_code == 201, response.text
    latest = (await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")).json()
    assert latest["uir"]["source_filename"] == "uir.json"
    bad = await api_client.post(url, files={"file": ("bad.json", b'{"name": "x", "tags": 1}')})
    assert bad.status_code == 422 and "Invalid UIR JSON" in bad.json()["detail"]


async def test_versions_diff_audit_and_export(api_client: AsyncClient) -> None:
    project_id = (await _create_project(api_client, "Line 3 / Packaging"))["id"]
    base = f"/api/v1/projects/{project_id}"
    await api_client.post(f"{base}/files", files={"file": ("line.L5X", SAMPLE)})
    doc = parse_l5x(SAMPLE, source_filename="line.L5X").project.model_dump(mode="json")
    doc["tags"][0]["description"] = "Green start button"
    doc["tags"].pop()
    doc["screens"][0]["widgets"][0]["tag_ref"] = "Stop_PB"
    await api_client.post(f"{base}/files", files={"file": ("line.json", json.dumps(doc).encode())})

    versions = (await api_client.get(f"{base}/uir/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    v1 = (await api_client.get(f"{base}/uir/1")).json()
    assert v1["uir"]["source_filename"] == "line.L5X"
    assert (await api_client.get(f"{base}/uir/9")).status_code == 404

    diff = (await api_client.get(f"{base}/uir/diff")).json()
    assert (diff["base_version"], diff["target_version"]) == (1, 2)
    changes = {(c["change_type"], c["path"]) for c in diff["changes"]}
    assert ("MODIFIED", "$.tags[0].description") in changes
    assert ("REMOVED", "$.tags[16]") in changes
    assert ("MODIFIED", "$.screens[0].widgets[0].tag_ref") in changes
    assert ("MODIFIED", "$.source_filename") in changes
    first = (await api_client.get(f"{base}/uir/diff", params={"target": 1})).json()
    assert first["base_version"] is None and first["summary"]["added"] > 0

    report = (await api_client.get(f"{base}/uir/audit")).json()
    assert report["passed"] is True and report["rules_checked"] == ["R-001", "R-002", "R-003"]

    export = await api_client.get(f"{base}/export/l5x", params={"version": 1})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/xml")
    assert 'filename="Line_3_Packaging_v1.L5X"' in export.headers["content-disposition"]
    assert parse_l5x(
        export.content, source_filename="line.L5X"
    ).project == UIRProject.model_validate(v1["uir"])
