"""Test-only transactional fixtures; real scoped PostgreSQL pgvector RPC.

Privileged setup is confined to fresh random IDs in one rolled-back transaction.
Search runs as authenticated with a fixture user's claims, not service_role.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from app.rag.gateway import parse_retrieval_rows
from app.rag.service import validate_query_vector

from .deterministic import corpus_chunks
from .models import Dataset, identifier

TOOLS = Path(__file__).resolve().parents[3] / "supabase/tests"


def tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    if not spec or not spec.loader:
        raise RuntimeError("Existing database tooling unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quote(value: str) -> str:
    # All inputs are validated fixture data, not a shell command or dynamic identifier.
    return "'" + value.replace("'", "''") + "'"


class HostedGateway:
    def __init__(self, dataset: Dataset, environment: dict[str, str]):
        self.dataset = dataset
        self.connection = tool("postgres_connection").Postgres(
            environment, "supportpilot_rag_evaluation"
        )
        self.workspaces = {}
        self.users = {}
        self.source_ids = {source.id: uuid4() for source in dataset.sources}
        self.chunk_ids = {
            f"{source.id}/{index}": uuid4() for source, index, _ in corpus_chunks(dataset)
        }
        self.active = False
        self.rollback_verified = False

    def seed(self, vectors: list[list[float]], model: str):
        chunks = list(corpus_chunks(self.dataset))
        if len(vectors) != len(chunks):
            raise ValueError("Invalid document vector count")
        vectors = [validate_query_vector(vector, 768) for vector in vectors]
        self.connection.query("begin;")
        self.active = True
        for scope in ("alpha", "beta"):
            user = uuid4()
            self.users[scope] = user
            self.connection.query(
                "insert into auth.users (id,email,raw_user_meta_data) "
                f"values ('{user}','eval-{user}@example.test','{{}}');"
            )
            self.connection.query(
                f"set local role authenticated; set local request.jwt.claim.sub='{user}';"
            )
            workspace = self.connection.query(
                f"select id from public.create_workspace('Northstar Evaluation {scope}');"
            )[0][0]
            self.workspaces[scope] = workspace
            self.connection.query("reset role;")
        for source in self.dataset.sources:
            text = "\n\n".join(source.chunks)
            self.connection.query(f"""insert into public.knowledge_sources
                (id, workspace_id, created_by, source_type, title, status, faq_question, faq_answer,
                 extracted_at, extracted_char_count, chunk_count, indexed_at,
                 embedding_provider, embedding_model, embedding_dimension)
                values ('{self.source_ids[source.id]}','{self.workspaces[source.workspace]}',
                '{self.users[source.workspace]}', 'faq',{quote(source.title)},'ready',
                {quote("Synthetic policy: " + source.title)}, {quote(text)},
                now(),{len(text)},{len(source.chunks)},now(),'gemini',{quote(model)},768);""")
        for (source, index, text), vector in zip(chunks, vectors, strict=True):
            self.connection.query(f"""insert into public.knowledge_chunks
                (id,source_id,workspace_id,chunk_index,content,content_sha256,char_count,locator,embedding)
                values ('{self.chunk_ids[f"{source.id}/{index}"]}','{self.source_ids[source.id]}',
                '{self.workspaces[source.workspace]}',{index},{quote(text)},
                '{hashlib.sha256(text.encode()).hexdigest()}',{len(text)},'{{"kind":"faq"}}',
                {quote(json.dumps(vector, allow_nan=False))}::extensions.vector);""")

    async def search(
        self, workspace_id, query_embedding, provider_name, model_name, dimension, match_count
    ):
        scope = next(scope for scope in self.workspaces if identifier(scope) == workspace_id)
        vector = validate_query_vector(query_embedding, dimension)
        self.connection.query(
            f"set local role authenticated; set local request.jwt.claim.sub='{self.users[scope]}';"
        )
        result = self.connection.query(f"""select
            coalesce(jsonb_agg(to_jsonb(row)),'[]'::jsonb)::text
            from public.search_knowledge_chunks('{self.workspaces[scope]}',
            {quote(json.dumps(vector, allow_nan=False))}::jsonb,{quote(provider_name)},
            {quote(model_name)},768,{match_count}) as row;""")
        rows = json.loads(result[0][0])
        # Stable benchmark identities only at the reporting boundary. Real RPC
        # filtering/ranking and metadata are validated before replacing random IDs.
        matches = parse_retrieval_rows(rows, "search_knowledge_chunks")
        reverse_sources = {value: key for key, value in self.source_ids.items()}
        reverse_chunks = {value: key for key, value in self.chunk_ids.items()}
        from dataclasses import replace

        return [
            replace(
                match,
                source_id=identifier(reverse_sources[match.source_id]),
                chunk_id=identifier(reverse_chunks[match.chunk_id]),
            )
            for match in matches
        ]

    def close(self):
        try:
            if self.active:
                self.connection.query("rollback;")
                self.active = False
                ids = ",".join(f"'{user}'" for user in self.users.values())
                count = self.connection.query(
                    f"select count(*) from auth.users where id in ({ids});"
                )[0][0]
                self.rollback_verified = count == "0"
                if not self.rollback_verified:
                    raise RuntimeError("Fixture rollback verification failed")
        finally:
            self.connection.close()
