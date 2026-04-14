---
title: "openscribe-mcp: Composable Document-Understanding Primitives for Agent Systems"
authors:
  - name: "Adisak Sukul"
    affil: "Iowa State University"
    email: "asukul@iastate.edu"
  - name: "[TBD co-authors]"
venue_options:
  - "ACL 2027 System Demonstrations (4 pages)"
  - "EMNLP 2026 System Demonstrations (4 pages)"
  - "ACM UIST 2027 Demo"
  - "ACM IUI 2027 Demo"
  - "NAACL 2027 Demo track"
length_target: "4 pages (ACL/EMNLP demo)"
status: "draft v0.1"
last_update: "2026-04-12"
---

# Abstract

We present **openscribe-mcp**, the first adaptive OCR framework exposed as a Model Context Protocol (MCP) server for consumption by autonomous agents. openscribe-mcp wraps OpenScribe — an open-source cascade combining PaddleOCR, Tesseract, PDF text-layer extraction, and Claude vision — behind five composable tools: `ocr_page`, `ocr_pdf`, `chunk_semantic`, `detect_language`, and `evaluate_ocr_quality`. A single `~/.claude.json` entry exposes these tools to any MCP-speaking agent. We accompany the server with **ocr-thai-archival**, a Claude Skill package that ships pre-tuned configuration, prompt templates, and a quality threshold for historical Thai parliamentary documents (1934-present). To our knowledge this is the first adaptive OCR framework shipped as both an MCP server and a Claude Skill, and the first reusable document-understanding primitive for agent ecosystems. We demonstrate the system on the Parliamentary Repository of Thailand corpus, where a single agent request reads a century-old royal ceremonial document, preserves Buddhist-Era dates, and returns structured metadata for downstream retrieval — all without writing cascade-orchestration code.

# 1. Introduction

The gap between rich document-understanding pipelines and agent tool surfaces has grown faster than the tools themselves. A modern OCR system (hybrid classical + VLM cascade with adaptive routing and cost budgeting) contains a dozen moving parts, each of which must be installed, configured, credentialed, and orchestrated by hand. Agents that want to OCR a PDF must either (a) reimplement the cascade themselves, (b) shell out to a CLI and parse its output, or (c) limit themselves to whatever tool their framework ships by default — usually a single LLM vision call at a cost of ~USD 0.15 per page.

Model Context Protocol (MCP) is Anthropic's December 2024 open standard for exposing tools to LLM agents. An MCP server runs locally (stdio) or remotely (SSE) and advertises a set of callable functions with typed JSON schemas. Any MCP-aware agent (Claude Code, OpenAI Agents SDK, LangChain, CrewAI) can connect with one configuration line and immediately use the tools without writing glue code.

**openscribe-mcp** brings our adaptive OCR framework (OpenScribe main paper, in preparation — companion submission) into the MCP ecosystem. It exposes five document-understanding primitives:

1. `ocr_page(image_path, language, tenant)` — extract text from a single image via the adaptive cascade
2. `ocr_pdf(pdf_path, language, max_pages, tenant)` — extract text from every page of a PDF
3. `chunk_semantic(text, language, chunk_size, overlap)` — language-aware chunking
4. `detect_language(text)` — quick ISO 639-3 identification
5. `evaluate_ocr_quality(text, confidence, reference_text)` — intrinsic metrics plus optional CER

A Claude Code user adds a five-line config entry and immediately has the full OpenScribe cascade — PaddleOCR for cheap pages, Claude Opus on Vertex AI for rescue, fitz text-layer extraction as the zero-cost first stage — available to any conversation.

**Our contributions:**
- First OCR framework shipped as an MCP server
- **Lazy engine-loading pattern** that keeps metadata tools always-available even when heavy engines (PaddleOCR, Claude vision) are not installed
- **ocr-thai-archival** Claude Skill: a reference packaging for corpus-specific tuning
- Open-source reference implementation under a permissive license

# 2. System Overview

openscribe-mcp sits on top of the OpenScribe library (Figure 1). OpenScribe provides:
- **Engine interface**: abstract `Engine.extract(PageContext) -> OcrResult` with four concrete implementations (FitzEngine, PaddleEngine, TesseractEngine, ClaudeEngine)
- **Cascade**: confidence-gated early-stopping pipeline with dropout calibration and cost budgeting
- **Metrics**: intrinsic (script ratios, gibberish score) and extrinsic (CER, LLM-judge) quality scoring

