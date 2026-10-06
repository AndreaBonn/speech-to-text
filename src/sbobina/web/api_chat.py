"""CRUD and messaging for course chat conversations (T042, ADR D5).

Course-key resolution mirrors api_generations.py; one chat turn lives in
chat_turn.py. ``app.state.chat_client``, when set, replaces the production
Ollama client: tests set it to a scripted model instead of calling Ollama.
"""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from ollama import Client
from pydantic import BaseModel, Field
from starlette.responses import Response

from sbobina import llm_factory
from sbobina.chat_pipeline import ChatClient
from sbobina.course_registry import find_by_key
from sbobina.courses import course_key
from sbobina.ollama_chat import ChatRequest, chat_json
from sbobina.settings import Settings
from sbobina.web.chat_records import (
    ChatAnswerRecord,
    ChatMeta,
    ChatQuestionRecord,
    ChatRecord,
)
from sbobina.web.chat_store import (
    chat_meta,
    create_chat,
    delete_chat,
    list_chats,
    load_records,
)
from sbobina.web.chat_turn import ChatLocation, ChatServices, ask
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_citations_api import CitationContext, resolve_citation

router = APIRouter(prefix="/api/v1/courses")

MAX_QUESTION_CHARS = 1000


class ChatMessageBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def _settings_fingerprint(settings: Settings) -> tuple[object, ...]:
    """What `_chat_client` must rebuild on: a settings change otherwise keeps
    serving a cached chain whose breaker state (and provider keys) are stale."""
    keys = llm_factory.keys_from_settings(settings=settings)
    return (
        settings.llm_engine,
        tuple((entry.provider, entry.model) for entry in settings.llm_chain),
        settings.llm_ollama_fallback,
        settings.ollama_model,
        frozenset(keys),
    )


def _build_local_client(settings: Settings) -> ChatClient:
    """Unchanged from before the api engine existed, chat_timeout_s included."""
    client = Client(host=settings.ollama_host, timeout=settings.chat_timeout_s)

    def built(chat_request: ChatRequest) -> str:
        return chat_json(client=client, request=chat_request)

    return built


def _chat_client(request: Request) -> ChatClient:
    """The app's chat client, cached per engine/chain/keys fingerprint.

    ``app.state.chat_client``, when a caller (test or future wiring) sets it
    directly, always wins and skips this cache: that is the seam tests use to
    inject a scripted model instead of building one from settings.
    """
    existing = getattr(request.app.state, "chat_client", None)
    if existing is not None:
        return cast(ChatClient, existing)
    settings: Settings = request.app.state.settings
    fingerprint = _settings_fingerprint(settings=settings)
    if getattr(request.app.state, "_chat_client_fingerprint", None) == fingerprint:
        return cast(ChatClient, request.app.state._built_chat_client)
    client = (
        _build_local_client(settings=settings)
        if settings.llm_engine == "local"
        else llm_factory.build_from_settings(
            settings=settings, guard=request.app.state.gpu_arbiter.chat_turn
        )
    )
    request.app.state._built_chat_client = client
    request.app.state._chat_client_fingerprint = fingerprint
    return client


def _services(request: Request) -> ChatServices:
    settings: Settings = request.app.state.settings
    return ChatServices(
        store=request.app.state.job_store,
        index_path=request.app.state.search_index_path,
        arbiter=request.app.state.gpu_arbiter,
        chat_client=_chat_client(request=request),
        model=settings.ollama_model,
        guard_whole_client=settings.llm_engine == "local",
    )


Services = Annotated[ChatServices, Depends(_services)]


def _course_id(key: str, services: ChatServices) -> str:
    course = find_by_key(
        courses_dir=services.store.courses_dir, key=course_key(label=key)
    )
    if course is None:
        raise NotFoundError(entity="Corso", id=key)
    return course.id


