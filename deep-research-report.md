# RAG Assistant with Governance & Security by Design

## Why this project is portfolio-relevant in 2026

A “RAG assistant” is already a strong portfolio signal because it demonstrates end-to-end, production-shaped skills: data ingestion, search/retrieval, LLM integration, UX, and deployment. Adding **governance & security by design** turns it into a rarer signal: you are not just building a demo chatbot, you are building an application that anticipates real organizational constraints (privacy, access control, auditability, observability, and regulatory pressure). citeturn30search0turn31search2turn31search3

From a European market lens, the **EU AI Act timeline** is an important backdrop: according to the entity["organization","European Commission","eu executive body"], the AI Act entered into force on **1 August 2024**, and is fully applicable on **2 August 2026**, with earlier milestones including (a) prohibited AI practices and AI literacy obligations applying from **2 February 2025**, and (b) governance rules and obligations for general-purpose AI models applying from **2 August 2025**. citeturn31search3  
Even if your personal project is not marketed as a compliance product, aligning your design with this “governance maturity” is portfolio-friendly because it mirrors what employers increasingly ask: “Can you ship AI features safely?” citeturn31search3

On the **security** side, the entity["organization","OWASP Foundation","web app security nonprofit"] Top 10 for LLM applications explicitly documents risks like prompt injection, insecure output handling, training data poisoning, model denial of service, and supply-chain vulnerabilities. That list maps directly to features you can implement and demonstrate: input/output controls, retrieval isolation, rate limiting, dependency scanning, red teaming, and audit trails. citeturn30search0turn30search3

On the **risk management** side, the entity["organization","National Institute of Standards and Technology","us standards agency"] AI RMF frames AI risk management across the lifecycle and positions trustworthiness as a design objective—not an afterthought. Translating that philosophy into an engineering artifact (your project) is both educational and marketable. citeturn30search2turn30search6

## Project scope and reference architecture

**Project purpose (portfolio narrative):**  
Build a local-first, open-source RAG assistant for “internal knowledge” that demonstrates **secure-by-default AI application engineering**: document ingestion, permissioned retrieval, traceable answers with citations, PII handling, developer-grade observability, and an automated security/evaluation workflow. citeturn30search0turn31search3turn48view0

**Target user story:**  
A small team wants to upload internal PDFs/notes, ask questions, receive grounded answers with source citations, and maintain an audit trail showing what was accessed and why. The system must prevent cross-workspace leakage and reduce accidental exposure of sensitive data. citeturn30search0turn48view0

**MVP scope (what you should ship early):**
- Upload documents (PDF + markdown/text at minimum) → parse → chunk → embed → store.
- Chat/search UI returning answers **with citations** (chunk-level evidence).
- Workspaces + authentication + role-based document access (at least Admin vs Member).
- Minimal governance UX: document inventory, data classification label, and audit log for queries and retrieval events.
- Telemetry: traces + metrics + structured logs (enough to debug RAG failures and latency). citeturn24view3turn40view0turn42view1turn13search6

**Progressive enhancement (portfolio depth layers):**
- PII detection/redaction pipeline (ingestion-time and/or response-time).
- Prompt-injection–aware system prompt + retrieval isolation (e.g., never treat retrieved text as instructions).
- Automated LLM security testing/red teaming + evaluation in CI.
- SSO/OIDC integration (optional “enterprise mode”).
- Self-host deployment profile with reverse proxy and HTTPS. citeturn30search0turn32view0turn46view0turn11view0turn21search1turn21search4

**Reference architecture (implementation-neutral):**

_Ingestion path_  
User → Upload → Parser → Chunker → Embedder → Vector store + metadata store → Audit event

_Query path_  
User → AuthN/AuthZ → Query policy checks → Retrieve (vector + optional keyword) → (optional rerank) → LLM generate answer → Citations + redaction layer → Response → Telemetry + audit event

**Key design choice that makes this “governance & security” (not just RAG):**  
Treat the RAG system like a normal enterprise application: every access is scoped (workspace, role), every retrieval has a trace/audit record, and every model call is observable and testable. citeturn30search0turn31search2turn48view0

## Recommended open-source stack and alternatives

### Confirming the baseline stack

