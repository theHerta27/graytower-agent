"""Strict HTTP request contracts; domain validation remains in the services."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class TaskCreate(Input):
    project: str = Field(min_length=1)
    request: str = Field(min_length=1, max_length=8000)
    knowledge_mode: Literal['lexical', 'off'] = 'lexical'

    @field_validator('project', 'request')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('must not be blank')
        return value


class EmptyInput(Input):
    pass


class CheckInput(Input):
    check_set: str


class RunInput(Input):
    run_id: str
    scope_sha256: str
    accept_data: bool
    accept_cost: bool


class ResumeInput(Input):
    run_id: str
    scope_sha256: str
    answer: str | None = None


class EditInput(Input):
    operation_id: str
    path: str
    expected_sha256: str
    content: str


class TreeInput(Input):
    tree_hash: str


class RestoreInput(Input):
    operation_id: str


class DeliveryPrepare(Input):
    kind: str
    operation_id: str | None = None


class DeliveryInput(Input):
    preparation_id: str


class DeliveryApprove(DeliveryInput):
    approval_hash: str


class DeliveryDiscard(DeliveryInput):
    cleanup_hash: str


class KnowledgeSearch(Input):
    query: str


class KnowledgeImport(Input):
    action: Literal['import']
    path: str
    headings: list[str] | None = None


class KnowledgeStatus(Input):
    action: Literal['status']
    id: str
    status: str


class KnowledgeDelete(Input):
    action: Literal['delete']
    id: str


KnowledgeMutation = Annotated[
    KnowledgeImport | KnowledgeStatus | KnowledgeDelete,
    Field(discriminator='action'),
]


class MemoryAdd(Input):
    action: Literal['add']
    content: str
    version: str
    kind: str | None = None


class MemoryUpdate(Input):
    action: Literal['update']
    id: str
    content: str | None = None
    version: str | None = None
    kind: str | None = None
    status: str | None = None


class MemoryDelete(Input):
    action: Literal['delete']
    id: str


MemoryMutation = Annotated[
    MemoryAdd | MemoryUpdate | MemoryDelete,
    Field(discriminator='action'),
]
