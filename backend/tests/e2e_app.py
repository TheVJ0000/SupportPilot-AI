"""Loopback-only browser TEST server. NEVER imported by app.main.

Real routes/models/middleware/services; external Supabase and AI boundaries
are deterministic. Separate application instance; no production overrides.
No lifespan worker, outbound provider calls, hosted writes or static credential.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from app.admin.gateway import AdminOperationsGateway, get_admin_gateway
from app.admin.models import Metrics
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.factory import get_generation_provider
from app.ai.generation.models import (
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationStreamComplete,
    GroundedGenerationDecision,
)
from app.api.routes import api_router
from app.auth.dependencies import get_authenticated_context, get_token_verifier
from app.auth.models import AuthenticatedRequestContext, AuthenticatedUser
from app.auth.verifier import AuthenticationError
from app.chat.errors import CustomerChatGatewayError
from app.chat.gateway import get_customer_chat_gateway
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerFeedbackResponse,
    CustomerHistoryMessage,
    CustomerHumanRequestResult,
    PersistedCustomerTurn,
    StartedCustomerTurn,
)
from app.escalations.background import get_background_triage_runner
from app.knowledge.gateway import get_knowledge_gateway
from app.knowledge.models import ProcessingSource
from app.main import app as production
from app.rag.models import RetrievedChunk

ALPHA = "20000000-0000-4000-8000-000000000001"
BETA = "20000000-0000-4000-8000-000000000002"
PUBLIC = "10000000-0000-4000-8000-000000000001"
BETA_PUBLIC = "10000000-0000-4000-8000-000000000002"
CONV = "40000000-0000-4000-8000-000000000001"
HUMAN = "40000000-0000-4000-8000-000000000002"
ESC = "50000000-0000-4000-8000-000000000001"
SOURCE = "70000000-0000-4000-8000-000000000001"
USER = "90000000-0000-4000-8000-000000000001"
TIME = "2026-09-18T12:00:00Z"


def conversation(identifier, human=False):
    return dict(
        id=identifier,
        status="human_requested" if human else "open",
        resolution_outcome="unresolved",
        created_at=TIME,
        updated_at=TIME,
        last_message_at=TIME,
        human_requested_at=TIME if human else None,
        resolved_at=None,
        closed_at=None,
    )


def item(record):
    return {
        key: value
        for key, value in record.items()
        if key not in ("human_requested_at", "resolved_at", "closed_at")
    } | dict(
        message_count=2,
        assistant_message_count=1,
        feedback_positive_count=1,
        feedback_negative_count=0,
        has_escalation=False,
        escalation_priority=None,
    )


def knowledge(title, status="ready", source_id=SOURCE):
    return dict(
        id=source_id,
        title=title,
        source_type="faq",
        status=status,
        original_filename=None,
        created_at=TIME,
        processing_started_at=None,
        processing_attempts=0,
        extracted_at=None,
        extracted_char_count=None,
        chunk_count=0,
        last_error_code=None,
        processing_stage=None,
        indexing_attempts=0,
        indexed_at=None,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimension=None,
        last_failure_stage=None,
    )


class Reset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    role: str = "owner"
    scenario: str = "normal"


class State:
    def reset(self, request):
        self.token, self.role, self.scenario = request.token, request.role, request.scenario
        self.records = {CONV: conversation(CONV), HUMAN: conversation(HUMAN, True)}
        closed_id = "40000000-0000-4000-8000-000000000003"
        self.records[closed_id] = conversation(closed_id) | dict(
            status="closed", resolution_outcome="resolved", resolved_at=TIME, closed_at=TIME
        )
        self.escalation = dict(
            id=ESC,
            conversation_id=HUMAN,
            trigger_reason="human_requested",
            status="open",
            triage_status="pending",
            category=None,
            priority=None,
            summary=None,
            triage_attempts=0,
            created_at=TIME,
            updated_at=TIME,
            triaged_at=None,
            last_error_code=None,
            notification_status=None,
        )
        self.widget = True
        self.beta_widget = False
        self.customer_id = uuid4()
        self.hash = None
        self.history = []
        self.turns = {}
        self.attempts = []
        self.stream_calls = 0
        self.feedback_calls = 0
        self.status = "closed" if self.scenario == "closed" else "open"
        self.human_at = None
        self.gates = [asyncio.Event(), asyncio.Event()]
        self.delayed = asyncio.Event()
        self.delay_started = False
        self.delay_finished = False
        self.conflicted = False
        self.sources = [
            knowledge("Shipping Policy"),
            knowledge("Returns FAQ", source_id=str(uuid4())),
            knowledge("Troubleshooting Guide", "processing", str(uuid4())),
        ]


state = State()
state.reset(Reset(token=str(uuid4())))
app = FastAPI(title="SupportPilot browser test tooling")
app.user_middleware = production.user_middleware.copy()
app.include_router(api_router, prefix="/api")


@app.post("/_e2e/reset")
async def reset(request: Reset):
    if request.role not in ("owner", "admin", "member"):
        raise HTTPException(422)
    state.reset(request)
    return {"ok": True}


@app.get("/_e2e/state")
async def status():
    return dict(
        attempts=state.attempts,
        messages=len(state.history),
        feedback_calls=state.feedback_calls,
        stream_calls=state.stream_calls,
        delay_started=state.delay_started,
        delay_finished=state.delay_finished,
    )


@app.post("/_e2e/release/{gate}")
async def release(gate: int):
    if gate == 2:
        state.delayed.set()
    elif gate in (0, 1):
        state.gates[gate].set()
    else:
        raise HTTPException(422)
    return {"ok": True}


@app.get("/_e2e/knowledge")
async def sources():
    return state.sources


@app.post("/_e2e/close")
async def close():
    state.status = "closed"
    return {"ok": True}


@app.post("/_e2e/faq")
async def faq(data: dict):
    source = knowledge(data["question"], "pending", str(uuid4()))
    state.sources.append(source)
    return source


class Verifier:
    async def verify(self, token):
        if token != state.token:
            raise AuthenticationError
        return AuthenticatedUser(user_id=USER, email=f"{state.role}@example.test")


async def admin_dependency(
    context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
):
    async def rpc(request):
        data = json.loads(request.content)
        workspace = data["target_workspace_id"]
        if state.role == "member" or workspace not in (ALPHA, BETA):
            return httpx.Response(400, json={"code": "42501"})
        name = request.url.path.rsplit("/", 1)[-1]
        if state.scenario == "pending" and name.startswith("admin_set_"):
            state.delay_started = True
            await asyncio.wait_for(state.delayed.wait(), 20)
        if state.scenario == "late" and workspace == ALPHA and name == "admin_dashboard_snapshot":
            state.delay_started = True
            await asyncio.wait_for(state.delayed.wait(), 20)
            state.delay_finished = True
        if name == "admin_dashboard_snapshot":
            metrics = dict.fromkeys(Metrics.model_fields, 0)
            metrics.update(
                total_conversations=3 if workspace == ALPHA else 9,
                knowledge_ready=2,
                knowledge_processing=1,
            )
            if workspace == ALPHA:
                metrics.update(
                    resolved_conversations=1,
                    ai_answered_conversations=2,
                    human_requested_conversations=1,
                    open_escalations=1,
                )
            return httpx.Response(
                200,
                json=dict(
                    workspace_id=workspace,
                    metrics=metrics,
                    recent_conversations=[],
                    recent_escalations=[],
                ),
            )
        if name in ("admin_get_widget_config", "admin_set_widget_enabled"):
            attribute = "widget" if workspace == ALPHA else "beta_widget"
            if name == "admin_set_widget_enabled":
                if getattr(state, attribute) != data["expected_is_enabled"]:
                    return httpx.Response(400, json={"code": "40001"})
                setattr(state, attribute, data["new_is_enabled"])
            return httpx.Response(
                200,
                json=dict(
                    workspace_id=workspace,
                    workspace_name="Alpha Support" if workspace == ALPHA else "Beta Support",
                    public_id=PUBLIC if workspace == ALPHA else BETA_PUBLIC,
                    is_enabled=getattr(state, attribute),
                ),
            )
        if name == "admin_list_conversations":
            return httpx.Response(
                200,
                json=dict(
                    workspace_id=workspace,
                    items=[
                        item(r)
                        for r in sorted(state.records.values(), key=lambda r: r["id"], reverse=True)
                    ]
                    if workspace == ALPHA
                    else [],
                    next_cursor=None,
                ),
            )
        if name == "admin_list_escalations":
            fixtures = [state.escalation] + [
                state.escalation
                | dict(id=f"50000000-0000-4000-8000-00000000000{index}", status=escalation_status)
                for index, escalation_status in ((2, "in_progress"), (3, "resolved"))
            ]
            return httpx.Response(
                200,
                json=dict(
                    workspace_id=workspace,
                    items=sorted(fixtures, key=lambda record: record["id"], reverse=True)
                    if workspace == ALPHA
                    else [],
                    next_cursor=None,
                ),
            )
        if name.startswith("admin_set_") and state.scenario == "conflict" and not state.conflicted:
            state.conflicted = True
            return httpx.Response(
                400, json={"code": "40001", "message": "synthetic private SQL payload"}
            )
        if "conversation" in name:
            if workspace != ALPHA or data["target_conversation_id"] not in state.records:
                return httpx.Response(400, json={"code": "P0002"})
            record = state.records[data["target_conversation_id"]]
            if name == "admin_set_conversation_resolution":
                if (
                    record["status"] != data["expected_status"]
                    or record["resolution_outcome"] != data["expected_resolution_outcome"]
                ):
                    return httpx.Response(400, json={"code": "40001"})
                action = data["requested_action"]
                record.update(
                    status=("human_requested" if record["human_requested_at"] else "open")
                    if action == "reopen"
                    else "closed",
                    resolution_outcome={
                        "resolve": "resolved",
                        "close_unresolved": "closed_unresolved",
                        "reopen": "unresolved",
                    }[action],
                    resolved_at=TIME if action == "resolve" else None,
                    closed_at=None if action == "reopen" else TIME,
                )
            messages = [
                dict(
                    id=str(uuid4()),
                    role="customer",
                    content="Alpha shipping question",
                    answer_status=None,
                    created_at=TIME,
                    feedback=None,
                    citations=[],
                ),
                dict(
                    id=str(uuid4()),
                    role="assistant",
                    content="Alpha orders ship within two days.",
                    answer_status="answered",
                    created_at=TIME,
                    feedback="positive",
                    citations=[
                        dict(
                            source_id=SOURCE,
                            source_title="Shipping Policy",
                            source_type="file",
                            chunk_index=0,
                            locator={"kind": "pdf", "page_start": 2, "page_end": 2},
                        )
                    ],
                ),
            ]
            return httpx.Response(
                200,
                json=dict(
                    workspace_id=workspace, conversation=record, messages=messages, escalation=None
                ),
            )
        if workspace != ALPHA or data.get("target_escalation_id") != ESC:
            return httpx.Response(400, json={"code": "P0002"})
        if name == "admin_set_escalation_status":
            if state.escalation["status"] != data["expected_current_status"]:
                return httpx.Response(400, json={"code": "40001"})
            state.escalation["status"] = data["new_status"]
        return httpx.Response(
            200,
            json=dict(
                workspace_id=workspace,
                escalation=state.escalation,
                audit_runs=[],
                notification=None,
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(rpc)) as client:
        yield AdminOperationsGateway(
            "https://supportpilot.example.test",
            "synthetic-publishable-placeholder",
            context.access_token,
            client,
        )


class CustomerGateway:
    async def create_session(self, public_id, token_hash, expires_at):
        if str(public_id) != PUBLIC or not state.widget:
            raise CustomerChatGatewayError("create_customer_chat_session", "P0002")
        state.hash = token_hash
        return CreatedCustomerSession(
            customer_session_id=uuid4(),
            conversation_id=state.customer_id,
            workspace_id=ALPHA,
            workspace_name="Alpha Support",
            expires_at=expires_at,
        )

    def authorize(self, conversation_id, token_hash):
        if conversation_id != state.customer_id or token_hash != state.hash:
            raise CustomerChatGatewayError("get_customer_conversation", "28000")

    async def get_conversation(self, conversation_id, token_hash, *, public_request=False):
        self.authorize(conversation_id, token_hash)
        return CustomerConversationResponse(
            conversation_id=conversation_id,
            status=state.status,
            human_requested_at=state.human_at,
            messages=state.history,
        )

    async def begin_turn(self, conversation_id, token_hash, client_message_id, message):
        self.authorize(conversation_id, token_hash)
        state.attempts.append(str(client_message_id))
        if state.scenario == "throttle" and len(state.attempts) == 1:
            raise CustomerChatGatewayError("begin_customer_chat_turn", "PT429", 2)
        if state.scenario == "internal":
            raise CustomerChatGatewayError(
                "begin_customer_chat_turn", "XX000: synthetic SELECT secret-looking-provider-value"
            )
        if state.status != "open":
            raise CustomerChatGatewayError("begin_customer_chat_turn", "55000")
        existing = state.turns.get(client_message_id)
        if existing and existing.get("result"):
            return StartedCustomerTurn(
                turn_id=existing["id"],
                workspace_id=ALPHA,
                conversation_id=conversation_id,
                turn_status="completed",
                is_replay=True,
            )
        if not existing:
            state.turns[client_message_id] = dict(id=uuid4())
            state.history.append(
                CustomerHistoryMessage(
                    id=uuid4(),
                    role="customer",
                    content=message,
                    created_at=datetime.now(UTC),
                    citations=[],
                )
            )
        state.current = client_message_id
        return StartedCustomerTurn(
            turn_id=state.turns[client_message_id]["id"],
            workspace_id=ALPHA,
            conversation_id=conversation_id,
            turn_status="processing",
            is_replay=False,
        )

    def retrieval_gateway(self, *args):
        return self

    async def search(self, *args):
        return [
            RetrievedChunk(
                chunk_id=uuid4(),
                source_id=SOURCE,
                source_title="Shipping Policy",
                source_type="file",
                chunk_index=0,
                content="Orders ship within two days.",
                locator={"kind": "pdf", "page_start": 2, "page_end": 2},
                similarity=0.9,
            )
        ]

    async def complete_turn(self, turn_id, token_hash, answer_status, answer, citations):
        result = PersistedCustomerTurn(
            turn_id=turn_id,
            conversation_id=state.customer_id,
            message_id=uuid4(),
            client_message_id=state.current,
            answer_status=answer_status,
            answer=answer,
            citations=citations,
        )
        state.turns[state.current]["result"] = result
        state.history.append(
            CustomerHistoryMessage(
                id=result.message_id,
                role="assistant",
                content=answer,
                answer_status=answer_status,
                created_at=datetime.now(UTC),
                citations=citations,
            )
        )

    async def get_turn_result(self, conversation_id, token_hash, client_message_id):
        self.authorize(conversation_id, token_hash)
        return state.turns[client_message_id]["result"]

    async def fail_turn(self, *args):
        return None

    async def set_feedback(self, conversation_id, token_hash, message_id, rating):
        self.authorize(conversation_id, token_hash)
        state.feedback_calls += 1
        if state.scenario == "feedback_fail" and state.feedback_calls == 1:
            raise CustomerChatGatewayError("set_customer_message_feedback", "PT429", 2)
        for message in state.history:
            if message.id == message_id and message.role == "assistant":
                message.feedback = rating
                return CustomerFeedbackResponse(message_id=message_id, rating=rating)
        raise CustomerChatGatewayError("set_customer_message_feedback", "P0002")

    async def request_human_support(self, conversation_id, token_hash):
        self.authorize(conversation_id, token_hash)
        first = state.status != "human_requested"
        state.status = "human_requested"
        if first:
            state.human_at = datetime.now(UTC)
        return CustomerHumanRequestResult(
            conversation_id=conversation_id,
            status=state.status,
            human_requested_at=state.human_at,
            escalation_id=ESC,
            triage_status="pending",
            is_new_request=first,
        )


class Embeddings:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    async def embed_query(self, question):
        return [0.1] * 768


class Generation:
    provider_name = "synthetic"
    model_name = "browser-fixture"

    async def stream_grounded_answer(self, question, evidence):
        state.stream_calls += 1
        insufficient = state.scenario == "insufficient"
        result = GroundedGenerationDecision(
            decision="insufficient_evidence" if insufficient else "answerable",
            answer="" if insufficient else "Orders ship within two days.",
            evidence_ids=[] if insufficient else ["E1"],
        )
        yield GenerationDecisionEvent(decision=result.decision, evidence_ids=result.evidence_ids)
        if not insufficient:
            yield GenerationAnswerDelta(text="Orders ")
            await asyncio.wait_for(state.gates[0].wait(), 20)
            if state.scenario == "retry" and state.stream_calls == 1:
                raise GenerationProviderError("generation_provider_unavailable")
            yield GenerationAnswerDelta(text="ship ")
            await asyncio.wait_for(state.gates[1].wait(), 20)
            yield GenerationAnswerDelta(text="within two days.")
        yield GenerationStreamComplete(result=result)


class KnowledgeGateway:
    async def begin_extraction(self, source_id):
        return ProcessingSource(
            source_id=source_id,
            workspace_id=UUID(ALPHA),
            source_type="faq",
            storage_path=None,
            original_filename=None,
            mime_type=None,
            byte_size=None,
            faq_question="Synthetic FAQ?",
            faq_answer="Synthetic answer.",
        )

    async def complete_extraction(self, source_id, chunks, extracted_char_count):
        for source in state.sources:
            if source["id"] == str(source_id):
                source.update(
                    status="pending",
                    extracted_at=TIME,
                    chunk_count=len(chunks),
                    extracted_char_count=extracted_char_count,
                )


class Background:
    async def __call__(self, *args):
        return None


app.dependency_overrides.update(
    {
        get_token_verifier: Verifier,
        get_admin_gateway: admin_dependency,
        get_customer_chat_gateway: CustomerGateway,
        get_embedding_provider: Embeddings,
        get_generation_provider: Generation,
        get_knowledge_gateway: KnowledgeGateway,
        get_background_triage_runner: Background,
    }
)