openscribe-mcp adds a thin MCP-server layer:
- Async dispatch via the official `mcp` Python SDK
- JSON-schema-validated tool surface
- Tenant-aware config loading (one cascade per tenant, config via `TenantConfig` Pydantic schema)
- Lazy import of heavy engines to keep cold start under 200 ms

> **Figure 1:** Architecture. [TODO: insert diagram showing Agent → MCP client → stdio → openscribe-mcp → OpenScribe Pipeline → {Fitz, Paddle, Claude} → OcrResult back up the stack]

## 2.1 Lazy Engine Loading

A naive MCP server would construct the full OpenScribe pipeline at startup, which requires PaddleOCR (~2 GB of model weights), Claude auth, and GPU availability. Many agent environments have none of these. openscribe-mcp constructs engines on-demand inside the OCR tool handlers; metadata tools (`detect_language`, `chunk_semantic`, `evaluate_ocr_quality`) work immediately with only a `pythainlp` + `pymupdf` installation, while `ocr_page` and `ocr_pdf` raise clear errors directing the user to install heavy engines if needed.

This pattern (metadata tools always available, heavy tools loaded on first use) is a general contribution of this demo — we argue MCP servers should default to lazy construction to maximize deployability.

## 2.2 Tool Surface

Each tool is defined by a JSON schema matching the MCP specification. Example for `ocr_pdf`:

```json
{
  "name": "ocr_pdf",
  "description": "Extract text from every page of a PDF using the OpenScribe adaptive cascade...",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pdf_path": {"type": "string"},
      "language": {"type": "string", "default": "und"},
      "max_pages": {"type": "integer"},
      "tenant": {"type": "string", "default": "prt"}
    },
    "required": ["pdf_path"]
  }
}
```

Tool responses are JSON-in-TextContent (so any MCP client can parse them), carrying the per-page text, engine used, confidence, escalation reason, and cost.

# 3. Claude Skills Integration

A Claude Skill is a directory under `~/.claude/skills/<skill-name>/` containing a `SKILL.md` (with YAML frontmatter) and any configuration files the skill needs. When the Claude Code agent detects an intent matching the skill's description, it loads the skill's configuration and uses it to shape subsequent tool calls.

We ship **ocr-thai-archival** as the first reference skill:

```yaml
---
name: ocr-thai-archival
version: 0.1.0
description: OpenScribe skill pre-tuned for Thai archival documents —
  scanned parliamentary records, royal proclamations, typewriter-era bills,
  handwritten annotations, Buddhist-Era dates.
tags: [ocr, thai, archival, parliament, history, multilingual]
requires:
  - openscribe>=0.1.0
  - pythainlp
  - paddleocr
---
```

The skill's `config.yaml` specifies:
- Engine cascade: `fitz → paddle(th) → claude-opus-4-6(vertex)`
- Quality threshold: 0.80 (lower than default 0.85 because Thai scans are noisier)
- Dropout rate: 0.05 (for adaptive-controller calibration)
- Cost budget: USD 0.25 per page
- Prompt template for the Claude rescue stage, specifically tuned for 1930s Thai documents

When a user says something like *"OCR this old Thai parliamentary bill: /path/to/bill.pdf"*, Claude Code:
1. Matches the intent to `ocr-thai-archival`
2. Loads the skill's config
3. Invokes `ocr_pdf` on openscribe-mcp with `language="th"` and `tenant="prt"`
4. Streams per-page results back to the user

No glue code, no cascade setup, no model installation beyond the skill's declared requirements.

# 4. Example Use Case

We demonstrate end-to-end on a real archival document: a 1934 royal ceremonial program (`oai:prt.parliament.go.th:20.500.14156/218941`), *"หมายกำหนดการ พระราชพิธีเปิดประชุมสมัยสามัญสภาผู้แทนราษฎร แห่งราชอาณาจักรสยาม พุทธศักราช 2477"* — "Ceremonial program for the royal ceremony opening the ordinary session of the House of Representatives of the Kingdom of Siam, Buddhist Era 2477 (1934 CE)".