Your proposed baseline—**Python (FastAPI), TypeScript (Next.js/React), PostgreSQL + vector extension, Docker, OpenTelemetry**—is coherent and industry-aligned:

- **FastAPI** is MIT-licensed and explicitly positioned as modern, high-performance, and “easy to learn,” with OpenAPI-based interactive docs—useful both for learning and for a portfolio-grade API surface. citeturn24view3turn23view3
- **Next.js** (MIT) is a widely adopted React framework and comes with extensive official documentation and community channels; the repository and docs emphasize real-world use and production workflows. citeturn24view2turn23view2
- **React** is MIT-licensed and extremely widely used, making your UI skills maximally legible to recruiters. citeturn45search4turn45search0
- **TypeScript** is Apache-2.0 licensed and is a de facto standard for serious frontend (and increasingly full-stack) work. citeturn45search1turn45search5
- **PostgreSQL** uses the PostgreSQL License (permissive) and has a stable governance and “no plans to change license” statement—important for long-term portfolio projects. citeturn40view0
- **pgvector** is a popular Postgres extension for vector similarity search; third-party documentation (e.g., EnterpriseDB docs) states it is released under the PostgreSQL License, and the GitHub repo shows large adoption. citeturn44search2turn42view1
- **OpenTelemetry instrumentation for FastAPI** exists as a maintained package, allowing you to build proper traces/metrics without vendor lock-in. citeturn13search6turn45search10
- Containerization is a good fit for reproducibility. Docker Engine is described as open source and supported by the Moby project community, while Docker Desktop has separate licensing terms—relevant when your goal is “as open-source as possible.” citeturn41search7turn41search16turn41search1

### Comparative tool tables

The tables below use: **License** (as stated by official repos/docs), **Community proxy** (GitHub stars/forks as of early Feb 2026 in the cited sources), and qualitative scores for **Docs** and **Ease** based on the maturity and “getting started” materials surfaced by official documentation and README structure (not a scientific measure, but a practical heuristic). citeturn24view3turn23view2turn42view1turn13search6

#### RAG orchestration framework options

| Option | License | Community proxy | Docs & learning | Fit for this project |
|---|---|---:|---|---|
| LangChain | MIT citeturn24view0 | 126k stars / 20.7k forks citeturn24view0 | Very large ecosystem; can become complex quickly citeturn24view0 | Strong “market recognition,” especially if you also add evaluation + security testing |
| LlamaIndex | MIT citeturn2search2 | 46.8k stars / 7.5k forks citeturn2search2 | Purpose-built for data + retrieval, generally straightforward for RAG tasks citeturn2search2 | Excellent for ingestion/retrieval pipelines without committing to heavy agent frameworks |
| Haystack | Apache-2.0 (plus “unknown licenses found” flagged by GitHub) citeturn24view1 | 24.1k stars / 2.6k forks citeturn24view1 | Emphasizes explicit pipelines, recipes, and production positioning citeturn23view1 | Strong “production-shaped” narrative; good if you want a clean pipeline-driven architecture |

**Recommendation for your portfolio goal:** pick **LlamaIndex** as the primary orchestration layer for ingestion + retrieval because it is specialized for RAG and has strong adoption, while keeping your own “governance/security envelope” (authz, audit, PII, telemetry) as first-class application code. This lets you demonstrate both practical speed and engineering ownership. citeturn2search2turn30search0turn48view0

#### Vector database / vector store options

| Option | License | Community proxy | Ops complexity | Fit for this project |
|---|---|---:|---|---|
| pgvector (inside PostgreSQL) | PostgreSQL License citeturn44search2 | 19.6k stars / 1k forks citeturn42view1 | Lowest (single DB for metadata + vectors) citeturn42view1 | Best default for “low cost, real-world, integrated” RAG; excellent for a solo portfolio project |
| Qdrant | Apache-2.0 citeturn4view0 | 24.1k stars / 1.6k forks citeturn4view0 | Medium (separate service) | Strong if you want to showcase a dedicated vector DB (common in production) |
| Weaviate | BSD-3-Clause citeturn4view1 | 14.6k stars / 1k forks citeturn4view1 | Medium–High | Feature-rich; can become “platform-like” for a personal project |
| Milvus | Apache-2.0 citeturn5view0 | 34.8k stars / 3.3k forks citeturn5view0 | High | Powerful, but heavier operationally; best if you want to learn distributed systems/tooling |

