# confirm03 — SSE背压及取消清理评审

候选简化了SSE内存队列和持久化清理等待。请审查消费者变慢、断线以及取消到达提交阶段时，是否仍保持有界背压与清理任务所有权。仅讨论给定单进程服务实现，不假设多worker部署。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. EventQueue在项数或字节数达到上限时等待空间，消费者取出事件后必须唤醒等待的生产者；队列清空不代表Run已终止。
2. 调用者取消可以停止业务推理，但已经由服务持有的持久化收尾任务不能被调用者取消；_wait_owned必须等待它结束并取回结果。
3. RunHandle.emit发生背压超时会标记cancel_requested并抛CancelledError；不能用超时退出把丢失唤醒当作正常行为。
4. 只需审查冻结候选这两段修改引发的行为；不要求新增SSE断线续传、持久事件日志或改变POST拥有Run的设计。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/herta-agent-coding/backend/herta_agent/service/events.py
+++ b/herta-agent-coding/backend/herta_agent/service/events.py
@@ -64,7 +64,6 @@
     def get_nowait(self):
         item = super().get_nowait()
         self._bytes -= self._sizes.popleft()
-        self._space.set()
         return item
 
     async def put(self, item):
--- a/herta-agent-coding/backend/herta_agent/service/runs.py
+++ b/herta-agent-coding/backend/herta_agent/service/runs.py
@@ -99,7 +99,7 @@
     """Internal cleanup retains ownership despite repeated caller cancellation."""
     while not task.done():
         try:
-            await asyncio.shield(task)
+            await task
         except asyncio.CancelledError:
             continue
     return task.result()
