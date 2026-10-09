import uuid
from pathlib import Path

import anyio
from httpx import AsyncClient
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog, File, FileParseStatus, UIRSnapshot
from app.schemas.uir import UIRProject


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
        files={"file": ("../../etc/plc export.xml", b"<Controller/>", "application/xml")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file"]["filename"] == "plc_export.xml"
    assert body["file"]["file_size_bytes"] == len(b"<Controller/>")
    assert body["file"]["parse_status"] == "SUCCESS"
    assert body["snapshot"]["version"] == 1
    assert body["snapshot"]["parent_version_hash"] is None

    file = await db_session.get(File, uuid.UUID(body["file"]["id"]))
    assert file is not None
    assert file.parse_status is FileParseStatus.SUCCESS
    stored = anyio.Path(file.local_path)
    assert await stored.is_file()
    assert await stored.read_bytes() == b"<Controller/>"
    assert Path(stored.parent) == upload_dir / str(project_id)

    latest = await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")
    assert latest.status_code == 200
    snapshot = latest.json()
    assert snapshot["version"] == 1
    uir = UIRProject.model_validate(snapshot["uir"])
    assert uir.source_filename == "plc_export.xml"
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
    first = (await api_client.post(url, files={"file": ("a.txt", b"one")})).json()["snapshot"]
    second = (await api_client.post(url, files={"file": ("b.txt", b"two")})).json()["snapshot"]
    assert second["version"] == 2
    assert second["parent_version_hash"] == first["version_hash"]

    latest = (await api_client.get(f"/api/v1/projects/{project_id}/uir/latest")).json()
    assert latest["version"] == 2
    assert latest["uir"]["source_filename"] == "b.txt"

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
    too_big = await api_client.post(url, files={"file": ("big.xml", b"x" * 2048)})
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
