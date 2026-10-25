"""One bounded LangChain tool model, with durable decisions before graph checkpoints.

The graph owns decisions, this ledger owns paid attempts. An unfinished attempt
is never inferred to be safe to repeat, even after a process restart.
"""
import hashlib
import json
import os
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict
from langchain_deepseek import ChatDeepSeek
from openai import APIStatusError

from ..coding.responses_transport import CallBudget, encoded
from ..models import no_external_tracing


class ModelLimitError(RuntimeError):
    """A deterministic local limit prevented a new paid attempt."""


class ModelUnknownError(RuntimeError):
    """A decision cannot safely be executed or automatically repeated."""


def _error(kind, code):
    return kind(json.dumps({'code': code}, sort_keys=True))


class ToolModel:
    endpoint = 'https://api.deepseek.com/chat/completions'

    def __init__(self, root, grant, specs, api_key='', http_client=None):
        self.budget = CallBudget(Path(root), grant)
        self._key = api_key or os.environ.get('DEEPSEEK_API_KEY', '')
        # Keep redirects and ambient proxy routing out of the fixed authorization.
        self._http = http_client if http_client is not None else httpx.Client(
            timeout=90, follow_redirects=False, trust_env=False)
        if self._http.follow_redirects:
            raise ValueError('model HTTP redirects must be disabled')
        self._chat = ChatDeepSeek(
            model='deepseek-flash', api_key=self._key or 'offline-preview-only',
            base_url='https://api.deepseek.com', max_tokens=grant['max_output_tokens'],
            max_retries=0, timeout=90, temperature=0, cache=False,
            http_client=self._http, extra_body={'thinking': {'type': 'disabled'}},
            use_responses_api=False,
        )
        schemas = [{'type': 'function', 'function': {
            'name': spec['name'], 'description': spec['description'],
            'parameters': spec['inputSchema'],
        }} for spec in specs]
        self._tools = self._chat.bind_tools(schemas, parallel_tool_calls=False) if schemas else self._chat
        with self.budget._db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS model_decisions ('
                         'decision_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, '
                         'state TEXT NOT NULL, call_id INTEGER, response TEXT, error_code TEXT)')

    def remaining_calls(self):
        summary = self.budget.summary()
        return max(0, summary['max_calls'] - summary['reserved'])

    def summary(self):
        return self.budget.summary()

    def close(self):
        self._http.close()

    def _redact(self, value):
        raw = encoded(value).decode('utf-8')
        if self._key:
            # Redact at the serialized boundary, including provider metadata.
            raw = raw.replace(json.dumps(self._key, ensure_ascii=False)[1:-1], '[REDACTED]')
        return json.loads(raw)

    def _save(self, decision_id, state, *, response=None, error_code=None):
        with self.budget._db() as conn:
            conn.execute('UPDATE model_decisions SET state=?,response=?,error_code=? WHERE decision_id=?',
                         (state, encoded(response).decode() if response is not None else None,
                          error_code, decision_id))

    def _usage(self, message):
        usage = message.usage_metadata
        if usage is None:
            return None
        return {'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
                'input_tokens_details': {'cached_tokens': usage.get('input_token_details', {}).get('cache_read', 0)}}

    def _settle(self, decision_id, call_id, stored, code):
        """Settle a saved response without ever reissuing its HTTP request."""
        message = messages_from_dict([stored])[0]
        try:
            usage = self._usage(message)
            with self.budget._db() as conn:
                call = conn.execute('SELECT state FROM calls WHERE id=?', (call_id,)).fetchone()
            if call is None:
                raise ValueError('missing reservation')
            if call['state'] == 'reserved':
                self.budget.finish(call_id, 'failed' if code else 'completed', usage)
        except (TypeError, ValueError, KeyError):
            self._save(decision_id, 'unknown', response=stored, error_code='invalid_model_usage')
            raise _error(ModelUnknownError, 'invalid_model_usage') from None
        self._save(decision_id, 'failed' if code else 'completed', response=stored, error_code=code)
        if code:
            raise _error(ModelUnknownError, code)
        return message

    def complete(self, messages: list[BaseMessage], decision_id: str, final_only=False) -> AIMessage:
        if not isinstance(decision_id, str) or not decision_id or len(decision_id) > 250:
            raise _error(ModelUnknownError, 'invalid_decision_id')
        if self._key and self._key in decision_id:
            raise _error(ModelUnknownError, 'invalid_decision_id')
        if not isinstance(messages, list) or not messages or any(not isinstance(m, BaseMessage) for m in messages):
            raise _error(ModelUnknownError, 'invalid_model_messages')
        bound = self._chat if final_only else self._tools
        kwargs = getattr(bound, 'kwargs', {})
        try:
            payload = self._chat._get_request_payload(messages, **kwargs)
            payload.update(payload.pop('extra_body', {}))
            raw = encoded(payload)
        except Exception:
            raise _error(ModelUnknownError, 'invalid_model_request') from None
        request_hash = hashlib.sha256(raw).hexdigest()
        # Check replay before current limits: completed decisions remain readable.
        with self.budget._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM model_decisions WHERE decision_id=?', (decision_id,)).fetchone()
            if row:
                if row['request_hash'] != request_hash:
                    raise _error(ModelUnknownError, 'decision_request_changed')
                if row['state'] == 'completed':
                    return messages_from_dict([json.loads(row['response'])])[0]
                if row['state'] != 'received':
                    error_type = ModelLimitError if row['state'] == 'rejected' else ModelUnknownError
                    raise _error(error_type, row['error_code'] or 'model_call_unknown')
            else:
                if len(raw) > self.budget.grant['max_input_bytes']:
                    raise _error(ModelLimitError, 'input_size_exceeded')
                if not self._key:
                    raise _error(ModelUnknownError, 'model_key_missing')
                conn.execute('INSERT INTO model_decisions(decision_id,request_hash,state) VALUES (?,?,?)',
                             (decision_id, request_hash, 'reserved'))
        if row:
            return self._settle(decision_id, row['call_id'], json.loads(row['response']), row['error_code'])
        # A crash on either side of this reservation cannot authorize a resend.
        try:
            call_id = self.budget.reserve(payload)
        except ValueError:
            self._save(decision_id, 'rejected', error_code='call_budget_exhausted')
            raise _error(ModelLimitError, 'call_budget_exhausted') from None
        with self.budget._db() as conn:
            conn.execute('UPDATE model_decisions SET call_id=? WHERE decision_id=?', (call_id, decision_id))
        try:
            with no_external_tracing():
                message = bound.invoke(messages, config={'callbacks': []})
        except Exception as exc:
            code = 'model_call_failed' if isinstance(exc, APIStatusError) else 'model_call_unknown'
            self.budget.finish(call_id, 'failed', None)
            self._save(decision_id, 'failed' if isinstance(exc, APIStatusError) else 'unknown', error_code=code)
            raise _error(ModelUnknownError, code) from None
        if not isinstance(message, AIMessage):
            self.budget.finish(call_id, 'failed', None)
            self._save(decision_id, 'failed', error_code='invalid_model_response')
            raise _error(ModelUnknownError, 'invalid_model_response')
        # Normalize and persist the actual LangChain message before returning to
        # the graph. Metadata and tool arguments participate in credential redaction.
        stored = self._redact(message_to_dict(message))
        message = messages_from_dict([stored])[0]
        code = ('unexpected_final_tool_call' if final_only and (message.tool_calls or message.invalid_tool_calls)
                else 'invalid_tool_call' if message.invalid_tool_calls else None)
        self._save(decision_id, 'received', response=stored, error_code=code)
        return self._settle(decision_id, call_id, stored, code)