User request (inside a Claude Code session):

> Read the PDF at `/prt/pdfs/20_500_14156__218941.pdf` and tell me when the ceremony was held.

Claude Code matches the skill, invokes `ocr_pdf`, and gets back:

```json
{
  "pdf_path": "/prt/pdfs/20_500_14156__218941.pdf",
  "n_pages": 3,
  "total_cost_usd": 0.28,
  "pages": [
    {
      "page_id": "218941:p0",
      "text": "หมายกำหนดการ\nพระราชพิธีเปิดประชุมสมัยสามัญ\nสภาผู้แทนราษฎร\nแห่งราชอาณาจักรสยาม\nพุทธศักราช 2477",
      "confidence": 0.91,
      "engine": "paddle",
      "escalation_reason": "quality_met",
      "cost_usd": 0.0
    },
    {
      "page_id": "218941:p1",
      "text": "[stamp: ตราครุฑ]\n...ประกาศ ณ วันที่ 16 ธันวาคม พุทธศักราช 2477...",
      "confidence": 0.87,
      "engine": "claude",
      "escalation_reason": "quality_met",
      "cost_usd": 0.14
    }
  ]
}
```

Claude reads the output, recognizes that page 0 had a text layer the paddle engine handled for free, page 1 required LLM rescue due to a ceremonial seal and handwritten annotation that PaddleOCR couldn't resolve, and the ceremony date is 16 December 1934 (Buddhist Era 2477). The user gets an accurate answer; the agent invested USD 0.28 end-to-end; and no OCR code was written or configured by the user at any point.

The same agent, with no additional code, can now OCR a concrete-sustainability PDF from a different tenant (`tenant=isu`, English-focused cascade) or a mixed-script Cabinet minute (`tenant=prt`, which defaults to Thai but detects English segments automatically).

# 5. Implementation Details

## 5.1 Transport & Protocol

openscribe-mcp uses the stdio transport from the official `mcp` Python SDK (v1.27+). The server starts with `python -m research_platform.ocr.mcp`, advertises its tools via the `list_tools` RPC, and responds to `call_tool` requests with JSON output wrapped in MCP `TextContent` objects. An SSE transport variant is available for remote-agent use cases but is not the default.

## 5.2 Tenant Configuration

Each tool call optionally carries a `tenant` argument. The server maps this to a `TenantConfig` via our Pydantic schema, which specifies the engine stack, language defaults, GCP project for Vertex calls, and filesystem layout. Changing tenants at the tool level allows a single server to serve multiple institutional corpora without restart.

## 5.3 Error Surface

Every tool call returns a JSON object; errors are returned as `{"error": "..."}` rather than raising protocol-level exceptions. This matches the MCP guidance to keep errors in-band so agents can reason about them rather than crashing.

## 5.4 Cold Start

Cold-start latency for `create_server()` + `list_tools()` + first metadata tool is **under 200 ms** on our Windows 11 workstation with Python 3.12. First call to `ocr_page` on a PDF with existing text layer takes ~300 ms end-to-end. First call to `ocr_page` that triggers Claude rescue takes ~8 s (dominated by network round-trip to Vertex AI).

# 6. Evaluation

## 6.1 Deployment Friction

We measured **lines of configuration** needed to integrate openscribe-mcp with Claude Code, compared to writing a custom cascade from scratch:

| Approach | LoC | Dependencies |
|---|---:|---|
| Write cascade from scratch | ~400 | paddleocr + anthropic + qdrant + ... |
| Call individual libraries directly | ~150 | same |
| openscribe-mcp (our contribution) | **5** | mcp + openscribe |

Five lines: a JSON object in `~/.claude.json` under `mcpServers`. The agent takes over from there.

## 6.2 Tool Call Latency Breakdown

[TODO: measure tool call latency distributions on a sample of 100 archival documents, report p50/p95/p99 for each tool. Pending PRT origin returning to collect real benchmark data. Interim: synthetic latency on a held-out ISU corpus.]

## 6.3 Metadata Tools in Engine-Free Environment

We verified all metadata tools (`detect_language`, `chunk_semantic`, `evaluate_ocr_quality`) work on a bare `python -m pip install mcp pythainlp pymupdf` installation, with no PaddleOCR, no CUDA, no Anthropic credentials. This is the lazy-loading property: metadata tools are always available, heavy OCR tools require their engines to be installed before first call.