def _locate(key: str, chat_id: str, services: ChatServices) -> ChatLocation:
    """Only uuid4 ids name a chat file: anything else is simply not found."""
    try:
        valid = str(UUID(chat_id)) == chat_id
    except ValueError:
        valid = False
    if not valid:
        raise NotFoundError(entity="Chat", id=chat_id)
    return ChatLocation(
        key=key, course_id=_course_id(key=key, services=services), chat_id=chat_id
    )


def _records(where: ChatLocation, services: ChatServices) -> list[ChatRecord]:
    records = load_records(
        courses_dir=services.store.courses_dir,
        course_id=where.course_id,
        chat_id=where.chat_id,
    )
    if not any(isinstance(record, ChatMeta) for record in records):
        raise NotFoundError(entity="Chat", id=where.chat_id)
    return records


def _meta_payload(meta: ChatMeta) -> dict[str, Any]:
    return {"id": meta.id, "title": meta.title, "created_at": meta.created_at}


def _answer_payload(
    record: ChatAnswerRecord, context: CitationContext
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "outcome": record.outcome.value,
        "discarded": record.discarded,
        "error": record.error,
        "created_at": record.created_at,
        "sentences": [
            {
                "text": sentence.text,
                "citations": [
                    resolve_citation(citation=citation, context=context)
                    for citation in sentence.citations
                ],
            }
            for sentence in record.sentences
        ],
    }


def _context(where: ChatLocation, services: ChatServices) -> CitationContext:
    return CitationContext(
        courses_dir=services.store.courses_dir,
        store=services.store,
        course_id=where.course_id,
        key=where.key,
    )


def _message_payload(
    record: ChatRecord, context: CitationContext
) -> dict[str, Any] | None:
    if isinstance(record, ChatQuestionRecord):
        return {"role": "user", "text": record.text, "created_at": record.created_at}
    if isinstance(record, ChatAnswerRecord):
        return _answer_payload(record=record, context=context)
    return None


@router.post("/{key:path}/chats", status_code=201)
def create_chat_route(key: str, services: Services) -> dict[str, Any]:
    course_id = _course_id(key=key, services=services)
    meta = create_chat(courses_dir=services.store.courses_dir, course_id=course_id)
    return {"data": _meta_payload(meta=meta)}


@router.get("/{key:path}/chats")
def list_chats_route(
    key: str,
    services: Services,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    courses_dir = services.store.courses_dir
    course = find_by_key(courses_dir=courses_dir, key=course_key(label=key))
    metas = (
        []
        if course is None
        else list_chats(courses_dir=courses_dir, course_id=course.id)
    )
    start = (page - 1) * per_page
    return {
        "data": [_meta_payload(meta=meta) for meta in metas[start : start + per_page]],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": len(metas),
            "total_pages": (len(metas) + per_page - 1) // per_page,
        },
    }


@router.get("/{key:path}/chats/{chat_id}")
def get_chat_route(key: str, chat_id: str, services: Services) -> dict[str, Any]:
    where = _locate(key=key, chat_id=chat_id, services=services)
    records = _records(where=where, services=services)
    meta = chat_meta(records=records)
    assert meta is not None  # _records guarantees a meta line
    context = _context(where=where, services=services)
    messages = [_message_payload(record=record, context=context) for record in records]
    return {
        "data": {
            **_meta_payload(meta=meta),
            "messages": [message for message in messages if message is not None],
        }
    }


@router.delete("/{key:path}/chats/{chat_id}", status_code=204)
def delete_chat_route(key: str, chat_id: str, services: Services) -> Response:
    where = _locate(key=key, chat_id=chat_id, services=services)
    delete_chat(
        courses_dir=services.store.courses_dir,
        course_id=where.course_id,
        chat_id=where.chat_id,
    )
    return Response(status_code=204)


@router.post("/{key:path}/chats/{chat_id}/messages")
def post_message_route(
    key: str, chat_id: str, body: ChatMessageBody, services: Services
) -> dict[str, Any]:
    where = _locate(key=key, chat_id=chat_id, services=services)
    records = _records(where=where, services=services)
    reply = ask(services=services, where=where, records=records, question=body.question)
    context = _context(where=where, services=services)
    return {"data": _answer_payload(record=reply, context=context)}
