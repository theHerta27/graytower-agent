"""Bounded, auditable DeepSeek LangChain calls shared by product agents.

The JSONL ledger is append-only. A reserved call consumes the cap even when the
process dies before recording a response. This is a local single-host gateway;
it does not infer monetary cost from token counts or retry provider failures.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from langchain_deepseek import ChatDeepSeek
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.messages import convert_to_messages
from langchain_core.tracers.context import tracing_v2_callback_var
from langsmith import tracing_context
from openai import ContentFilterFinishReasonError, LengthFinishReasonError
from pydantic import BaseModel, ValidationError


class ModelResponseError(RuntimeError):
    """A provider response arrived but failed the required output schema."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _one_json_object(content: str) -> dict:
    """Never repair truncation, strip prose, ignore duplicate keys or take a prefix."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError('non-finite JSON number')

    def finite_float(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError('non-finite JSON number')
        return number

    try:
        value = json.loads(content, object_pairs_hook=object_pairs,
                           parse_constant=reject_constant, parse_float=finite_float)
        if not isinstance(value, dict):
            raise ValueError('decision must be an object')
        return value
    except (ValueError, TypeError) as exc:
        raise ModelResponseError('expected exactly one complete JSON object') from exc


@contextmanager
def no_external_tracing():
    """Keep project content out of ambient LangSmith callbacks on this driver.

    Context overrides are essential: environment flags alone do not override an
    already-active trace. Product entrypoints also use this around the root graph.
    The application is single-driver; original environment values are restored.
    """
    names = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_HANDLER")
    previous = {name: os.environ.get(name) for name in names}
    token = tracing_v2_callback_var.set(None)
    try:
        for name in names:
            os.environ[name] = "false"
        with tracing_context(enabled=False, parent=False):
            yield
    finally:
        tracing_v2_callback_var.reset(token)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class ModelGateway:
    """Only DeepSeek; no fallback, no hidden retry, persistent call reservations.

    ``http_client`` exists for caller-owned connection lifecycle and offline
    transport testing. It never changes the fixed DeepSeek endpoint. ``preview``
    requires no credential and sends no request. ``complete`` requires an audit
    path and obtains its credential only from its argument or DEEPSEEK_API_KEY.
    """

    endpoint = "https://api.deepseek.com"

    def __init__(self, *, api_key: str | None = None, model: str = "deepseek-flash",
                 max_calls: int = 4, max_input_chars: int = 100_000,
                 max_output_tokens: int = 1500, timeout: float = 60,
                 audit_path: Path | None = None, http_client=None,
                 output_method: str = 'json_mode'):
        if model not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise ValueError("unsupported explicit DeepSeek model")
        for name, value in (("max_calls", max_calls), ("max_input_chars", max_input_chars),
                            ("max_output_tokens", max_output_tokens)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 < timeout <= 300:
            raise ValueError("timeout must be in (0, 300]")
        if output_method not in {'json_mode', 'function_calling'}:
            raise ValueError('unsupported explicit structured output method')
        self.model = model
        self.max_calls = max_calls
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.output_method = output_method
        self.audit_path = Path(audit_path) if audit_path is not None else None
        self._api_key = api_key
        self._http_client = http_client
        self.calls: list[dict] = []

    def _chat(self, api_key: str):
        kwargs = dict(api_key=api_key, model=self.model, base_url=self.endpoint,
                      max_tokens=self.max_output_tokens, max_retries=0,
                      timeout=self.timeout, temperature=0,
                      extra_body={"thinking": {"type": "disabled"}})
        if self._http_client is not None:
            kwargs["http_client"] = self._http_client
        return ChatDeepSeek(**kwargs)

    def preview(self, messages: list[dict], schema: type[BaseModel]) -> dict:
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ValueError("schema must be a Pydantic model class")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list")
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in {"system", "user", "assistant"}
                    or not isinstance(message["content"], str)):
                raise ValueError("only explicit text messages are supported")
        # Mirror the pinned LangChain binding. Offline HTTP tests compare the
        # entire wire payload; preview and invocation share the prepared messages.
        chat = self._chat("preview-only-not-a-credential")
        prepared_messages = deepcopy(messages)
        if self.output_method == 'json_mode':
            prepared_messages.insert(0, {'role': 'system', 'content': (
                'Return exactly one complete JSON object matching the JSON Schema below. '
                'Do not return an array, multiple decisions, Markdown or text outside the object. '
                'Choose only the next decision; execution is handled by the application.\n'
                + _json(schema.model_json_schema()))})
            bound = chat.bind(response_format={'type': 'json_object'})
        else:
            tool_name = convert_to_openai_tool(schema)["function"]["name"]
            bound = chat.bind_tools([schema], tool_choice=tool_name, parallel_tool_calls=False)
        payload = chat._get_request_payload(prepared_messages, **bound.kwargs)
        # openai merges extra_body into the HTTP JSON body before transport.
        payload.update(payload.pop("extra_body", {}))
        input_chars = len(_json({name: payload[name] for name in ('messages', 'tools') if name in payload}))
        if input_chars > self.max_input_chars:
            raise ValueError(f"model input exceeds {self.max_input_chars} character limit")
        return {"provider": "deepseek", "endpoint": self.endpoint + "/chat/completions",
                "payload": payload, "input_chars": input_chars,
                "max_input_chars": self.max_input_chars, "max_calls": self.max_calls,
                "max_output_tokens": self.max_output_tokens,
                "output_method": self.output_method,
                "schema": schema.model_json_schema()}

    @contextmanager
    def _audit_lock(self):
        if self.audit_path is None:
            raise RuntimeError("persistent audit_path is required for model calls")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.with_suffix(self.audit_path.suffix + ".lock").open("a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _append(self, record: dict):
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.calls.append(record)

    def _safe(self, value: Any, key: str):
        if isinstance(value, dict):
            return {name: self._safe(item, key) for name, item in value.items()
                    if str(name).lower() not in {"api_key", "authorization", "headers", "request", "response"}}
        if isinstance(value, (tuple, list)):
            return [self._safe(item, key) for item in value]
        if isinstance(value, str):
            value = value.replace(key, "[REDACTED]") if key else value
            return re.sub(r"(?i)\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{6,}", "[REDACTED]", value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return type(value).__name__

    def remaining_calls(self) -> int:
        """Read a budget snapshot without creating files or reserving a call.

        Unknown/failed calls remain charged. complete() checks this same ledger
        again under its local lock before adding a reservation.
        """
        if self.audit_path is None:
            raise RuntimeError("persistent audit_path is required for model budget")
        try:
            raw = self.audit_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self.max_calls
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("model audit ledger unreadable; refusing a new call") from exc
        states = {}
        try:
            for line in raw.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if (not isinstance(item, dict) or not isinstance(item.get("call_id"), str)
                        or not item["call_id"].strip() or item.get("status") not in {"reserved", "completed", "failed"}):
                    raise ValueError("invalid model audit record")
                call_id, status = item["call_id"], item["status"]
                if ((status == "reserved" and call_id in states)
                        or (status != "reserved" and states.get(call_id) != "reserved")):
                    raise ValueError("invalid model audit lifecycle")
                states[call_id] = status
        except (ValueError, TypeError) as exc:
            raise RuntimeError("model audit ledger invalid; refusing a new call") from exc
        return max(0, self.max_calls - len(states))

    def complete(self, messages: list[dict], schema: type[BaseModel]) -> dict:
        preview = self.preview(messages, schema)
        key = self._api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is required; no provider fallback")
        chat = self._chat(key)
        record = {"call_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
                  "provider": "deepseek", "model": self.model,
                  "output_method": self.output_method,
                  "payload_hash": hashlib.sha256(_json(preview["payload"]).encode()).hexdigest(),
                  "preview": self._safe(preview, key), "status": "reserved",
                  "usage": None, "elapsed_seconds": None, "error": None, "raw": None}
        with self._audit_lock():
            if self.remaining_calls() == 0:
                raise RuntimeError("persistent model call limit exhausted")
            self._append(deepcopy(record))
        started = time.monotonic()
        try:
            interrupted_response = False
            with no_external_tracing():
                try:
                    # generate preserves every completion choice; invoke and
                    # structured wrappers otherwise expose only the first one.
                    binding = {name: preview['payload'][name] for name in
                               ('tools', 'tool_choice', 'parallel_tool_calls', 'response_format')
                               if name in preview['payload']}
                    result = chat.generate([convert_to_messages(preview['payload']['messages'])],
                                           callbacks=[], **binding)
                    generations = result.generations[0]
                except (LengthFinishReasonError, ContentFilterFinishReasonError) as exc:
                    # The SDK's JSON parse endpoint raises before LangChain can
                    # return raw. Keep the paid completion's usage and content;
                    # the terminal-state guard below still rejects the decision.
                    if exc.completion is None:
                        raise ModelResponseError('incomplete provider decision') from exc
                    result = chat._create_chat_result(exc.completion)
                    generations = result.generations
                    interrupted_response = True
                    for generation in generations:
                        generation.message.response_metadata.update(result.llm_output or {})
                        generation.message.response_metadata.update(generation.generation_info or {})
            raw = generations[0].message if generations else None
            if len(generations) != 1:
                record['raw_choices'] = self._safe([
                    {'content': g.message.content, 'tool_calls': g.message.tool_calls,
                     'invalid_tool_calls': g.message.invalid_tool_calls,
                     'finish_reason': g.message.response_metadata.get('finish_reason')}
                    for g in generations], key)
            if raw is not None:
                record["usage"] = self._safe(getattr(raw, "usage_metadata", None), key)
                metadata = getattr(raw, "response_metadata", {})
                record["actual_model"] = metadata.get("model_name", metadata.get("model", self.model))
                record["raw"] = self._safe({"content": raw.content, "tool_calls": raw.tool_calls,
                    "invalid_tool_calls": raw.invalid_tool_calls,
                    "finish_reason": metadata.get("finish_reason"),
                    "reasoning_content": getattr(raw, "additional_kwargs", {}).get("reasoning_content")}, key)
            if interrupted_response or len(generations) != 1:
                raise ModelResponseError('expected one completed response choice')
            if self.output_method == 'json_mode':
                if (raw is None or raw.tool_calls or raw.invalid_tool_calls
                        or raw.response_metadata.get('finish_reason') != 'stop'
                        or not isinstance(raw.content, str)):
                    raise ModelResponseError('expected a completed JSON decision without tool calls')
                # LangChain's JSON parser repairs partial JSON and can select a
                # prefix. Validate the complete raw content instead of `parsed`.
                parsed = _one_json_object(raw.content)
            else:
                expected_name = convert_to_openai_tool(schema)["function"]["name"]
                if (raw is None or len(raw.tool_calls) != 1 or raw.invalid_tool_calls
                        or raw.tool_calls[0].get("name") != expected_name
                        or raw.response_metadata.get('finish_reason') != 'tool_calls'):
                    raise ModelResponseError("expected exactly one structured decision")
                parsed = raw.tool_calls[0]['args']
            try:
                answer = schema.model_validate(parsed, strict=True).model_dump(mode="json")
            except ValidationError as exc:
                raise ModelResponseError('decision schema invalid') from exc
            record["status"] = "completed"
            return answer
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = {"type": type(exc).__name__,
                               "message": "structured output invalid" if isinstance(exc, ModelResponseError) else "provider call failed"}
            if isinstance(exc, ModelResponseError):
                raise ModelResponseError("provider response failed structured output validation") from None
            raise RuntimeError("DeepSeek provider call failed; inspect the safe audit record") from None
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 6)
            with self._audit_lock():
                self._append(self._safe(record, key))


DeepSeekModelGateway = ModelGateway