**Recommendation:** start with **PostgreSQL + pgvector** (lowest operational overhead; still very “real world”), then optionally add an “adapter layer” to support Qdrant as a stretch goal to demonstrate portability. citeturn40view0turn44search2turn4view0

#### LLM inference & embeddings stack

| Component | Recommended option | License | Community proxy | Why it fits the “free / OSS” goal |
|---|---|---|---:|---|
| Local LLM runtime | llama.cpp | MIT citeturn2search0 | 82.8k stars / 12.2k forks citeturn2search0 | Widely used for local inference and supports GGUF-style quantized models; great for cost control |
| Python binding | llama-cpp-python | MIT citeturn28search2 | 9.9k stars citeturn28search2 | Clean integration path into FastAPI without paid APIs |
| High-throughput server (optional) | vLLM | Apache-2.0 citeturn2search6 | 41.1k stars citeturn2search6 | Excellent if you have GPU access and want to demonstrate scalable inference patterns |
| Embeddings + reranking | Sentence Transformers | Apache-2.0 citeturn29view0 | 18.2k stars citeturn29view0 | Extremely practical: embeddings + cross-encoder rerankers in one ecosystem |
| Model/ML library backbone | Transformers | Apache-2.0 citeturn28search4 | 156k stars citeturn28search4 | Industry standard for model loading/training; strong portfolio signal |

**Important licensing nuance (weights vs code):** most of the tooling above is permissively licensed, but **model weights** can be under a wide variety of terms. Use a hub like entity["company","Hugging Face","ai platform company"] to select models and explicitly check their license metadata before distributing anything with your repo/demo. citeturn28search12turn29view0

#### Document ingestion / parsing pipeline

| Option | License | Community proxy | Strengths | When to use |
|---|---|---:|---|---|
| Unstructured | Apache-2.0 citeturn27view0 | 13.9k stars citeturn27view0 | End-to-end preprocessing for many document types; designed for LLM ingestion workflows citeturn26view0 | Best default if you want broad document coverage quickly |
| pypdf | BSD-3-Clause citeturn25search3 | (PyPI project; license stated) citeturn25search3 | Lightweight PDF text extraction | Good for a simpler PDF-only MVP |
| pdfplumber | MIT citeturn25search5 | 9.6k stars citeturn25search5 | Better layout/table extraction for machine-generated PDFs | Useful if you want “better than naive PDF text” without a heavy stack |
| Apache Tika | Apache-2.0 citeturn25search2 | (ASF project license page) citeturn25search2 | Broad file type extraction engine (server/CLI/library) | Great if you want “enterprise-style” ingestion for many formats |

**Recommendation:** use **Unstructured** for breadth and learning value, with a fallback path using pypdf/pdfplumber for “boring but reliable” PDF ingestion. citeturn27view0turn25search3turn25search5

#### Security, evaluation, and DevSecOps toolchain

| Goal area | Tool | License | Community proxy | What you will demonstrate |
|---|---|---|---:|---|
| PII detection/redaction | Presidio | MIT citeturn48view0 | 6.8k stars citeturn48view0 | Real privacy controls: detect/anonymize sensitive entities in text citeturn48view0 |
| LLM security scanning | garak | Apache-2.0 citeturn32view0 | 6.9k stars citeturn32view0 | Practical red-teaming mindset and automated jailbreak/prompt-injection checks citeturn32view0 |
| Prompt/RAG evaluation + red teaming | promptfoo | MIT citeturn46view0 | 10.2k stars citeturn46view0 | Repeatable evaluation and “quality gates” in CI citeturn46view0 |
| Guardrails (policy layer for LLM behavior) | NeMo Guardrails | Apache-2.0 citeturn7view1 | 5.6k stars citeturn7view1 | Policy-constrained responses and safer LLM app behavior |
| Secrets scanning | Gitleaks | MIT citeturn38view1 | 24.8k stars citeturn38view1 | Prevent accidental credential leaks in a public portfolio repo |
| Vulnerability & misconfig scanning | Trivy | Apache-2.0 citeturn38view0 | 31.2k stars citeturn38view0 | Container/IaC/dependency scanning posture |
| Dependency vulnerability scan | OSV-Scanner | Apache-2.0 citeturn36search3 | 8.4k stars citeturn36search3 | “Supply chain aware” practice aligned with OWASP concerns citeturn30search0 |
| SBOM generation | Syft | Apache-2.0 citeturn37view2 | 8.3k stars citeturn37view2 | Modern compliance artifact (SBOM) and reproducibility discipline |

