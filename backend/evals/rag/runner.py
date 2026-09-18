"""Explicit, offline-by-default benchmark command. Never imported by app.main."""

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from app.ai.embeddings.base import EmbeddingDocument
from app.ai.embeddings.errors import EmbeddingProviderError
from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import (
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationStreamComplete,
)
from app.chat.context import build_contextual_question
from app.rag.answering import (
    grounded_response_from_decision,
    insufficient_response,
    prepare_grounded_evidence,
)
from app.rag.service import KnowledgeRetrievalService

from .deterministic import Embeddings, Gateway, corpus_chunks, generation
from .metrics import aggregate, score_case
from .models import Dataset, identifier, load_dataset


async def run_cases(
    dataset: Dataset, gateway, embeddings, *, live_provider=None, retrieval_only=False
):
    rows = []
    halted = False
    for case in dataset.cases:
        retrieval = None
        answer = None
        error = None
        stream_checked = False
        generation_called = False
        timings = {}
        evaluated = not retrieval_only and (live_provider is None or case.live_generation)
        if halted:
            rows.append(
                score_case(
                    dataset,
                    case,
                    None,
                    None,
                    generation_evaluated=evaluated,
                    error="not_run_after_failure",
                )
            )
            continue
        try:
            query = build_contextual_question(case.question, case.context_turns)
            started = perf_counter()
            retrieval = await KnowledgeRetrievalService(gateway, embeddings).retrieve(
                identifier(case.workspace), query
            )
            timings["embedding_and_retrieval_ms"] = round((perf_counter() - started) * 1000, 2)
            if evaluated:
                prepared = prepare_grounded_evidence(retrieval)
                if prepared is None:
                    answer = insufficient_response(identifier(case.workspace), retrieval.question)
                else:
                    provider = live_provider or generation(dataset, case)
                    generation_called = True
                    started = perf_counter()
                    if case.live_stream:
                        prefix = None
                        deltas = []
                        final = None
                        async for event in provider.stream_grounded_answer(
                            retrieval.question, prepared.evidence
                        ):
                            if isinstance(event, GenerationDecisionEvent):
                                if prefix is not None or deltas or final:
                                    raise ValueError("Invalid stream ordering")
                                prefix = event
                            elif isinstance(event, GenerationAnswerDelta):
                                if prefix is None or prefix.decision != "answerable" or final:
                                    raise ValueError("Invalid delta ordering")
                                deltas.append(event.text)
                            elif isinstance(event, GenerationStreamComplete):
                                if prefix is None or final:
                                    raise ValueError("Invalid stream completion")
                                final = event.result
                            else:
                                raise ValueError("Invalid stream event")
                        if (
                            final is None
                            or prefix is None
                            or final.answer != "".join(deltas)
                            or final.decision != prefix.decision
                            or set(final.evidence_ids) != set(prefix.evidence_ids)
                        ):
                            raise ValueError("Inconsistent or incomplete stream")
                        decision = final
                        stream_checked = True
                    else:
                        decision = await provider.generate_grounded_answer(
                            retrieval.question, prepared.evidence
                        )
                    answer = grounded_response_from_decision(prepared, decision)
                    timings["generation_ms"] = round((perf_counter() - started) * 1000, 2)
        except (EmbeddingProviderError, GenerationProviderError):
            error = "provider_error"
            halted = live_provider is not None
        except Exception as failure:
            # Never include exception messages or provider/DB payloads in output.
            if getattr(failure, "status_code", None) in (502, 503):
                error = "provider_error"
                halted = live_provider is not None
            else:
                error = "evaluation_error"
                halted = live_provider is not None
        row = score_case(
            dataset, case, retrieval, answer, generation_evaluated=evaluated, error=error
        )
        row.update(
            stream_checked=stream_checked, timings=timings, generation_called=generation_called
        )
        row["timings"]["overall_ms"] = round(sum(timings.values()), 2)
        rows.append(row)
    return rows


def unavailable(reasons: list[str]):
    return dict(status="LIVE EVALUATION UNAVAILABLE", reasons=reasons, live_calls=0)


