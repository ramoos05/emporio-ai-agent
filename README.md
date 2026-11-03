# Bia — Empório da Música

Python customer-service agent for the Artefact AI Engineer technical challenge. It combines OpenAI function calling, structured CSV queries and section-based retrieval of store policies. The CLI is intentional: the challenge permits a terminal interface and focuses on correct agent behavior.

## Status and evidence

The candidate ran the OpenAI integration locally and supplied saved conversations. `examples/` contains five actual excerpts from that session, with tool evidence and review notes; these are not five independently executed sessions. Portuguese source transcripts are preserved without rewriting model output. Some responses contain identified issues. The latest prompt revision addresses them, but has not been rerun against a live model here. Automated tests use a simulated client and do not establish LLM answer quality.

Before submission, run `scripts/gerar_exemplos.py`, inspect all five new conversations, and provide English translations for the submission document. The script replaces the excerpts with five fresh scenarios. Do not claim that a failed scenario passed.

## Requirements and setup

Python 3.11+, an OpenAI API key with model access, and Git for publication. Default model: `gpt-4.1-mini`; override using `EMPORIO_MODEL`.

Windows PowerShell, from this directory:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` locally:

```dotenv
OPENAI_API_KEY=your_api_key
EMPORIO_MODEL=gpt-4.1-mini
```

Then run:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m emporio --verbose
.venv\Scripts\python.exe scripts/gerar_exemplos.py
```

`/sair` exits; `/novo` starts a new session. `--session demo` resumes that session; `--model MODEL_ID` overrides the model. Verbose output displays tool arguments and results, so only use fictional customer information in demonstrations.

On Linux/macOS, replace `.venv\Scripts\python.exe` with `.venv/bin/python` and use `cp .env.example .env`.

## Architecture and decisions

A customer message enters the CLI. The agent sends the system instructions, recent history and tool schemas to OpenAI Chat Completions. The model selects tools; Python executes them and sends results back. The model then produces a response. The loop is capped at six rounds; incomplete turns are rolled back on API failure.

| Module | Responsibility |
|---|---|
| `agent.py` | OpenAI tool loop, history window and legacy-session migration |
| `tools.py` | Catalog, promotions, orders, policies, calculations and local handoff |
| `data.py` | CSV loading, normalization and business data |
| `policies.py` | Lexical ranking of policy sections |
| `prompts.py` | Persona, scope, factual constraints and business hours |
| `config.py` | Environment configuration, loaded after `.env` |
| `storage.py` | Atomic local JSON session persistence |
| `cli.py` | Terminal interaction |

**Function calling instead of an SQL agent:** seven purpose-specific tools expose only the required operations. No model-generated SQL or Python is executed. A small explicit loop avoids unnecessary orchestration dependencies.

**OpenAI model:** configurable model with native tools. `gpt-4.1-mini` is the default configuration, not a benchmark winner. Real latency, cost and accuracy must be measured; no comparative benchmark was performed. The Anthropic integration from the earlier version has been replaced.

**Policy retrieval:** the original PDF and its Markdown transcription are included. Sections are ranked through normalized lexical overlap, lightweight stemming, domain synonyms and title weights. This avoids embeddings and vector infrastructure for a small manual. It may miss unfamiliar paraphrases. Internal sections 7 and 10 are excluded from retrieval; relevant behavioral rules are in the prompt.

**Structured data:** CSVs are loaded at startup and cached in memory. They are a historical snapshot, not a live inventory integration. JSON specifications are parsed; product status and stock jointly determine availability. A discontinued or coming-soon product is not sellable even with positive stock. `is_active` determines promotions because validity dates are absent. The highest active promotion wins; PIX does not stack with it.

**Conversation state:** local JSON sessions with atomic writes; up to 40 messages are sent to the model, cutting at a customer turn to preserve tool-call/result pairs. Session files contain customer input and tool evidence. They are excluded from delivery and Git.

**Order access:** order number plus matching email/phone is a demonstration-level identity check, not production authentication. Unknown orders and mismatched identity return the same error. Three failed attempts block the current session; starting another session can bypass this limit. Production needs authentication and authorization outside the LLM.

**Post-sale rules:** estimated delivery never establishes receipt. The agent asks for purchase channel and actual receipt date before confirming cancellation eligibility. Internal 30-day defect exchange is measured from purchase; it does not eliminate the separate warranty. The assistant cannot approve refunds or cancel orders.

## Assumptions and limitations

- The catalog budget filter uses the current promotional/table price, before PIX.
- Promotion dates are unavailable: only the active flag is authoritative.
- Order totals are preserved even if they differ from item sums.
- Installment rules follow detailed section 3.1: minimum R$50 up to 3 installments, R$80 for 4–6, R$100 for 7–12. This is a documented interpretation of conflicting summary text.
- Regional shipping covers Campo Grande only because municipalities are not listed. Exactly R$500 is interpreted as R$35 shipping; amounts above R$500 qualify for free shipping. Confirm these interpretations with the business before production.
- The manual has conflicting contact numbers. This prototype uses (67) 3341-4444 and the email spelling without an accent; the conflict remains a business clarification.
- Business hours do not include an automatic holiday calendar.
- Handoff creates a local JSONL record only. It does not notify staff or guarantee a callback. Responses must identify the simulation.
- Monetary calculations use rounded floats. Production needs Decimal and exact installment reconciliation.
- Prompt instructions reduce but do not guarantee protection against prompt injection or hallucination.
- The broad API exception fallback does not expose diagnostic details. Structured, redacted logging would improve troubleshooting.
- Data is sent to the model provider. Production requires privacy review, data minimization, retention controls and appropriate access protection.

## Evaluation and follow-up

The supplied implementation passed 50 automated tests during review. Tests cover loading, tools, retrieval, mocked OpenAI interaction, persistence, configuration and date regressions. They do not call the real API.

Review of supplied live transcripts found: (1) displayed results confused with total matches; (2) online-purchase qualification omitted from a return response; (3) an outdated delivery estimate presented without explaining its age; and (4) payment summary not distinguishing all installment bands. The revised prompt explicitly addresses these issues. They require a live regression run before claiming resolution.

Future work: a fixed evaluation set with factual checks, authentication independent of the LLM, deterministic return calculations from confirmed dates, Decimal accounting, real handoff notifications, holiday support and privacy-preserving telemetry.

## AI assistance and provenance

The initial supplied version declared Claude Code assistance. ChatGPT/Codex reviewed and revised configuration, post-sale handling, documentation and tests. The candidate supplied a working OpenAI adaptation and live session records. This review preserved those records and identified weaknesses rather than presenting edited answers as actual model output. The candidate should verify this statement and describe their own review and validation work accurately.

## Submission

The recruiter email requests English answers and a PDF uploaded through Google Forms. The technical brief also requires a public Git repository and 3–5 example conversations. Submit an English PDF containing the real public repository URL, architecture, decisions, validation and limitations, together with translated conversation evidence. The original store-facing dialogue may be retained in Portuguese alongside translations.

Preserve the Git history and commit further work honestly. Never commit `.env`, `.venv` or private sessions. Create a public empty repository, configure its URL as `origin`, then push `main`. Confirm access from a signed-out browser. Do not modify the repository after the submission deadline.

The final PDF needs the published repository URL and the results of the latest live validation; those are not available in this package yet.
