# Trust the manual — prototype rules

Static PWA, mock data, no backend, no network calls except loading files from /public.
Purpose: validate the UX. "Don't trust the AI. Trust the manual. We just get you to the right page."

## Product rules (non-negotiable)
1. No prose. No onboarding, no explanations, no AI summaries, no chat bubbles, no "AI thinks…". If a string is not a label the user needs to act, delete it.
2. The manual is the answer. The result screen IS the official PDF, rendered page by page, with a translucent marker over the relevant lines. Its own page numbers, its own chapter titles, its own diagrams. Nothing rewritten.
3. It must be obvious it is the manual: header shows the manual title as printed on the cover + "p. N/M", body is the rendered PDF page on a light sheet inside the dark app.
4. Three steps only: bike → question → pages. Back is always one tap.
5. Mobile first (390×844), thumb-reachable controls at the bottom, 44px min tap targets, works one-handed with dirty hands. Also fine on desktop.
6. Fast. No spinners longer than a page render. No fake "thinking" delays.

## Visual
- Dark app chrome (--bg), light PDF sheet, one accent (--accent, orange) for the marker and the primary action only.
- System font. Sizes: 17px base, 15px secondary, 13px meta. Weight 500 for labels, 400 body.
- Radius 12px. Borders 1px --line. No shadows, no gradients, no icon libraries: inline SVG paths or unicode only.
- Tailwind v4 utilities + the CSS variables in src/index.css. No other CSS files.

## Allowed UI strings (entire app)
Photo · VIN · search placeholder "Make, model" · question placeholder "What do you want to do?" · Parts · p. · ← · ✕ · ↑ (send) · mic glyph.
Section titles, chapter titles, part names, specs and shop names come from the data files verbatim.

## Code
- React 19 + TypeScript + Vite + Tailwind v4 + pdfjs-dist. Types in src/types.ts are the contract; do not change them.
- Each owner edits only their own files (see File ownership). Shared files (App.tsx, types.ts, data/index.ts, data/bikes.json, index.css) are owned by the integrator.
- Pure functions in src/lib, screens in src/screens, reusable pieces in src/components.
- No comments explaining what code does. No README prose. `npm run build` must pass with zero TS errors.

## File ownership
- identify agent: src/screens/Identify.tsx, src/lib/identify.ts
- ask agent: src/screens/Ask.tsx, src/lib/match.ts, src/lib/speech.ts, src/components/Parts.tsx
- viewer agent: src/screens/Result.tsx, src/components/PdfPage.tsx, src/lib/pdf.ts
- data agents: public/manuals/<id>.pdf, src/data/manuals/<id>.json, tools/extract_<id>.py
- pwa agent: public/icons/*, vite.config.ts (PWA block only), index.html (head only)