async def live(dataset: Dataset, *, confirm_free_tier: bool, retrieval_only: bool):
    from app.core.config import Settings

    settings = Settings()
    missing = []
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY missing")
    if not confirm_free_tier:
        missing.append("Free-tier eligibility/billing-disabled confirmation missing")
    if (
        settings.gemini_generation_model != "gemini-3.8-flash"
        or settings.gemini_embedding_model != "gemini-embedding-2"
    ):
        missing.append("Existing model configuration differs from benchmark requirements")
    if not all(os.environ.get(key) for key in ("PGHOST", "PGUSER", "PGPASSWORD")):
        missing.append("Existing safe PG connection configuration missing")
    if missing:
        return unavailable(missing)

    from google import genai

    from app.ai.embeddings.gemini import GeminiEmbeddingProvider
    from app.ai.generation.gemini import GeminiGenerationProvider

    from .hosted import HostedGateway

    hosted = None
    client = None
    result = None
    try:
        # Verify TLS/database availability BEFORE spending any AI quota.
        hosted = HostedGateway(dataset, os.environ.copy())
        client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
        embeddings = GeminiEmbeddingProvider(
            "configured-server-key", settings.gemini_embedding_model, 768, client=client
        )
        provider = GeminiGenerationProvider(
            "configured-server-key", settings.gemini_generation_model, client=client
        )
        documents = [
            EmbeddingDocument(text, source.title) for source, _, text in corpus_chunks(dataset)
        ]
        vectors = await embeddings.embed_documents(documents)
        hosted.seed(vectors, settings.gemini_embedding_model)
        control_vector = await embeddings.embed_query(
            "What is the private demonstration locker code?"
        )
        control = await hosted.search(
            identifier("beta"), control_vector, "gemini", settings.gemini_embedding_model, 768, 8
        )
        if len(control) != 1 or control[0].source_id != identifier("private-locker"):
            raise ValueError("Isolation fixture positive control failed")
        rows = await run_cases(
            dataset, hosted, embeddings, live_provider=provider, retrieval_only=retrieval_only
        )
        result = report(dataset, rows, mode="live", retrieval_only=retrieval_only)
        result["live_embedding"] = dict(
            document_success=True,
            query_control_success=True,
            dimension=768,
            model=settings.gemini_embedding_model,
        )
        result["isolation_positive_control"] = True
        return result
    except (EmbeddingProviderError, GenerationProviderError):
        result = dict(status="LIVE EVALUATION FAILED", failure="provider_error")
        return result
    except Exception:
        result = dict(status="LIVE EVALUATION FAILED", failure="evaluation_or_database_error")
        return result
    finally:
        if hosted is not None:
            try:
                hosted.close()
                if result is not None:
                    result["rollback_verified"] = hosted.rollback_verified
            except Exception:
                if result is not None:
                    result.update(status="LIVE EVALUATION FAILED", failure="rollback_error")
        if client is not None:
            await client.aio.aclose()


def report(dataset, rows, *, mode, retrieval_only):
    return dict(
        status="evaluated",
        mode=mode,
        dataset_version=dataset.version,
        date=datetime.now(UTC).date().isoformat(),
        measurement="live Gemini + scoped hosted PostgreSQL RPC"
        if mode == "live"
        else (
            "offline lexical retrieval diagnostic + scripted SDK contract responses; "
            "NOT live model quality"
        ),
        generation_model="gemini-3.8-flash",
        embedding_model="gemini-embedding-2" if mode == "live" else "hashed-bag-of-words (fixture)",
        dimension=768,
        category_counts=dict(Counter(case.category for case in dataset.cases)),
        retrieval_only=retrieval_only,
        summary=aggregate(rows),
        cases=rows,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("deterministic", "live"), default="deterministic")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument(
        "--confirm-free-tier",
        action="store_true",
        help="Only after verifying both configured models are free and billing is disabled",
    )
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset()
        if args.mode == "live":
            result = asyncio.run(
                live(
                    dataset,
                    confirm_free_tier=args.confirm_free_tier,
                    retrieval_only=args.retrieval_only,
                )
            )
            result.update(
                mode="live",
                dataset_version=dataset.version,
                date=datetime.now(UTC).date().isoformat(),
                case_count=len(dataset.cases),
                generation_model="gemini-3.8-flash",
                embedding_model="gemini-embedding-2",
                dimension=768,
            )
        else:
            rows = asyncio.run(
                run_cases(
                    dataset, Gateway(dataset), Embeddings(), retrieval_only=args.retrieval_only
                )
            )
            result = report(dataset, rows, mode="deterministic", retrieval_only=args.retrieval_only)
    except Exception:
        # Pydantic validation messages may contain input values: suppress them.
        result = dict(status="EVALUATION FAILED", failure="evaluation_error")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    console = {key: value for key, value in result.items() if key != "cases"}
    print(json.dumps(console, indent=2, allow_nan=False))
    if result["status"] != "evaluated":
        return 2 if result["status"] == "LIVE EVALUATION UNAVAILABLE" else 1
    summary = result["summary"]
    if args.retrieval_only:
        return (
            0
            if summary["quality_gates"]["hit8"]
            and summary["quality_gates"]["recall8"]
            and summary["security"]["cross_workspace_leakage"] == 0
            and not summary["provider_errors"]
            and not summary["evaluation_errors"]
            else 1
        )
    return 0 if summary["security_gate"] and summary["quality_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
