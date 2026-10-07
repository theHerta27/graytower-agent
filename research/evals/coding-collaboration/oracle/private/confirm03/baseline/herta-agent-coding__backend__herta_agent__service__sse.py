"""A POST response owns admission and observes disconnect before any headers."""

import asyncio

from starlette.responses import Response

from herta_agent.service.events import encode_event
from herta_agent.service.runs import _wait_owned


class RunResponse(Response):
    def __init__(self, manager, session_id, text, settings):
        super().__init__(media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        self.raw_headers = [
            (key, value) for key, value in self.raw_headers if key != b"content-length"
        ]
        self.manager, self.session_id, self.text = manager, session_id, text
        self.settings, self.handle = settings, None

    async def __call__(self, scope, receive, send):
        serving = asyncio.create_task(self._serve(send))
        disconnected = asyncio.create_task(self._disconnect(receive))
        try:
            finished, _ = await asyncio.wait(
                (serving, disconnected), return_when=asyncio.FIRST_COMPLETED
            )
            if serving in finished:
                await serving
        finally:
            cleanup = asyncio.create_task(self._cleanup(serving, disconnected))
            await _wait_owned(cleanup)

    async def _cleanup(self, serving, disconnected):
        serving.cancel()
        disconnected.cancel()
        await asyncio.gather(serving, disconnected, return_exceptions=True)
        if self.handle is not None:
            await self.manager.cancel(self.handle.run_id, "disconnect")

    async def _disconnect(self, receive):
        while (await receive())["type"] != "http.disconnect":
            pass

    async def _send(self, send, message):
        async with asyncio.timeout(self.settings.send_wait_seconds):
            await send(message)

    async def _serve(self, send):
        self.handle = await self.manager.submit(self.session_id, self.text)
        try:
            await self._send(
                send, {"type": "http.response.start", "status": 200, "headers": self.raw_headers}
            )
            while True:
                try:
                    async with asyncio.timeout(self.settings.heartbeat_seconds):
                        event = await self.handle.events.get()
                except TimeoutError:
                    if self.handle.done.is_set():
                        break
                    await self._send(
                        send,
                        {
                            "type": "http.response.body",
                            "body": b": heartbeat\n\n",
                            "more_body": True,
                        },
                    )
                    continue
                if self.handle.cancel_requested and event["type"] == "llm.delta":
                    continue  # Buffered partial has not yet reached the transport.
                await self._send(
                    send,
                    {"type": "http.response.body", "body": encode_event(event), "more_body": True},
                )
                if event["type"] in {
                    "run.completed",
                    "run.failed",
                    "run.cancelled",
                    "service.error",
                }:
                    break
            await self._send(send, {"type": "http.response.body", "body": b"", "more_body": False})
        except (TimeoutError, OSError):
            pass  # A stalled/closed transport cancels its owner in response cleanup.
