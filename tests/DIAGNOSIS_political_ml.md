# Diagnosis: "Political Machine Learning" not showing Adisak Sukul

## Symptoms reported by user
- Searching `Political Machine Learning` does not show any of Adisak Sukul's
  publications.
- The previous version (Antigravity + Claude Opus 4.5, before the cleanup) did show them.

## Findings

### Backend was already correct
A direct call to `/api/search` for `Political Machine Learning` against the
running backend already returned Adisak Sukul as a found expert (position #2,
later #1 after the dedupe fix), and the relevant papers were in `sources`. The
DSpace direct API also returned the right papers (`Machine Learning Models for
Political Video Advertisement Classification` etc., with
`dc.contributor.majorProfessor = ["Adisak Sukul", "Wallapak Tavanapong"]`).

So the backend never lost the data — what was lost was the **way the frontend
displays it**.

### Three real bugs in the display layer

**Bug 1 — Citations only show `authors`, never `advisors`/`majorProfessor`.**

The Qdrant payload only stores `authors` for each chunk. For papers where
Adisak is the major professor (not the listed author), his name simply does
not appear anywhere in the citation card. Before the cleanup, the legacy
`sources` panel rendered both authors and advisors; after the cleanup the
citation block replaced it and dropped the advisor line.

**Bug 2 — The legacy `sources` panel is hidden whenever `citations[]` is set.**

`App.jsx` checks `!Array.isArray(results.citations)` before rendering the
sources panel. The new RAG pipeline always returns `citations[]`, so the
sources panel is dead code in production. Adisak's name was visible in that
old panel because each source row showed `advisors`.

**Bug 3 — `found_faculty` was polluted by surname-only matches.**

The old matching logic accepted a bare last-name match as a hit
("Sukul" → Adisak Sukul, but also "Li" → every Li, "Mitra" → every Mitra,
etc.). For `Political Machine Learning` this returned **91** "found" experts,
mostly false positives, so even though Adisak was actually present in the
list (around position #2) he was buried inside a wall of unrelated names.

## Fixes applied

1. **`backend/main.py` — `_enrich_citations_with_advisors`**: after Qdrant
   returns citations, look up each citation's UUID in the live DSpace results
   and merge in `advisors` + `contributors` + a clean `authors_list` array.
   Citations now carry advisor info even though Qdrant payloads do not.

2. **`backend/main.py` — `_person_name_matches`**: tightened to require BOTH
   first AND last name as whole-word matches. The result list shrank from 91
   to 9 for the `Political Machine Learning` query, with Adisak at position
   #1 (no false positives).

3. **`frontend/src/App.jsx` — citation card**: now renders an
   `Major Professor: ...` line below the authors when the enriched citation
   includes advisors.

## Verification

| Query                            | Adisak in found_faculty | Position | Found-faculty count |
|----------------------------------|------------------------|----------|---------------------|
| `Political Machine Learning` (before) | yes                    | 2        | **91** (huge noise) |
| `Political Machine Learning` (after)  | yes                    | **1**    | **9**               |
| `Adisak Sukul` (before)               | yes                    | 1        | many                |
| `Adisak Sukul` (after)                | yes                    | 1        | small               |

DSpace ground truth for Adisak: 11 papers. Test harness reports 100% coverage
on both the local and the GCP-deployed backend, with 5/5 topic searches
correctly attributed back to him.

## Files touched
- `backend/main.py` — `_person_name_matches`, `_enrich_citations_with_advisors`,
  call sites in `/api/search`.
- `frontend/src/App.jsx` — citation card now renders `cite.advisors`.
