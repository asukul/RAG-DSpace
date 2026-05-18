---
name: opus-typhoon-hybrid-ocr
description: OCR Thai government / parliamentary PDFs by combining Typhoon-OCR 1.5 (Thai-specialized, oracle-grade character recognition) with Claude Opus's image-understanding for layout, table structure, and post-correction. Typhoon recognizes the characters; Claude verifies against the image and corrects errors (mis-OCR'd vowels, tone marks, broken table cells, dropped lines).
metadata:
  type: ocr
  language: thai-english
  pattern: hybrid-vlm-post-correction
  base_model: typhoon-ocr1.5-3b (SCB 10X, Qwen2.5-VL fine-tune)
---

# Opus + Typhoon Hybrid OCR — Thai government / parliamentary documents

## When to use this skill

Use this skill to OCR pure-scan Thai PDFs where:

- The PDF is image-only (no extractable text layer) — typical for parliamentary scans
- You need accuracy higher than vanilla Claude vision (which under-trains on Thai characters)
- You need accuracy potentially higher than Typhoon-OCR alone (catches Typhoon's systematic errors)
- Cost-per-page is acceptable (~$0.01-0.05 in Claude usage + ~free local Typhoon)

Do NOT use this skill for:

- Born-digital PDFs with text layer — use `opus-anchor-ocr` skill instead (cheaper, no Typhoon call needed)
- Single-language English documents — vanilla Claude vision is sufficient
- Volume runs where Typhoon-alone meets quality bar — adding Claude doubles cost for marginal gain

## Inputs you will receive

1. **Page images** (PNG, rendered at ~144 DPI). Read each via the Read tool.
2. **Typhoon's OCR output** for the same pages, labelled with page-break sentinels (`---PAGE-BREAK---`). Typhoon-OCR 1.5 (3B) is a Thai-specialized vision-language model based on Qwen2.5-VL; its output is your starting point, not the final answer.

## What you must do

1. **Read all the page images.** Don't skip — your value-add is catching Typhoon's errors against the image.

2. **Read Typhoon's output.** Treat it as the baseline. It will get the bulk of characters right; your job is correction, not re-OCR from scratch.

3. **Compare Typhoon's text to what you see in the image, page by page.** Focus your attention on:
   - **Thai vowel marks** above and below characters (ิ ี ึ ื ุ ู เ แ ใ ไ โ) — Typhoon sometimes drops or swaps these
   - **Tone marks** (่ ้ ๊ ๋ and ์ silencer) — frequently mis-OCR'd in Typhoon output
   - **Number transcription** — Thai numerals (๐๑๒๓๔๕๖๗๘๙) vs Arabic; mis-OCR can swap entire digits
   - **Look-alike characters** — ฎ vs ฏ, ภ vs ก, ฬ vs ฬ, ษ vs ส, ฒ vs ฌ
   - **Table structure** — Typhoon flattens tables; if you see a table in the image, reconstruct rows with tabs
   - **Multi-column layout** — Typhoon may interleave columns; reorder if needed
   - **Headers / footers / page numbers** — Typhoon sometimes drops these; restore if visible

4. **Where Typhoon got it right (most of the time), pass it through unchanged.** Don't rewrite for style — your job is fidelity to the image, not editorial improvement.

5. **Where Typhoon got it wrong** (mis-OCR character, broken structure, dropped section), fix against the image.

6. **Where you genuinely cannot read the image** (smudge, scan artifact) AND Typhoon's text looks reasonable, keep Typhoon's text.

7. **Preserve line breaks roughly as they appear in the image.**

8. **Between pages, insert a single line containing exactly:** `---PAGE-BREAK---`

## Output rules

- Output **only the corrected text**. No commentary, no labels, no markdown wrapping, no "Here is the corrected OCR:".
- Do NOT translate. Do NOT summarise. Do NOT modernize spelling. Do NOT fix legal phrasing even if it looks ungrammatical.
- Use Thai numerals only if they appear in the source; otherwise keep Arabic.
- If a region is genuinely illegible AND Typhoon emitted `[ocr error]` for it, output `[illegible]` on its own line.
- Tables: preserve row/column structure with tabs between columns, one row per line.

## Why this pattern works

Typhoon-OCR 1.5 is fine-tuned specifically on Thai documents (the visual encoder has seen many examples of Thai characters in document images). On the user's 5-way bake-off across 1,008 PRT documents, Typhoon (Jaccard 0.43 vs Gemini oracle) clearly beats vanilla Claude Opus (0.34) on Thai OCR.

But Typhoon has documented weaknesses in its own model card: *"a certain level of hallucination may occur"* — most often as dropped tone marks, swapped vowels, and flattened table structure on the harder pages. These are exactly the failure modes a frontier VLM with strong general image understanding (Claude Opus) can catch, even with a weaker Thai vision encoder.

The hybrid pattern is established in the OCR literature: classical OCR for the bulk of character recognition, frontier LLM for cleanup, validation, and structure (Tesseract → GPT, Marker → Gemini Flash, Docling → LLM, etc.). Expected accuracy ceiling: above either model alone, with diminishing returns as Typhoon's baseline approaches the document's intrinsic complexity ceiling.

## Critical: do not "creatively interpret"

Your value here is **fidelity to the image**, not generating plausible Thai text. If you find yourself "filling in" what a Thai bureaucratic document "probably says," stop and re-read the image. The user explicitly cares about transcription accuracy over readability — they are using this output as evidence for downstream RAG, not as reading material.

## Inputs in the prompt that follows

The runner script will fill in placeholders below this line:

- `{pages}` — newline-separated list of page-image paths in document order
- `{typhoon_text}` — Typhoon-OCR's output for the same pages, with `---PAGE-BREAK---` between pages
