# QA report — live stack, 2026-09-20

Headless Chrome 390×844 + 1280×800 against the live API (27 manuals). Final run: 0 console errors, 0 failed requests.

Fixed
1. BMW R 12 G/S unreachable: two catalog rows for the same bike, the manual-less one won. `src/data/index.ts` keeps the row with a manual.
2. Page strip order: one section's pages stay ascending (`src/screens/Result.tsx` spread()).
3. Long manual titles truncated at 390 px: `src/lib/fit.ts` useFit, wired into Result and Ask.
4. Kawasaki page images dropped (JBIG2): pdf.js `wasmUrl`, decoders in `public/wasm/`.
5. Offline demo: bundled PDFs stay same-origin so the service worker caches them; airplane-mode reload verified.
6. Bookmark-less manuals: reader falls back to the manual's own sections.
7. API: gzip on JSON (catalog 2.5 MB → 207 KB), CORS expose headers so pdf.js can range-request.

Verified: every step of docs/DEMO.md, marker stroke, zoom, API-down fallback, slow-API fallback, empty query, unknown photo, add-manual sheet, PWA install, desktop.

Remaining
- Landscape manuals snap once on first open (viewer, low).
- Ingest title extraction: see ingest-findings.md (4 Kawasaki titled "WARNING", one garbled Royal Enfield title, five Honda manuals titled "OWNER'S MANUAL"); `p. N` is the PDF index, not the printed folio.

Screenshots: docs/qa/live/** (before/, desktop/, failures/, detail/).