```


## 相关源码
以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。

### herta-agent-coding/backend/herta_agent/service/events.py:1-106
```python
0001 | """Versioned SSE representation and bounded, transient event buffering."""
0002 | 
0003 | import asyncio
0004 | import json
0005 | from collections import deque
0006 | from typing import Literal
0007 | 
0008 | from pydantic import BaseModel, ConfigDict, Field, JsonValue
0009 | 
0010 | MAX_EVENT_BYTES = 256 * 1024
0011 | MAX_BUFFER_BYTES = 2 * 1024 * 1024
0012 | 
0013 | 
0014 | class ServiceEvent(BaseModel):
0015 |     model_config = ConfigDict(extra="forbid", strict=True)
0016 |     schema_version: Literal[1] = 1
0017 |     type: Literal[
0018 |         "run.started",
0019 |         "run.completed",
0020 |         "run.failed",
0021 |         "run.cancelled",
0022 |         "llm.started",
0023 |         "llm.delta",
0024 |         "llm.completed",
0025 |         "tool.started",
0026 |         "tool.completed",
0027 |         "tool.failed",
0028 |         "rag.retrieved",
0029 |         "service.error",
0030 |     ]
0031 |     session_id: str = Field(pattern=r"^[^\r\n]+$")
0032 |     run_id: str = Field(pattern=r"^[^\r\n]+$")
0033 |     seq: int = Field(ge=1)
0034 |     timestamp: str
0035 |     payload: dict[str, JsonValue]
0036 | 
0037 | 
0038 | def encode_event(event) -> bytes:
0039 |     value = ServiceEvent.model_validate(event).model_dump()
0040 |     data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
0041 |     encoded = (
0042 |         f"id: {value['run_id']}:{value['seq']}\nevent: {value['type']}\ndata: {data}\n\n".encode()
0043 |     )
0044 |     if len(encoded) > MAX_EVENT_BYTES:
0045 |         raise ValueError("Service event exceeds size limit")
0046 |     return encoded
0047 | 
0048 | 
0049 | class EventQueue(asyncio.Queue):
0050 |     def __init__(self):
0051 |         super().__init__(maxsize=128)
0052 |         self._sizes = deque()
0053 |         self._bytes = 0
0054 |         self._space = asyncio.Event()
0055 | 
0056 |     def put_nowait(self, item):
0057 |         size = len(encode_event(item))
0058 |         if self._bytes + size > MAX_BUFFER_BYTES:
0059 |             raise asyncio.QueueFull
0060 |         super().put_nowait(item)
0061 |         self._sizes.append(size)
0062 |         self._bytes += size
0063 | 
0064 |     def get_nowait(self):
0065 |         item = super().get_nowait()
0066 |         self._bytes -= self._sizes.popleft()
0067 |         return item
0068 | 
0069 |     async def put(self, item):
0070 |         while True:
0071 |             try:
0072 |                 self.put_nowait(item)
0073 |                 return
0074 |             except asyncio.QueueFull:
0075 |                 self._space.clear()
0076 |                 await self._space.wait()
0077 | 
0078 | 
0079 | def adapt_runtime(event):
0080 |     payload = {
0081 |         "step": event.step,
0082 |         "message_id": event.message_id,
0083 |         "tool_call_id": event.tool_call_id,
0084 |         **event.payload,
0085 |     }
0086 |     yield event.type, payload
0087 |     result = event.payload.get("result", {})
0088 |     if (
0089 |         event.type == "tool.completed"
0090 |         and event.payload.get("name") == "search_knowledge"
0091 |         and result.get("ok") is True
0092 |     ):
0093 |         data = result["data"]
0094 |         yield (
0095 |             "rag.retrieved",
0096 |             {
0097 |                 "step": event.step,
0098 |                 "tool_call_id": event.tool_call_id,
0099 |                 "query": data.get("query"),
0100 |                 "index_id": data.get("index_id"),
0101 |                 "chunks": [
0102 |                     {key: chunk.get(key) for key in ("id", "source", "source_spans", "score")}
0103 |                     for chunk in data.get("chunks", [])
0104 |                 ],
0105 |             },
0106 |         )
```

### herta-agent-coding/backend/herta_agent/service/runs.py:30-116
```python
0030 | 
0031 | 
0032 | @dataclass
0033 | class RunHandle:
0034 |     run_id: str
0035 |     session_id: str
0036 |     events: EventQueue = field(default_factory=EventQueue)
0037 |     event_wait_seconds: float = 2.0
0038 |     done: asyncio.Event = field(default_factory=asyncio.Event)
0039 |     task: asyncio.Task | None = None
0040 |     admitting: asyncio.Task | None = None
0041 |     finalizing: asyncio.Task | None = None
0042 |     started: bool = False
0043 |     admission: Admission | None = None
0044 |     terminal: RunRecord | None = None
0045 |     cancel_requested: bool = False
0046 |     step: int = 0
0047 |     seq: int = 0
0048 | 
0049 |     def _event(self, type, payload):
0050 |         self.seq += 1
0051 |         return {
0052 |             "type": type,
0053 |             "session_id": self.session_id,
0054 |             "run_id": self.run_id,
0055 |             "seq": self.seq,
0056 |             "timestamp": datetime.now(UTC).isoformat(),
0057 |             "schema_version": 1,
0058 |             "payload": payload,
0059 |         }
0060 | 
0061 |     def publish(self, type, payload, *, terminal=False):
0062 |         event = self._event(type, payload)
0063 |         while True:
0064 |             try:
0065 |                 self.events.put_nowait(event)
0066 |                 return
0067 |             except asyncio.QueueFull:
0068 |                 if not terminal:
0069 |                     raise
0070 |                 self.events.get_nowait()  # Cleanup never waits for a consumer.
0071 | 
0072 |     async def emit(self, event):
0073 |         if self.cancel_requested:
0074 |             raise asyncio.CancelledError
0075 |         self.step = event.step
0076 |         try:
0077 |             for type, payload in adapt_runtime(event):
0078 |                 async with asyncio.timeout(self.event_wait_seconds):
0079 |                     await self.events.put(self._event(type, payload))
0080 |         except (TimeoutError, ValueError):
0081 |             self.cancel_requested = True
0082 |             raise asyncio.CancelledError from None
0083 | 
0084 | 
0085 | @dataclass(frozen=True)
0086 | class RunView:
0087 |     run: RunRecord
0088 |     cancel_requested: bool
0089 | 
0090 | 
0091 | @dataclass(frozen=True)
0092 | class CancelResult:
0093 |     accepted: bool
0094 |     status: str
0095 |     cancel_requested: bool
0096 | 
0097 | 
0098 | async def _wait_owned(task):
0099 |     """Internal cleanup retains ownership despite repeated caller cancellation."""
0100 |     while not task.done():
0101 |         try:
0102 |             await task
0103 |         except asyncio.CancelledError:
0104 |             continue
0105 |     return task.result()
0106 | 
0107 | 
0108 | class RunManager:
0109 |     def __init__(self, store, agent, settings: ServiceSettings | None = None, *, model=None):
0110 |         self.store, self.agent = store, agent
0111 |         self.settings = settings or ServiceSettings()
0112 |         model = model or getattr(
0113 |             getattr(agent.provider, "settings", None), "model", type(agent.provider).__name__
0114 |         )
0115 |         self.config = RunConfig(model=model, settings=agent.settings)
0116 |         self._active: dict[str, RunHandle] = {}
```

### herta-agent-coding/backend/herta_agent/service/runs.py:205-289
```python
0205 |         if handle.finalizing is None:
0206 |             if handle.cancel_requested:
0207 |                 status, final_message = "cancelled", None
0208 |             handle.finalizing = asyncio.create_task(
0209 |                 self.store.finish_run(
0210 |                     handle.run_id,
0211 |                     status,
0212 |                     steps=handle.step,
0213 |                     final_message=final_message,
0214 |                     error=error,
0215 |                 )
0216 |             )
0217 |         handle.terminal = await _wait_owned(handle.finalizing)
0218 |         return handle.terminal
0219 | 
0220 |     async def _execute(self, handle):
0221 |         handle.started = True
0222 |         try:
0223 |             if handle.cancel_requested:
0224 |                 raise asyncio.CancelledError
0225 |             await self.store.start_run(handle.run_id)
0226 |             handle.publish("run.started", {})
0227 |             history = await self.store.load_history(
0228 |                 handle.session_id, before_seq=handle.admission.user.seq
0229 |             )
0230 |             session = Session.restore(handle.session_id, [r.message for r in history])
0231 |             turn = PersistentTurn(session, self.store, handle, self)
0232 |             await self.agent.run(
0233 |                 session, handle.admission.user.message.content, turn_io=turn, observer=handle
0234 |             )
0235 |         except asyncio.CancelledError:
0236 |             handle.cancel_requested = True
0237 |         except Exception:
0238 |             pass  # Finalization below records a safe error, never provider bodies.
0239 |         finally:
0240 |             if handle.terminal is None:
0241 |                 try:
0242 |                     await self._finish(
0243 |                         handle,
0244 |                         "cancelled" if handle.cancel_requested else "failed",
0245 |                         error="当前Run未能完成。",
0246 |                     )
0247 |                 except Exception:
0248 |                     handle.publish(
0249 |                         "service.error",
0250 |                         {"persisted": False, "code": "store_unwritable"},
0251 |                         terminal=True,
0252 |                     )
0253 |             if handle.terminal is not None:
0254 |                 handle.publish(
0255 |                     f"run.{handle.terminal.status}",
0256 |                     {"persisted": True, "steps": handle.terminal.steps},
0257 |                     terminal=True,
0258 |                 )
0259 |             self._release(handle)
0260 | 
0261 |     async def shutdown(self, *, grace_seconds=10.0):
0262 |         if (
0263 |             isinstance(grace_seconds, bool)
0264 |             or not isinstance(grace_seconds, (int, float))
0265 |             or not math.isfinite(grace_seconds)
0266 |             or not 0 < grace_seconds <= 600
0267 |         ):
0268 |             raise ValueError("Invalid shutdown timeout")
0269 |         if self._shutdown_task is None:
0270 |             self._stopping = True
0271 |             for handle in tuple(self._active.values()):
0272 |                 self._request_cancel(handle)
0273 |             self._shutdown_task = asyncio.create_task(self._shutdown())
0274 |         try:
0275 |             async with asyncio.timeout(grace_seconds):
0276 |                 await asyncio.shield(self._shutdown_task)
0277 |         except TimeoutError:
0278 |             raise StoreError("shutdown_timeout", "清理尚未结束，数据库仍由在途任务持有。") from None
0279 | 
0280 |     async def _shutdown(self):
0281 |         handles = tuple(self._active.values())
0282 |         for handle in handles:
0283 |             await handle.done.wait()
0284 |         await self.store.close()
0285 | 
0286 |     def _release(self, handle):
0287 |         self._active.pop(handle.run_id, None)
0288 |         self._sessions.discard(handle.session_id)
0289 |         handle.done.set()
```

### herta-agent-coding/backend/herta_agent/service/sse.py:1-85
```python
0001 | """A POST response owns admission and observes disconnect before any headers."""
0002 | 
0003 | import asyncio
0004 | 
0005 | from starlette.responses import Response
0006 | 
0007 | from herta_agent.service.events import encode_event
0008 | from herta_agent.service.runs import _wait_owned
0009 | 
0010 | 
0011 | class RunResponse(Response):
0012 |     def __init__(self, manager, session_id, text, settings):
0013 |         super().__init__(media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
0014 |         self.raw_headers = [
0015 |             (key, value) for key, value in self.raw_headers if key != b"content-length"
0016 |         ]
0017 |         self.manager, self.session_id, self.text = manager, session_id, text
0018 |         self.settings, self.handle = settings, None
0019 | 
0020 |     async def __call__(self, scope, receive, send):
0021 |         serving = asyncio.create_task(self._serve(send))
0022 |         disconnected = asyncio.create_task(self._disconnect(receive))
0023 |         try:
0024 |             finished, _ = await asyncio.wait(
0025 |                 (serving, disconnected), return_when=asyncio.FIRST_COMPLETED
0026 |             )
0027 |             if serving in finished:
0028 |                 await serving
0029 |         finally:
0030 |             cleanup = asyncio.create_task(self._cleanup(serving, disconnected))
0031 |             await _wait_owned(cleanup)
0032 | 
0033 |     async def _cleanup(self, serving, disconnected):
0034 |         serving.cancel()
0035 |         disconnected.cancel()
0036 |         await asyncio.gather(serving, disconnected, return_exceptions=True)
0037 |         if self.handle is not None:
0038 |             await self.manager.cancel(self.handle.run_id, "disconnect")
0039 | 
0040 |     async def _disconnect(self, receive):
0041 |         while (await receive())["type"] != "http.disconnect":
0042 |             pass
0043 | 
0044 |     async def _send(self, send, message):
0045 |         async with asyncio.timeout(self.settings.send_wait_seconds):
0046 |             await send(message)
0047 | 
0048 |     async def _serve(self, send):
0049 |         self.handle = await self.manager.submit(self.session_id, self.text)
0050 |         try:
0051 |             await self._send(
0052 |                 send, {"type": "http.response.start", "status": 200, "headers": self.raw_headers}
0053 |             )
0054 |             while True:
0055 |                 try:
0056 |                     async with asyncio.timeout(self.settings.heartbeat_seconds):
0057 |                         event = await self.handle.events.get()
0058 |                 except TimeoutError:
0059 |                     if self.handle.done.is_set():
0060 |                         break
0061 |                     await self._send(
0062 |                         send,
0063 |                         {
0064 |                             "type": "http.response.body",
0065 |                             "body": b": heartbeat\n\n",
0066 |                             "more_body": True,
0067 |                         },
0068 |                     )
0069 |                     continue
0070 |                 if self.handle.cancel_requested and event["type"] == "llm.delta":
0071 |                     continue  # Buffered partial has not yet reached the transport.
0072 |                 await self._send(
0073 |                     send,
0074 |                     {"type": "http.response.body", "body": encode_event(event), "more_body": True},
0075 |                 )
0076 |                 if event["type"] in {
0077 |                     "run.completed",
0078 |                     "run.failed",
0079 |                     "run.cancelled",
0080 |                     "service.error",
0081 |                 }:
0082 |                     break
0083 |             await self._send(send, {"type": "http.response.body", "body": b"", "more_body": False})
0084 |         except (TimeoutError, OSError):
0085 |             pass  # A stalled/closed transport cancels its owner in response cleanup.
```
