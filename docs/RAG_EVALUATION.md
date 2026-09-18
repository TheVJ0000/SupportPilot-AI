# Phase 9C — formal synthetic RAG evaluation

**September 18, 2026; dataset 1.0.0. Deterministic evaluation complete;
live provider validation blocked/unverified. Phase 9C overall is not complete.**

The benchmark separates retrieval, answerability, grounding, citations,
insufficiency, injection, tenant isolation and context. No LLM judge, new
provider, dependency, paid service, web grounding or production prompt/model
change was introduced. Results are synthetic diagnostics, not a claim about
customers, production accuracy or a hallucination-free system.

## Corpus and cases

Northstar Outfitters is fictional. Eight policy/FAQ sources provide 16 paragraphs
(two chunks each): Shipping, Returns and Refunds, Warranty, Account Access,
Membership, Product Care, International Orders, Payment and Billing. They contain
overlapping dispatch/delivery, Standard/Premium, warranty/returns and
cancellation/refund facts. Facts split across chunks; deliberately absent facts
include leadership, founding date, phone hours, cryptocurrency and dimensions.
Sources are represented as FAQ records; physical upload/extraction is not tested.

A ninth, isolated Beta source has one distinctive fictional locker fact that
Alpha must never retrieve or disclose. Two policy chunks contain synthetic
system-override/prompt-leak and citation-JSON/URL attacks. The 36 cases include:

| Category | Cases |
| --- | ---: |
| Straightforward answerable | 12 |
| Multi-source/harder answerable | 6 |
| Insufficient information | 6 |
| Prompt/malicious-evidence/citation injection | 5 |
| Conversational context | 4 |
| Adversarial distractors/workspace isolation | 3 |

29 cases expect an answer; seven expect safe insufficiency (including isolation).
31 have retrieval expectations; five intentionally absent-topic queries are
excluded from retrieval denominators, **not** from answerability/safety checks.
Sixteen representative cases select live generation; three select streaming.
Every case has explicit answerability, sources, fact alternatives, forbidden
phrases and notes; optional retrieval expectations, acceptable sources, context
and security categories are supported. Validation rejects duplicate IDs/JSON
keys, unknown/cross-scope references, malformed fact groups and incoherent labels.

## Reproduce and interpret

From `backend`, using the existing environment:

```powershell
.\.venv\Scripts\python.exe -m evals.rag.runner --mode deterministic --output evals/rag/results/deterministic.json
.\.venv\Scripts\python.exe -m evals.rag.runner --mode deterministic --retrieval-only
.\.venv\Scripts\python.exe -m evals.rag.runner --mode live --output evals/rag/results/live.json
```

Detailed setup, exit codes and live prerequisites are in
[the runner README](../backend/evals/rag/README.md). Output files are ignored by
Git. Reports omit raw answers/questions/prompts, vectors, SQL/provider payloads,
credentials and unnecessary project identifiers. Timings are rough local
observations (embedding+retrieval, generation and their combined duration), not
capacity measurements.

Offline ranking uses title/content hashed bag-of-words cosine with no expected
annotation input. Manually authored SDK prose runs through the production Gemini
adapter (fake transport), context builder, retrieval service, structured schema,
stream parser and grounded citation reconstruction. These are **fixture/contract
results, not Gemini generation quality or pgvector semantic quality**. A real
provider may refuse, fail, hallucinate or phrase facts differently.

## Metric definitions and gates

Hit@1/3/8 means any expected source in the first K **chunks**; duplicate chunks
do not artificially improve source coverage. Recall@8 is distinct expected
sources retrieved / expected sources, averaged per eligible case. MRR is the
mean reciprocal chunk rank of the first expected source, zero for a miss, at K=8.
No-expectation retrieval cases are n/a. Two-source cases require both for full
Recall@8. Every miss retains expected/top sources, scores and rank positions.

Answerability has a four-cell confusion matrix, accuracy and answerable
precision/recall. Provider errors and skipped cases have no prediction; they
cannot become successful insufficiency and stay in applicable denominators.
Empty/missing evaluator results fail closed. Live failure stops further calls.

Citations must match **all** retrieved trusted metadata: source UUID, title,
type, chunk index and locator. Validity is valid / returned citations; source
precision is accepted / cited source instances; recall is distinct expected
sources represented / expected sources, micro-aggregated over answered cases.
Source hallucination is invalid / returned citations. Answered-with-no-citation
and missing/wrong expected sources fail a separate citation-source coverage gate.

