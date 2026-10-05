"""Narrow name-only adaptation for the observed Coding Runtime namespaces.

This module owns no HTTP, execution, scheduling or model policy. It preserves
native function schemas and argument strings. DeepSeek's Responses reference
requires unique ASCII function names of 1..128 characters (2026-10-05):
https://api-docs.deepseek.com/api/create-response/
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping


_NAMESPACES = frozenset({'multi_agent_v1', 'mcp__coding_readonly'})
_NAME = re.compile(r'[a-zA-Z0-9_-]+')


@dataclass(frozen=True)
class NamespaceMapping:
    """Only this request's advertised functions may appear in its response."""

    by_provider: Mapping[str, tuple[str | None, str]]


def _identity(value: dict, namespace: str | None = None):
    supplied = value.get('namespace')
    if supplied is not None:
        if namespace is not None and supplied != namespace:
            raise ValueError('conflicting tool namespace')
        namespace = supplied
    if namespace is not None and namespace not in _NAMESPACES:
        raise ValueError('unsupported tool namespace')
    name = value.get('name')
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('function name must contain only ASCII letters, digits, underscore or dash')
    flat = name if namespace is None else namespace + '__' + name
    if len(flat) > 128:
        raise ValueError('provider function name exceeds 128 characters')
    return flat, (namespace, name)


def provider_request(body: dict) -> tuple[dict, NamespaceMapping]:
    """Copy a Runtime Responses body, flatten declarations and call history.

    Historical calls may refer to tools no longer advertised (e.g. forked
    child history). They are renamed without granting them to the response.
    Collisions, including between historical and current identities, fail.
    """
    mapped = deepcopy(body)
    advertised, identities = {}, {}

    def rename(value, namespace=None, *, declaration=False):
        flat, identity = _identity(value, namespace)
        if flat in identities and identities[flat] != identity:
            raise ValueError('provider function name collision')
        if declaration and flat in advertised:
            raise ValueError('duplicate advertised function')
        identities[flat] = identity
        if declaration:
            advertised[flat] = identity
        value['name'] = flat
        value.pop('namespace', None)
        return value

    def declaration(tool, namespace=None):
        if not isinstance(tool, dict) or tool.get('type') != 'function':
            raise ValueError('only native function declarations are supported')
        return rename(tool, namespace, declaration=True)

    if mapped.get('tools') is not None:
        if not isinstance(mapped['tools'], list):
            raise ValueError('tools must be a list')
        flattened = []
        for tool in mapped['tools']:
            if isinstance(tool, dict) and tool.get('type') == 'namespace':
                namespace = tool.get('name')
                if namespace not in _NAMESPACES:
                    raise ValueError('unsupported tool namespace')
                children = tool.get('tools')
                if not isinstance(children, list):
                    raise ValueError('namespace tools must be a list')
                flattened.extend(declaration(child, namespace) for child in children)
            else:
                flattened.append(declaration(tool))
        mapped['tools'] = flattened

    inputs = mapped.get('input')
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, dict) and item.get('type') == 'function_call':
                rename(item)
    choice = mapped.get('tool_choice')
    if isinstance(choice, dict):
        if choice.get('type') != 'function':
            raise ValueError('unsupported named tool choice')
        rename(choice)
        if choice['name'] not in advertised:
            raise ValueError('tool choice was not advertised')
    return mapped, NamespaceMapping(MappingProxyType(advertised))


def runtime_event(event: dict, mapping: NamespaceMapping) -> dict:
    """Copy one parsed SSE JSON event, restoring only tool identity fields.

    Usage, IDs, argument deltas, output text and errors remain unchanged.
    This is not an SSE parser and does not execute or validate tool arguments.
    """
    restored = deepcopy(event)

    def restore_name(item):
        if item.get('namespace') is not None:
            raise ValueError('provider response must not inject a namespace')
        flat = item.get('name')
        if not isinstance(flat, str) or flat not in mapping.by_provider:
            raise ValueError('response function was not advertised')
        namespace, name = mapping.by_provider[flat]
        item['name'] = name
        if namespace is not None:
            item['namespace'] = namespace
        else:
            item.pop('namespace', None)

    def restore_item(item):
        if isinstance(item, dict):
            kind = item.get('type', '')
            if kind == 'function_call':
                restore_name(item)
            elif isinstance(kind, str) and kind.endswith('_call'):
                raise ValueError('response tool type was not advertised')

    if 'item' in restored:
        restore_item(restored['item'])
    response = restored.get('response')
    if isinstance(response, dict) and isinstance(response.get('output'), list):
        for item in response['output']:
            restore_item(item)
    if (restored.get('type') in {'response.function_call_arguments.done',
                                 'response.function_call_arguments.delta'} and 'name' in restored):
        restore_name(restored)
    return restored
