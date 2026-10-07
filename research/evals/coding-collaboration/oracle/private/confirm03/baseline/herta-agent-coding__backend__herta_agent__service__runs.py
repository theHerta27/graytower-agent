"""One-process admission and ownership of persistent Agent runs."""

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from herta_agent.runtime.errors import AgentError
from herta_agent.runtime.messages import Message
from herta_agent.runtime.session import Session
from herta_agent.service.events import EventQueue, adapt_runtime
from herta_agent.service.settings import ServiceSettings
from herta_agent.service.turn import PersistentTurn
from herta_agent.storage.models import Admission, RunConfig, RunRecord, StoreError


class SessionConflictError(AgentError):
    code = "session_busy"

    def __init__(self):
        super().__init__("会话正在执行。")


class RunCapacityError(AgentError):
    code = "run_capacity_exceeded"

    def __init__(self):
        super().__init__("活跃Run已达到上限，请稍后重新提交。")


@dataclass
class RunHandle:
    run_id: str
    session_id: str
    events: EventQueue = field(default_factory=EventQueue)
    event_wait_seconds: float = 2.0
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    admitting: asyncio.Task | None = None
    finalizing: asyncio.Task | None = None
    started: bool = False
    admission: Admission | None = None
    terminal: RunRecord | None = None
    cancel_requested: bool = False
    step: int = 0
    seq: int = 0

    def _event(self, type, payload):
        self.seq += 1
        return {
            "type": type,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "schema_version": 1,
            "payload": payload,
        }

    def publish(self, type, payload, *, terminal=False):
        event = self._event(type, payload)
        while True:
            try:
                self.events.put_nowait(event)
                return
            except asyncio.QueueFull:
                if not terminal:
                    raise
                self.events.get_nowait()  # Cleanup never waits for a consumer.

    async def emit(self, event):
        if self.cancel_requested:
            raise asyncio.CancelledError
        self.step = event.step
        try:
            for type, payload in adapt_runtime(event):
                async with asyncio.timeout(self.event_wait_seconds):
                    await self.events.put(self._event(type, payload))
        except (TimeoutError, ValueError):
            self.cancel_requested = True
            raise asyncio.CancelledError from None


@dataclass(frozen=True)
class RunView:
    run: RunRecord
    cancel_requested: bool


@dataclass(frozen=True)
class CancelResult:
    accepted: bool
    status: str
    cancel_requested: bool


