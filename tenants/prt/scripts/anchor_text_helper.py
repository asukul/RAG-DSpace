"""Extract anchor-text blocks from a PDF for olmOCR-style hybrid OCR.

Returns a list of dicts, one per text block, in PDF-binary order:
  {"p": <1-indexed page>, "bbox": [x0,y0,x1,y1], "t": "<text>",
   "font": "<font name>", "size": <float>}

Bounding boxes are PDF-coordinate-space points (PyMuPDF's native units).
The runner converts them to JSON-lines for inclusion in the Claude prompt.

This is used as a module by `ocr_prt_opus_anchor.py`. CLI usage is for
debugging only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


def extract_anchor_blocks(pdf_path: Path, max_pages: Optional[int] = None) -> list[dict]:
    """Extract text blocks with bbox + font from each page.

    Returns blocks in (page, PDF-binary) order. Truncates very long blocks
    to keep total prompt size manageable.
    """
    blocks_out: list[dict] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"  fitz.open FAILED for {pdf_path.name}: {e}", file=sys.stderr)
        return []
    try:
        n = len(doc) if max_pages is None else min(len(doc), max_pages)
        for pnum in range(n):
            try:
                page = doc[pnum]
                page_dict = page.get_text("dict")
            except Exception as e:
                print(f"  get_text FAILED page {pnum+1}: {e}", file=sys.stderr)
                continue
            for block in page_dict.get("blocks", []):
                # type 0 = text block, 1 = image block
                if block.get("type", 0) != 0:
                    continue
                # Aggregate text across all spans in all lines of this block
                lines = block.get("lines", [])
                if not lines:
                    continue
                # Capture the dominant font + size from the first span seen
                dom_font = ""
                dom_size = 0.0
                parts: list[str] = []
                for line in lines:
                    line_parts: list[str] = []
                    for span in line.get("spans", []):
                        t = span.get("text", "")
                        if not t:
                            continue
                        line_parts.append(t)
                        if not dom_font:
                            dom_font = span.get("font", "")
                            dom_size = round(span.get("size", 0.0), 1)
                    if line_parts:
                        parts.append("".join(line_parts))
                text = "\n".join(parts).strip()
                if not text:
                    continue
                bbox = block.get("bbox", [0, 0, 0, 0])
                # Round bbox to ints to compact the JSON line
                bbox_int = [int(round(c)) for c in bbox]
                # Cap individual block text at 800 chars to keep prompts sane
                # (paragraphs longer than this in PRT are rare and usually
                # boilerplate; we don't want the prompt to balloon).
                if len(text) > 800:
                    text = text[:800] + "...[truncated]"
                blocks_out.append({
                    "p": pnum + 1,
                    "bbox": bbox_int,
                    "t": text,
                    "font": dom_font,
                    "size": dom_size,
                })
    finally:
        doc.close()
    return blocks_out


def blocks_to_jsonl(blocks: list[dict]) -> str:
    """Serialize as compact JSON-lines (one dict per line, no whitespace)."""
    return "\n".join(
        json.dumps(b, ensure_ascii=False, separators=(",", ":")) for b in blocks
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", help="Path to PDF file")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--jsonl", action="store_true", help="Emit JSON-lines instead of pretty JSON")
    args = ap.parse_args()

    blocks = extract_anchor_blocks(Path(args.pdf), max_pages=args.max_pages)
    if args.jsonl:
        print(blocks_to_jsonl(blocks))
    else:
        print(json.dumps(blocks, ensure_ascii=False, indent=2))
    print(f"\n# {len(blocks)} blocks extracted", file=sys.stderr)


if __name__ == "__main__":
    main()
