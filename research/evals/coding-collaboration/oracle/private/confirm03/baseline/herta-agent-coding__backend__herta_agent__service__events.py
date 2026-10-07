"""Versioned SSE representation and bounded, transient event buffering."""

import asyncio
import json
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

MAX_EVENT_BYTES = 256 * 1024
MAX_BUFFER_BYTES = 2 * 1024 * 1024


class ServiceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    type: Literal[
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "llm.started",
        "llm.delta",
        "llm.completed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "rag.retrieved",
        "service.error",
    ]
    session_id: str = Field(pattern=r"^[^\r\n]+$")
    run_id: str = Field(pattern=r"^[^\r\n]+$")
    seq: int = Field(ge=1)
    timestamp: str
    payload: dict[str, JsonValue]


def encode_event(event) -> bytes:
    value = ServiceEvent.model_validate(event).model_dump()
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = (
        f"id: {value['run_id']}:{value['seq']}\nevent: {value['type']}\ndata: {data}\n\n".encode()
    )
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError("Service event exceeds size limit")
    return encoded


class EventQueue(asyncio.Queue):
    def __init__(self):
        super().__init__(maxsize=128)
        self._sizes = deque()
        self._bytes = 0
        self._space = asyncio.Event()

    def put_nowait(self, item):
        size = len(encode_event(item))
        if self._bytes + size > MAX_BUFFER_BYTES:
            raise asyncio.QueueFull
        super().put_nowait(item)
        self._sizes.append(size)
        self._bytes += size

    def get_nowait(self):
        item = super().get_nowait()
        self._bytes -= self._sizes.popleft()
        self._space.set()
        return item

    async def put(self, item):
        while True:
            try:
                self.put_nowait(item)
                return
            except asyncio.QueueFull:
                self._space.clear()
                await self._space.wait()


def adapt_runtime(event):
    payload = {
        "step": event.step,
        "message_id": event.message_id,
        "tool_call_id": event.tool_call_id,
        **event.payload,
    }
    yield event.type, payload
    result = event.payload.get("result", {})
    if (
        event.type == "tool.completed"
        and event.payload.get("name") == "search_knowledge"
        and result.get("ok") is True
    ):
        data = result["data"]
        yield (
            "rag.retrieved",
            {
                "step": event.step,
                "tool_call_id": event.tool_call_id,
                "query": data.get("query"),
                "index_id": data.get("index_id"),
                "chunks": [
                    {key: chunk.get(key) for key in ("id", "source", "source_spans", "score")}
                    for chunk in data.get("chunks", [])
                ],
            },
        )
