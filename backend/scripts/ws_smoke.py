"""Standalone WebSocket smoke test against a running API.

Usage: uv run python scripts/ws_smoke.py [--api http://localhost:8000] [--prompt "..."]
Creates a project, uploads samples/test_project.xml, streams one synthesis run and checks the diff.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import websockets

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_project.xml"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--prompt", default="Add pump P-101 with start/stop buttons and run indicator"
    )
    args = parser.parse_args()
    async with httpx.AsyncClient(base_url=f"{args.api}/api/v1", timeout=30) as http:
        project = (
            (await http.post("/projects", json={"name": "WS smoke"})).raise_for_status().json()
        )
        pid = project["id"]
        files = {"file": (SAMPLE.name, SAMPLE.read_bytes(), "application/xml")}
        upload = (await http.post(f"/projects/{pid}/files", files=files)).raise_for_status().json()
        print(f"project {pid}: uploaded -> UIR v{upload['snapshot']['version']}")
        ws_url = args.api.replace("http", "ws", 1) + f"/ws/synthesis/{pid}"
        async with websockets.connect(ws_url) as ws:
            print("<-", json.loads(await ws.recv())["message"])
            await ws.send(json.dumps({"prompt": args.prompt}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
                attempt = f" #{event['attempt']}" if event.get("attempt") else ""
                print(f"<- {event['agent']:<20} {event['status']:<10}{attempt} {event['message']}")
                if (event.get("data") or {}).get("final"):
                    break
        if event["status"] != "completed":
            return 1
        diff = (await http.get(f"/projects/{pid}/uir/diff")).raise_for_status().json()
        print(f"diff v{diff['base_version']} -> v{diff['target_version']}: {diff['summary']}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