# 7. Related Work

**MCP tooling ecosystem** is under 18 months old. Anthropic announced the Model Context Protocol [mcp2024] in November 2024 as an open standard for connecting LLM applications to external data sources and tools; since then the ecosystem has grown to thousands of servers for filesystem, git, GitHub, browser automation, and database access. Document-understanding servers exposing adaptive OCR cascades do not yet exist in the public catalog, which is the gap this demo fills.

**OCR libraries** have mostly ignored agent integration. PaddleOCR [du2020ppocr] and Tesseract [smith2007tesseract] are the two dominant open-source engines. EasyOCR and commercial services (AWS Textract, Google Document AI) ship SDKs and REST APIs but not MCP servers. We are aware of no prior work exposing an OCR cascade as an MCP primitive.

**Adaptive OCR cascades** are discussed in our companion OpenScribe paper [openscribe-main-paper in preparation]. Prior work on ensemble OCR — Wemhoener et al. [wemhoener2013multi] on aligning noisy OCR output from multiple book editions, and Lund et al. [lund2014multi] on CRF-based OCR error correction that generalizes across data sets — targets accuracy improvement on a fixed corpus but does not consider cost-aware routing or agent integration.

# 8. Limitations & Future Work

- **Single-server-per-workstation**: the default stdio transport binds one server to one client process. For multi-user deployments we recommend the SSE transport variant, but we have not yet benchmarked it.
- **No streaming output**: `ocr_pdf` returns all pages at once. Long PDFs cause long latencies. Future work: stream per-page results as MCP notifications.
- **Single tenant per call**: calling across tenants requires a new tool invocation. Multi-tenant single-call aggregation would be a natural extension.
- **Claude Skills beyond Thai**: we ship one skill (`ocr-thai-archival`). Future skills: `ocr-mixed-script`, `ocr-handwritten-english`, `ocr-tables-forms`, `ocr-medieval-manuscripts`.

# 9. Conclusion

openscribe-mcp is the first OCR framework shipped as an MCP server. It is five lines of config away from any MCP-aware agent. It preserves the adaptive cost-quality routing of the underlying OpenScribe cascade while hiding its orchestration complexity. Combined with the `ocr-thai-archival` Claude Skill, it demonstrates how corpus-specific tuning can be packaged and distributed as a reusable artifact, lowering the barrier for institutions to deploy high-quality hybrid OCR without writing a line of orchestration code.

The server and the Thai archival skill are open-source. We invite the community to contribute additional skills for their own corpora.

# References

See `papers/references.md` for the shared verified bibliography. Cited in this paper:

- **[mcp2024]** Anthropic. 2024. *Model Context Protocol.* Open standard, announced November 2024. https://modelcontextprotocol.io
- **[du2020ppocr]** Du et al. 2020. *PP-OCR: A Practical Ultra Lightweight OCR System.* arXiv:2009.09941.
- **[smith2007tesseract]** Smith 2007. *An Overview of the Tesseract OCR Engine.* ICDAR 2007, pages 629-633. DOI:10.1109/ICDAR.2007.4376991.
- **[wemhoener2013multi]** Wemhoener, Yalniz, Manmatha 2013. *Creating an Improved Version Using Noisy OCR from Multiple Editions.* ICDAR '13.
- **[lund2014multi]** Lund, Ringger, Walker 2014. *How Well Does Multiple OCR Error Correction Generalize?* DRR 2014.
- **[pymupdf]** PyMuPDF (fitz) — https://github.com/pymupdf/PyMuPDF
- **[qdrant]** Qdrant — https://github.com/qdrant/qdrant
- **[openscribe-main]** OpenScribe main paper (companion submission, in preparation).

---

## Writing TODO

- [ ] Architecture diagram (Figure 1)
- [ ] Tool call latency measurements on real PRT/ISU data (pending PRT origin)
- [ ] Video/screencast for demo session
- [ ] Link to public GitHub repo
- [ ] Ethics statement (public parliamentary corpus, Thai language preservation)
- [ ] Shortened abstract to 150 words for demo format
- [ ] Check ACL demo page limit (4 pages main + 2 pages references)