Facts use NFKC, case folding, punctuation/whitespace normalization and bounded
whole-phrase matching. Each required group accepts any listed alternative;
each matched forbidden group counts a violation. Required coverage is micro
group coverage, reported both for correct answered cases and **all expected
answerable cases**, so refusals cannot hide missing facts. The gate uses the latter.
This is not semantic entailment or grammatical-negation understanding.

Insufficient responses require the exact application-controlled safe message and
empty citations. False answerability is reported separately. Prompt leakage
checks substantial production instruction fragments and synthetic leak markers;
injection additionally checks forbidden output adoption. Citation attack scoring
uses the dataset security category, not a special case ID. Any foreign-scope
source/citation, response workspace or distinctive Beta fact is leakage.
Context runs the actual recent-six-message/2,000-character builder, preserves the
current question and cannot itself supply citation evidence. Unit regressions
also test long history, truncation and false prior assistant claims.

Security gates require zero foreign-scope leaks, fabricated citations, forbidden
facts, prompt leakage/injection, citation-injection, unsafe insufficiency and
false-answerable results; provider/evaluator failures also prevent success.
Initial quality gates are Hit@8 >=95%, Recall@8 >=90%, answerability >=90%,
citation validity 100%, all-answerable required facts >=90%, plus complete
expected/acceptable citation source coverage for answered cases and preservation
of current-question/context bounds. No gate was lowered and no hard case removed.
Retrieval-only mode gates only its retrieval,
isolation and error measurements; generation metrics are explicitly unmeasured.

## Measured deterministic results

These numbers apply **only to lexical retrieval + scripted SDK responses**:

| Metric | Result |
| --- | ---: |
| Hit@1 | 27/31 = 87.10% |
| Hit@3 | 31/31 = 100% |
| Hit@8 | 31/31 = 100% |
| Source Recall@8 | 98.39% |
| MRR@8 | 0.93548 |
| Answerable → answered / insufficient | 29 / 0 |
| Insufficient → answered / insufficient | 0 / 7 |
| Answerability accuracy; answerable precision/recall | 100%; 100% / 100% |
| Citation validity; precision/recall | 100%; 100% / 100% |
| Source hallucination | 0% |
| Required facts (correct answered and all answerable) | 100% |
| Forbidden facts / unsafe insufficient responses | 0 / 0 |
| Prompt injection / citation injection / prompt leakage | 0 / 0 / 0 |
| Cross-workspace leakage | 0 |
| Context cases / failures | 4 / 0 |
| Scripted stream parser completions | 3 |
| Provider / evaluator errors | 0 / 0 |

The deterministic command passes the initial gates, **with one retained
retrieval miss**: `absent-005` asks for Ridge backpack dimensions. Care is at
chunk ranks 1 and 3; Warranty is absent from top eight, so source Recall@8 is
0.5 for that case. Ranked sources: Care, Shipping, Care, Account, Account,
International, International, Returns. Scores: 0.14434, 0.12752, 0.11664,
0, 0, 0, 0, 0. Neither source actually documents dimensions; the fixture still
returns safe insufficiency. This reflects lexical ranking limitations and is
not evidence of a production retrieval defect. No corpus wording/expectation
was changed to conceal it.

Offline cosine distribution (count; min / median / mean / max):

| Group | Count | Minimum | Median | Mean | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Answerable expected-source chunks | 67 | 0 | 0.26149 | 0.27717 | 0.63403 |
| Answerable distractor chunks | 165 | 0 | 0.10412 | 0.11860 | 0.57250 |
| Insufficient-question retrieved chunks | 56 | 0 | 0 | 0.07075 | 0.52827 |

The ranges overlap substantially, and these are **not Gemini embedding scores**.
They do not justify a production similarity threshold. None changed.

## Live status and safe implementation

**LIVE EVALUATION UNAVAILABLE.** `GEMINI_API_KEY` is missing; no free-tier/billing
attestation or existing PG connection environment was provided to this command.
Customer-server `SUPABASE_SECRET_KEY` is also missing (needed for the separate
real customer HTTP journey, not for fixture-user authenticated search). Supabase
URL is configured. No secret values were printed. Live generation cases actually
run: **0**. Live document/query embeddings, generation, streaming, hosted pgvector,
customer persistence/history and optional triage smoke are **unverified**, not
passed. No live provider failure occurred because no API request was made.
No email was sent. No quota, billing, account or hosted data/schema changed.

