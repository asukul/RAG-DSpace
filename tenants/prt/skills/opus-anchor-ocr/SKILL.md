---
name: opus-anchor-ocr
description: OCR born-digital Thai government / parliamentary PDFs using olmOCR-style document anchoring — feed Claude Opus both the rasterized page image AND the text extracted from the PDF binary with bounding boxes, so it reconstructs the page in visual reading order while using the anchor text as ground truth for character recognition.
metadata:
  type: ocr
  language: thai-english
  inspiration: olmOCR (arXiv 2502.18443), Typhoon-OCR 1.5 (SCB 10X)
---

# Opus Anchor OCR — Thai government / parliamentary documents

## When to use this skill

Use this skill to OCR Thai documents where:

- The PDF has an embedded text layer (born-digital exports from Word, InDesign, etc.)
- The text layer is present but may be scrambled, mis-ordered, or character-encoding-corrupted
- Visual accuracy matters: output should match what a human sees on the page, not just what the PDF binary stores
- The corpus is Thai parliamentary / government documents (this skill is tuned for that register)

Do NOT use this skill for:

- Pure-scan PDFs (image-only, no text layer) — Typhoon-OCR-1.5 wins on those; this skill cannot help where the PDF has no extractable text
- Non-Thai documents (no harm, but the skill's prompt context assumes Thai)
- General document understanding / VQA (skill is OCR-only; emits raw text)

## Inputs you will receive

1. **Page images** (PNG, rendered from the PDF at ~144 DPI). The Read tool can load these.
2. **An anchor-text block** as JSON-lines. Each line is one text block from the PDF binary in the form:
   ```
   {"p":<page>,"bbox":[x0,y0,x1,y1],"t":"<text>","font":"<name>","size":<float>}
   ```
   Blocks are listed in PDF-binary order, which is **often not visual reading order** — that's exactly why you also have the image.

## What you must do

1. **Read both the images and the anchor-text block.** Don't skip either.
2. **Reconstruct the page in visual reading order** (top-to-bottom, left-to-right). The bounding boxes in the anchor text give you the geometry; the image confirms what's visually first.
3. **Use the anchor text as ground truth for character recognition.** If the image shows a character that matches an anchor block, use the anchor character verbatim — it's the original Unicode codepoint from the PDF binary, not subject to vision OCR error. This is the key win: Thai vowels and tone marks that vision models often mis-read (e.g., ิ vs ี vs ึ) are unambiguous in the anchor text.
4. **Use the image as ground truth for layout and ordering.** If the anchor blocks are out of visual order, reorder them. If a block spans multiple visual columns, split it.
5. **Where anchor text is missing or clearly wrong** (e.g., scanned region embedded in an otherwise-text PDF, or text-extraction garbage), fall back to reading the image directly.
6. **Preserve line breaks roughly as they appear visually.** Don't reflow paragraphs.
7. **Between pages, insert a single line containing exactly:** `---PAGE-BREAK---`

## Output rules

- Output **only the corrected text**. No commentary, no labels, no markdown wrapping, no preamble like "Here is the OCR:".
- Use Thai numerals (๑๒๓...) only if they appear in the source. If the source uses Arabic, keep Arabic.
- Do NOT translate. Do NOT summarize. Do NOT correct legal phrasing (even if it looks ungrammatical).
- If a region is genuinely illegible AND has no anchor text covering it, output a single line: `[illegible]`
- Tables: preserve row/column structure. Use tabs between columns; one row per line. Don't convert to HTML or Markdown.

## Why this works for Thai

Vision-Language Models (including Claude Opus 4.7) under-train on Thai script in their vision encoder relative to Latin script. Published evidence: Grab Engineering (2025) measured Thai vision OCR accuracy improvement only after explicit fine-tuning on Thai text-in-image examples. Typhoon-OCR 1.5 owes its lead on Thai OCR to that fine-tuning.

However, the vast majority of Thai government / parliamentary documents are **born-digital PDFs** — produced from Word or InDesign and exported. The correct Thai text is already in the PDF binary; PyMuPDF can extract it with bounding boxes. This skill exploits that: Claude doesn't need to recognize Thai characters in the image, it needs to *order and verify* anchor-text blocks against the image. That is a task Claude does well in any language.

## Reference architecture

This is a direct adaptation of olmOCR (Allen Institute, Petrosyan et al. 2025) and the document-anchoring pattern shared by Typhoon-OCR 1.5 (SCB 10X 2025). Both extract PDF text via PyPDF/pdfreport and feed it alongside the rasterized page image to a VLM. olmOCR paper: arXiv 2502.18443.

## Inputs in the prompt that follows

The OCR runner script will fill in placeholders below this line:

- `{pages}` — newline-separated list of page-image paths in document order
- `{anchor_text}` — JSON-lines, one block per line, PDF-binary order, all pages concatenated
