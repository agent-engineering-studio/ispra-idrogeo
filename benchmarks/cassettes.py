"""Record IdroGEO's real answers once, replay them offline.

A cassette is the list of requests a case made and the answers IdroGEO gave,
as JSON. :class:`Recorder` wraps the real transport and writes them;
:class:`Replayer` answers from them and refuses any request it has not seen,
so a change in what the library asks for shows up as a failure, not as a
silent call to the network.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

FOLDER = Path(__file__).parent / "cassettes"


def key(request: httpx.Request) -> str:
    """The method, the path, the sorted query and the body of a request."""
    query = "&".join(f"{k}={v}" for k, v in sorted(request.url.params.multi_items()))
    body = request.content.decode("utf-8", errors="replace") if request.content else ""
    if body.startswith(("{", "[")):
        body = json.dumps(json.loads(body), sort_keys=True)
    return f"{request.method} {request.url.host}{request.url.path}?{query} {body}".strip()


def _encode(content: bytes) -> dict[str, str]:
    try:
        return {"text": content.decode("utf-8")}
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(content).decode("ascii")}


def _decode(entry: dict[str, str]) -> bytes:
    if "text" in entry:
        return entry["text"].encode("utf-8")
    return base64.b64decode(entry["base64"])


class Recorder(httpx.AsyncBaseTransport):
    """Passes requests to the network and keeps every answer."""

    def __init__(self) -> None:
        self._real = httpx.AsyncHTTPTransport(retries=2)
        self.entries: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._real.handle_async_request(request)
        content = await response.aread()
        self.entries.append(
            {
                "request": key(request),
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                **_encode(content),
            }
        )
        # the content is already decoded: drop the headers that describe the wire
        headers = [
            (k, v)
            for k, v in response.headers.multi_items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        ]
        return httpx.Response(
            response.status_code, headers=headers, content=content, request=request
        )

    def save(self, name: str, recorded_on: str) -> Path:
        path = FOLDER / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"recorded_on": recorded_on, "entries": self.entries}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path


class Replayer(httpx.AsyncBaseTransport):
    """Answers from a cassette; a request it has not seen gets a 599."""

    def __init__(self, name: str) -> None:
        data = json.loads((FOLDER / f"{name}.json").read_text(encoding="utf-8"))
        self.recorded_on: str = data["recorded_on"]
        self._answers = {e["request"]: e for e in data["entries"]}
        self.unseen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        entry = self._answers.get(key(request))
        if entry is None:
            self.unseen.append(key(request))
            return httpx.Response(599, text="not in the cassette", request=request)
        headers = {"content-type": entry["content_type"]} if entry["content_type"] else {}
        return httpx.Response(
            entry["status"], headers=headers, content=_decode(entry), request=request
        )
