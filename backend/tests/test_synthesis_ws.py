import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.llm import LLMClient, get_llm_client
from app.ai.rag import get_retriever
from app.ai.rag.retriever import HashingEmbedder, StandardsRetriever
from app.api.ws.synthesis import get_session_factory
from app.db.session import get_session
from app.main import app
from app.services.storage import LocalFileStorage, get_storage
from tests.conftest import SAMPLE_L5X


@pytest.fixture
def ws_client(db_engine: AsyncEngine, tmp_path: Any) -> Any:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _session() -> Any:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_llm_client] = lambda: LLMClient(mock=True)
    app.dependency_overrides[get_retriever] = lambda: StandardsRetriever(
        None, HashingEmbedder(), "t"
    )
    app.dependency_overrides[get_storage] = lambda: LocalFileStorage(
        tmp_path, max_bytes=1 << 20, allowed_extensions=[".xml", ".csv"]
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _collect(ws: Any) -> list[dict[str, Any]]:
    events = []
    while True:
        e = json.loads(ws.receive_text())
        events.append(e)
        if (e.get("data") or {}).get("final"):
            return events


def test_ws_streams_pipeline_and_saves_snapshot(ws_client: TestClient) -> None:
    pid = ws_client.post("/api/v1/projects", json={"name": "WS"}).json()["id"]
    ws_client.post(
        f"/api/v1/projects/{pid}/files", files={"file": ("line.xml", SAMPLE_L5X.read_bytes())}
    )
    with ws_client.websocket_connect(f"/ws/synthesis/{pid}") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["status"] == "connected" and hello["data"]["mode"] == "mock"
        ws.send_text("not json")
        assert _collect(ws)[-1]["status"] == "failed"
        ws.send_text(json.dumps({"prompt": "Add pump P-101 with start and stop"}))
        events = _collect(ws)
    agents = [e["agent"] for e in events]
    for name in (
        "excel_parser",
        "tag_namer",
        "logic_drafter",
        "hmi_layouter",
        "safety_auditor",
        "vendor_compiler",
        "diff_engine",
    ):
        assert name in agents
    assert any(e["status"] == "retry" for e in events)
    final = events[-1]
    assert final["status"] == "completed" and final["data"]["snapshot"]["version"] == 2
    diff = ws_client.get(f"/api/v1/projects/{pid}/uir/diff").json()
    assert diff["target_version"] == 2 and diff["summary"]["added"] > 0


def test_ws_ingests_pending_csv(ws_client: TestClient) -> None:
    pid = ws_client.post("/api/v1/projects", json={"name": "CSV"}).json()["id"]
    csv = (
        b"Tag,Type,Description,Address\n"
        b"Level_High,BOOL,Tank high level,Local:1:I.Data.0\n"
        b"Fill_Valve,BOOL,Fill valve,Local:2:O.Data.0\n"
    )
    up = ws_client.post(f"/api/v1/projects/{pid}/files", files={"file": ("io.csv", csv)}).json()
    assert up["file"]["parse_status"] == "PENDING"
    with ws_client.websocket_connect(f"/ws/synthesis/{pid}") as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"prompt": "Import the IO list"}))
        events = _collect(ws)
    assert events[-1]["status"] == "completed", events[-3:]
    tags = {
        t["name"] for t in ws_client.get(f"/api/v1/projects/{pid}/uir/latest").json()["uir"]["tags"]
    }
    assert {"Level_High", "Fill_Valve"} <= tags
    files = ws_client.get(f"/api/v1/projects/{pid}/files").json()
    assert files[0]["parse_status"] == "SUCCESS"


def test_ws_rejects_unknown_project_and_foreign_origin(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/synthesis/00000000-0000-0000-0000-000000000000") as ws:
        assert json.loads(ws.receive_text())["message"] == "Project not found"
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(
            "/ws/synthesis/00000000-0000-0000-0000-000000000000",
            headers={"origin": "https://evil.example"},
        ) as ws:
            ws.receive_text()
