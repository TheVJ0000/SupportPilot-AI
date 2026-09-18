# Synthetic RAG evaluation

Use the existing backend environment; no extra package, evaluation service or
credentials are needed for deterministic mode. From `backend`, on Windows:

```powershell
.\.venv\Scripts\python.exe -m evals.rag.runner --mode deterministic --output evals/rag/results/deterministic.json
.\.venv\Scripts\python.exe -m evals.rag.runner --mode deterministic --retrieval-only
.\.venv\Scripts\pytest.exe tests/test_rag_eval.py
```

On other platforms use `.venv/bin/python` and `.venv/bin/pytest` instead.
Generated JSON files under `results/` are gitignored. Per-case reports contain
source slugs, ranks, similarities, decisions, check counts, sanitized failure
codes and timings, **not** answer prose, prompts, vectors or provider payloads.

Offline mode uses independent hashed lexical ranking and manually authored SDK
responses. The real retrieval service, context builder, Gemini generation
adapter, streaming parser and citation post-processing execute with fake SDK
transport. It tests evaluation/contract behavior, **not live Gemini quality,
semantic retrieval, hosted pgvector or empirical prompt-injection resistance**.
The offline gateway never reads expected-answer/source/fact annotations.
Scripted response prose is separate from expected fact groups; partial/failing
results remain visible. The first dataset intentionally retains a retrieval miss.

## Explicit live command

```powershell
.\.venv\Scripts\python.exe -m evals.rag.runner --mode live --output evals/rag/results/live.json
```

Without required private configuration/attestation this returns
`LIVE EVALUATION UNAVAILABLE` (exit 2). It never falls
back to fixtures. Before any real call, an operator must privately supply the
existing `GEMINI_API_KEY` through the backend settings, and an existing safe
linked Free-development database connection through `PGHOST`, `PGUSER`,
`PGPASSWORD` (with `PGPORT`, `PGDATABASE`, `PGSSLROOTCERT` when needed).
The existing `psql`/libpq installation is used with TLS `verify-full`.
Do not put credential values in shell arguments, reports, this file or Git.
Do not enable paid billing or create infrastructure to satisfy this benchmark.

After independently verifying **both exact models** are available free for that
project and billing is disabled, append `--confirm-free-tier`. That flag is an
operator attestation, not automatic billing detection. Without it no call runs.
Models stay `gemini-3.8-flash` (LOW, strict structured JSON schema, tool-free) and
`gemini-embedding-2` (768 finite dimensions). Model availability is not established
by offline work alone. Fail closed if either model is unavailable or requires payment.

Live mode embeds 17 synthetic chunks, then seeds two fresh scopes in one SQL
transaction. Every query uses authenticated fixture-user claims and the actual
`search_knowledge_chunks` pgvector RPC, not service-role search or Python nearest
neighbors. Privileged setup touches only fresh random fixture IDs. Finally it
rolls back and checks the created users are absent; cleanup failure cannot pass.
No migration, hosted reset, real-data deletion or fixture commit is issued.

One additional Beta query proves the foreign fact is actually searchable in its
own scope before checking absence from Alpha. All 36 cases receive retrieval;
16 representative cases select generation,
including three using actual Gemini streaming. At most one primary generation
path per selected case; only existing adapter transient retries apply. After a
provider/evaluation failure the live loop stops and marks remaining cases
`not_run_after_failure`, preserving the failure and reducing quota use.
`generation_calls` counts actual primary invocations, not intended selection or
retry attempts. Provider errors are not insufficient-evidence successes.
`--retrieval-only` omits generation and its unmeasured metrics are null.

Exit 0 means the selected evaluation's documented gates passed; 1 means a failed
gate/operation; 2 means live prerequisites unavailable. Normal pytest never runs
live. This command does not run customer HTTP/persistence or triage smoke and
never sends email. See [the measured report](../../../docs/RAG_EVALUATION.md).