async def _wait_owned(task):
    """Internal cleanup retains ownership despite repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class RunManager:
    def __init__(self, store, agent, settings: ServiceSettings | None = None, *, model=None):
        self.store, self.agent = store, agent
        self.settings = settings or ServiceSettings()
        model = model or getattr(
            getattr(agent.provider, "settings", None), "model", type(agent.provider).__name__
        )
        self.config = RunConfig(model=model, settings=agent.settings)
        self._active: dict[str, RunHandle] = {}
        self._sessions: set[str] = set()
        self._stopping = False
        self._shutdown_task: asyncio.Task | None = None

    @property
    def active_count(self):
        return len(self._active)

    def check_admission(self, session_id):
        if self._stopping or not self.store.writable:
            raise StoreError("service_unavailable", "服务停止接纳或存储不可写。")
        if session_id in self._sessions:
            raise SessionConflictError()
        if self.active_count >= self.settings.max_active_runs:
            raise RunCapacityError()

    async def submit(self, session_id: str, user_text: str) -> RunHandle:
        user = Message(role="user", content=user_text)
        self.check_admission(session_id)
        handle = RunHandle(
            uuid4().hex, session_id, event_wait_seconds=self.settings.event_wait_seconds
        )
        self._active[handle.run_id] = handle
        self._sessions.add(session_id)  # No await before reservation.
        coroutine = self._admit_and_launch(handle, user)
        try:
            handle.admitting = asyncio.create_task(coroutine)
        except Exception:
            coroutine.close()
            self._release(handle)
            raise StoreError("run_start_failed", "无法启动接纳任务。") from None
        try:
            return await asyncio.shield(handle.admitting)
        except asyncio.CancelledError:
            self._request_cancel(handle)
            try:
                await _wait_owned(handle.admitting)
            except Exception:
                pass  # The admission owner already finalized/released on failure.
            self._request_cancel(handle)
            if handle.task is not None:
                await _wait_owned(handle.task)
            raise

    async def _admit_and_launch(self, handle, user):
        try:
            handle.admission = await self.store.admit_run(
                handle.session_id, handle.run_id, user, self.config
            )
            coroutine = self._execute(handle)
            try:
                handle.task = asyncio.create_task(coroutine)
            except Exception:
                coroutine.close()
                await self._finish(
                    handle,
                    "cancelled" if handle.cancel_requested else "failed",
                    error="无法启动Run任务。",
                )
                raise StoreError("run_start_failed", "无法启动Run任务。") from None
            return handle
        except BaseException:
            self._release(handle)
            raise

    async def get(self, run_id) -> RunView:
        run = await self.store.get_run(run_id)
        handle = self._active.get(run_id)
        return RunView(run, handle.cancel_requested if handle else run.status == "cancelled")

    def _request_cancel(self, handle) -> bool:
        if handle.terminal is not None or handle.finalizing is not None or handle.cancel_requested:
            return False
        handle.cancel_requested = True
        if handle.task is not None and handle.started:
            handle.task.cancel()
        return True

    async def cancel(self, run_id, reason="user") -> CancelResult:
        handle = self._active.get(run_id)
        accepted = self._request_cancel(handle) if handle is not None else False
        view = await self.get(run_id)
        return CancelResult(accepted, view.run.status, view.cancel_requested)

    async def _finish(self, handle, status, *, final_message=None, error=None):
        if handle.terminal is not None:
            return handle.terminal
        # No await between deciding the winner and registering the owned commit.
        if handle.finalizing is None:
            if handle.cancel_requested:
                status, final_message = "cancelled", None
            handle.finalizing = asyncio.create_task(
                self.store.finish_run(
                    handle.run_id,
                    status,
                    steps=handle.step,
                    final_message=final_message,
                    error=error,
                )
            )
        handle.terminal = await _wait_owned(handle.finalizing)
        return handle.terminal

    async def _execute(self, handle):
        handle.started = True
        try:
            if handle.cancel_requested:
                raise asyncio.CancelledError
            await self.store.start_run(handle.run_id)
            handle.publish("run.started", {})
            history = await self.store.load_history(
                handle.session_id, before_seq=handle.admission.user.seq
            )
            session = Session.restore(handle.session_id, [r.message for r in history])
            turn = PersistentTurn(session, self.store, handle, self)
            await self.agent.run(
                session, handle.admission.user.message.content, turn_io=turn, observer=handle
            )
        except asyncio.CancelledError:
            handle.cancel_requested = True
        except Exception:
            pass  # Finalization below records a safe error, never provider bodies.
        finally:
            if handle.terminal is None:
                try:
                    await self._finish(
                        handle,
                        "cancelled" if handle.cancel_requested else "failed",
                        error="当前Run未能完成。",
                    )
                except Exception:
                    handle.publish(
                        "service.error",
                        {"persisted": False, "code": "store_unwritable"},
                        terminal=True,
                    )
            if handle.terminal is not None:
                handle.publish(
                    f"run.{handle.terminal.status}",
                    {"persisted": True, "steps": handle.terminal.steps},
                    terminal=True,
                )
            self._release(handle)

    async def shutdown(self, *, grace_seconds=10.0):
        if (
            isinstance(grace_seconds, bool)
            or not isinstance(grace_seconds, (int, float))
            or not math.isfinite(grace_seconds)
            or not 0 < grace_seconds <= 600
        ):
            raise ValueError("Invalid shutdown timeout")
        if self._shutdown_task is None:
            self._stopping = True
            for handle in tuple(self._active.values()):
                self._request_cancel(handle)
            self._shutdown_task = asyncio.create_task(self._shutdown())
        try:
            async with asyncio.timeout(grace_seconds):
                await asyncio.shield(self._shutdown_task)
        except TimeoutError:
            raise StoreError("shutdown_timeout", "清理尚未结束，数据库仍由在途任务持有。") from None

    async def _shutdown(self):
        handles = tuple(self._active.values())
        for handle in handles:
            await handle.done.wait()
        await self.store.close()

    def _release(self, handle):
        self._active.pop(handle.run_id, None)
        self._sessions.discard(handle.session_id)
        handle.done.set()