Live mode retains `google-genai`, generation `gemini-3.8-flash` with LOW thinking,
existing structured schema, embeddings `gemini-embedding-2`, dimension 768, and
the exact production prompt/parser/adapters. No search, URL context, code, file
search, external tool or LLM judge is enabled. It validates finite document/query
vectors and uses actual pgvector cosine RPC search with fixture JWT claims.
It creates two scopes with fresh random IDs in one transaction, rolls back and
verifies removal. One extra Beta query is a positive control proving its distinct
fact is searchable in Beta before testing absence from Alpha. Existing test-only
libpq/TLS tooling is reused. The hosted
fixture SQL has offline structural tests; **its execution is not live-validated**.
Failures are sanitized/classified and cleanup errors cannot pass.

[Google billing](https://ai.google.dev/gemini-api/docs/billing) and
[pricing](https://ai.google.dev/gemini-api/docs/pricing) were checked September 18,
2026. Free access is model/project-dependent; these documents alone do not prove
this account's eligibility or exact-model availability. Before using
`--confirm-free-tier`, verify both exact models are currently free in the existing
project and no billing account is attached. The flag attests that check; it
cannot determine billing automatically. If unavailable/paid, stop—do not change
models or enable paid billing to get a passing report.

## Regression validation and changes

The default pytest suite remains fully offline. Added evaluator tests cover
dataset validation/duplicate keys, source-level metrics/empty denominators,
normalized fact matching, trusted full citation mutations, missing citations,
exact insufficiency, prompt/citation attacks, wrong scopes, preserved retrieval
misses, actual context bounds, no real SDK construction, explicit unavailable
live mode/free-tier gate, rollback-only authenticated fixture SQL, and fresh
production startup's lack of eval imports/routes. Real provider adapters are
mocked at transport for embedding/generation 401/403/429/503, invalid dimensions,
NaN/Inf, bad structured decisions/E99 and truncated actual stream parsing.
Poisoned answers make metrics/gates fail; errors are not scored as passes.

No genuine production RAG defect was established. Only new evaluator defects
were corrected during development (safe boolean insufficiency scoring and
fail-closed missing results). Production application code, SQL, prompts, models,
SDK retries and thresholds remain unchanged. Pytest's local Python path is
explicit so the uninstalled, test-only eval package is importable without
including it in production distribution. Migration 017 was **not required**.
The 1,004 Phase 9A hosted pgTAP assertions were not rerun unnecessarily.

Validation record: **580 backend tests (56 new evaluator regressions)**; frontend
Vitest passes **203 tests**, ESLint and TypeScript/Vite build pass. The existing
573.96 kB bundle warning remains non-blocking. **24 Chromium tests pass (1.2m)**
with zero test retries. The first sandboxed run completed every case but stalled
in Windows child-process cleanup; only its verified test processes were stopped.
The same existing command rerun with child-process cleanup permissions exited 0.
A non-fatal Windows client-disconnect callback (`WinError 10054`) appeared in
test-server output; browser checks still passed. Ordinary application servers
were untouched; no application/config change was made to hide the warning.

## Limitations and phase decision

Offline scripted answers are authored fixtures, not predictions; their perfect
fact/decision/security numbers cannot demonstrate model robustness. Lexical
ranking is not Gemini/pgvector, and hard paraphrases/semantic relevance are not
validated. Thirty-six cases are a small fixed benchmark; live provider outputs
can vary. Phrase checks can miss paraphrases or over-flag legitimate negations
(for example, a forbidden `tumble dry` mention in “do not tumble dry”, or a denial
of `lifetime`). Review such failures transparently; do not claim semantic
entailment or silently waive the gate. Full-instruction leakage checks do not
detect every conceivable rephrased disclosure. Micro citation validity alone
does not prove a claim is entailed; facts/source coverage supplement it.

Customer HTTP/SSE persistence/authenticated hosted browser behavior, real upload
extraction, Storage byte deletion, provider latency/concurrency and real security
under hostile model output remain outside this offline benchmark. Existing
provider error/security regressions test implementation safeguards, not live AI.

**9D not currently justified by measured evidence:** no resource, stream-load or
performance failure was observed in this phase; rough offline timings cannot
establish one. Phase 9A already measured atomic real-PostgreSQL final-slot races,
and 9B covered serial SSE/retry/cooldown journeys. They do **not** prove capacity
or multi-stream behavior. Complete the safe live 9C baseline first, then reassess
9D if measurements or a concrete expected-load requirement show a need. No 9D
or Phase 10 work was started.

Before Phase 10, complete the missing safe free-tier live Gemini/hosted retrieval
validation and real synthetic customer journey, review failures rather than
overfit prompts, and reassess load need. Phase 10 must separately verify current
free hosting, deployment secrets, CORS/Auth redirects, framing/CSP, logs and
public-demo bot/shared-quota/aggregate-budget risks. No deployment readiness or
live/provider completion is claimed.