**Security framework anchor (non-code):** explicitly map your controls to OWASP’s LLM Top 10 categories (e.g., prompt injection, insecure output handling, supply chain) and cite that mapping in your README. This is a strong differentiator because it turns features into a structured security story. citeturn30search0turn30search3

#### Observability stack

| Layer | Tooling | License / community proxy | Why it’s worth it in a portfolio |
|---|---|---|---|
| Instrumentation standard | OpenTelemetry (collector + instrumentation) | Collector is Apache-2.0; ~6.6k stars for the collector repo citeturn13search5turn45search10 | Demonstrates vendor-neutral telemetry and professional debugging practices |
| FastAPI auto-instrumentation | opentelemetry-instrumentation-fastapi | (Package exists and is documented) citeturn13search6 | Shows you can trace request → retrieval → LLM generation end-to-end |
| Metrics storage | Prometheus | Apache-2.0; 58.8k stars citeturn12search0 | Industry-standard metrics; supports SLO-style thinking |
| Dashboards | Grafana | AGPL-3.0; 70.9k stars citeturn12search4 | Skill signal: dashboards and operational visibility |
| Tracing backend | Jaeger | Apache-2.0; 24.1k stars citeturn12search2 | Clear, visual trace exploration for RAG latency debugging |

## Implementation roadmap and agile action plan

This section is written as a reusable “analysis document” you can place into your repo (e.g., `docs/PROJECT_ANALYSIS.md`) with minimal edits.

**Project objectives (measurable):**
- Deliver an MVP that supports document upload + permissioned RAG answers with citations and a minimal governance UI.
- Demonstrate a real engineering loop: build → observe → test → harden (security + eval) → iterate.
- Ship a portfolio-grade repository: reproducible setup, automated checks, and clear documentation. citeturn24view3turn30search0turn38view0turn38view1turn46view0

**Success criteria (definition of “portfolio-ready”):**
- One-command local run (Docker compose or equivalent), producing a working UI + API.
- At least one curated demo dataset and a scripted ingest + Q&A scenario.
- Audit log captures: user, workspace, docs retrieved, and request/trace id.
- Basic evaluation suite (promptfoo) runs in CI and blocks regressions.
- Security checks (Gitleaks + Trivy + OSV + SBOM) run automatically in CI. citeturn38view1turn38view0turn36search3turn37view2turn46view0

**Agile workflow diagram (simple, repeatable loop):**  
Backlog → Sprint plan → Build small slice → Instrument & log → Test/evaluate → Demo → Retrospective → Next slice citeturn13search6turn46view0

**Milestone plan (realistic at ~8 hours/day):**

| Timebox | Milestone | Key deliverables | Exit criteria |
|---|---|---|---|
| Days 1–3 | Foundations | Repo scaffold; Docker dev environment; DB schema skeleton; CI pipeline baseline | `make up` (or equivalent) starts API + DB; CI runs unit tests |
| Week 1 | Vertical slice MVP | Upload → ingest → embeddings → retrieval → answer with citations | End-to-end demo works on a small dataset; sources are displayed |
| Week 2 | Governance MVP | Auth; workspaces; RBAC; audit logging | Cross-workspace access blocked; audit log shows retrieval events |
| Week 3 | Observability & reliability | OpenTelemetry traces; Prometheus metrics; basic dashboards; rate limiting | Trace shows request path; metrics visible and documented citeturn13search5turn12search0turn12search4turn13search6 |
| Week 4 | Security & privacy hardening | PII detection/redaction; secret scanning; vulnerability scans | PII feature demo; CI fails on leaked secrets/vulns citeturn48view0turn38view1turn38view0turn36search3turn37view2 |
| Week 5 | Evaluation & red teaming | promptfoo evaluation sets; garak security runs; baseline score tracking | Reproducible eval results; documented safety tests citeturn46view0turn32view0 |
| Week 6 | Portfolio release | Polished README; architecture diagram; demo video script; release tag | Clean “portfolio landing page” documentation and stable demo run |

**Backlog structure (so you can work iteratively without getting lost):**
- “Core RAG”: ingestion, chunking, embedding, retrieval, citation rendering.
- “Governance”: auth, workspace isolation, policy rules, audit events, retention.
- “Security”: PII controls, prompt-injection countermeasures, dependency supply chain checks per OWASP categories.
- “Ops”: telemetry, dashboards, performance budgets, deploy profile.
- “Quality”: automated evaluation, regression tests, documentation. citeturn30search0turn46view0turn38view0turn38view1

## Portfolio packaging and evidence of impact

To maximize portfolio impact, plan for **artifacts** that recruiters can skim in minutes and deeper evidence that senior reviewers can validate.

**Repository structure that reads like a product:**
- `README.md`: problem statement, security stance, quickstart, screenshots/GIFs, and architecture.
- `docs/`: threat model, governance model, evaluation results, and telemetry screenshots.
- `examples/`: scripts to ingest a sample dataset and run “golden queries” that demonstrate citations and governance boundaries.

**Show—not just tell—governance & security:**
- Include a screenshot/demo narrative where:
  - User A uploads “confidential HR policy” in Workspace A.
  - User B in Workspace B cannot retrieve it (prove isolation).
  - Admin can see audit events and traces for the request. citeturn30search0turn13search6

**Quantifiable metrics to publish (simple but credible):**
- Retrieval latency p50/p95 (from Prometheus/Grafana).
- “Citation coverage” (percentage of answers with at least N cited chunks).
- PII detection counts on the demo dataset (before/after redaction).
- Evaluation score trend over time (promptfoo reports stored as artifacts). citeturn12search0turn12search4turn48view0turn46view0

**A strong final deliverable:**  
A short “engineering case study” section tying your design to recognized frameworks: cite OWASP LLM Top 10 categories you mitigated and reference the EU AI Act timeline as motivation for governance readiness (without claiming legal compliance). citeturn30search0turn31search3

## Risks, trade-offs, and cost containment

**Cost containment strategy (practical tiers):**
- **Tier 0 (no spend):** run everything locally; use llama.cpp + quantized models; keep demo dataset small; publish a recorded demo video.
- **Tier 1 (minimal spend):** self-host on a small server using open-source deployment tooling (reverse proxy + Docker Compose), so the only cost is commodity hosting.
- **Tier 2 (convenience):** optionally use free tiers for hosting, but keep the core deploy path vendor-neutral via containers and environment-based config. citeturn2search0turn21search1turn21search2turn21search3

**Licensing pitfalls to explicitly manage:**
- **Tooling vs weights:** your stack can be permissively licensed, while model weights may have additional constraints. Always record model license metadata in your docs and avoid redistributing restricted weights. citeturn28search12turn2search0turn29view0
- **Docker Desktop vs open-source runtime:** Docker Engine is described as open source and community-supported, but Docker Desktop has separate licensing terms; for a fully open-source toolchain on your workstation you can use Podman (Apache-2.0). citeturn41search7turn41search16turn41search9
- **Caching/queue broker licensing:** Redis licensing changed for newer versions, while the entity["organization","Linux Foundation","open source nonprofit"] launched Valkey as a BSD-licensed fork to preserve an open-source path; if you introduce a queue/broker, Valkey is a safer “open” default going forward. citeturn33search3turn34search6turn35view0

**Technical trade-offs to document (turn risks into portfolio strength):**
- **RAG correctness is not guaranteed.** Your portfolio value increases if you show evaluation + telemetry + mitigations rather than claiming perfection. The OWASP list explicitly highlights risks like prompt injection and supply chain vulnerabilities—use that to justify your controls and tests. citeturn30search0turn32view0turn46view0
- **PII detection is probabilistic.** Presidio itself warns that automated detection cannot guarantee catching all sensitive information—so your governance story should include layered protections (access controls, redaction, and safe defaults). citeturn48view0
- **Operational complexity can eat your time.** Starting with PostgreSQL + pgvector keeps the system coherent and minimizes services while still being production-relevant; adding a second vector DB later is a deliberate “advanced portability milestone,” not an MVP requirement. citeturn40view0turn44search2turn4view0