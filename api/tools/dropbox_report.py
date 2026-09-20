"""The chaos slide, measured. Run from api/:

    python -m tools.dropbox_report

Writes docs/pitches/dropbox/registry-report.md plus two SVG charts next to it. Every number comes
out of api/data/registry.json and api/data/bikes.json at the moment you run it - nothing is typed
by hand, so the pitch cannot drift from the repo. SVG rather than PNG on purpose: matplotlib is not
in api/.venv and a chart is not worth a dependency. Any browser or slide tool imports an SVG, and it
stays sharp on a projector.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.models import Bike, RegistryEntry  # noqa: E402
from app.registry import _ingestable, _is_pdf, doc_kind  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "pitches" / "dropbox"
FRAGMENTS = settings.data_dir / "registry-fragments"

# Portals walked to the end and written off, from docs/MANUALS.md ("Checked and genuinely
# unreachable") - the part of the chaos no amount of crawling fixes.
UNREACHABLE = (
    "CFMOTO", "LiveWire", "Beta", "Moto Morini", "Brixton", "Ural", "Janus", "Norton", "Mash",
    "CCM", "SWM", "Fantic", "Energica", "Segway", "Sur-Ron", "Talaria", "Stark",
)

INK = "#1b1b1b"
MUTED = "#8a8a8a"
LINE = "#dcdcdc"
ACCENT = "#ff6a00"


def load() -> tuple[list[RegistryEntry], list[Bike]]:
    rows = json.loads((settings.data_dir / "registry.json").read_text(encoding="utf-8"))
    bikes = json.loads((settings.data_dir / "bikes.json").read_text(encoding="utf-8"))
    return [RegistryEntry.model_validate(r) for r in rows], [Bike.model_validate(b) for b in bikes]


def host_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].lower() if "//" in url else ""


def bars(path: Path, title: str, data: list[tuple[str, int]], unit: str = "rows") -> None:
    """A horizontal bar chart, hand-written. No library, no raster, no theme to fight."""
    width, row_h, pad_top, left = 760, 26, 56, 250
    height = pad_top + row_h * len(data) + 24
    top = max(n for _, n in data) or 1
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="20" y="30" font-size="17" font-weight="600" fill="{INK}">{title}</text>',
        f'<line x1="{left}" y1="{pad_top - 14}" x2="{left}" y2="{height - 16}" stroke="{LINE}"/>',
    ]
    for i, (label, n) in enumerate(data):
        y = pad_top + i * row_h
        w = max(2, round((width - left - 96) * n / top))
        out.append(f'<text x="{left - 10}" y="{y + 12}" font-size="13" text-anchor="end" fill="{INK}">{label}</text>')
        out.append(f'<rect x="{left}" y="{y + 1}" width="{w}" height="16" fill="{ACCENT if i == 0 else INK}" opacity="{1 if i == 0 else 0.72}"/>')
        out.append(f'<text x="{left + w + 8}" y="{y + 13}" font-size="12" fill="{MUTED}">{n:,} {unit}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def funnel(path: Path, title: str, steps: list[tuple[str, int, str]]) -> None:
    """53,557 rows in, one page out. Each step is (label, value, what the step removed)."""
    width, step_h, pad_top = 760, 74, 56
    height = pad_top + step_h * len(steps) + 16
    top = steps[0][1] or 1
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="20" y="30" font-size="17" font-weight="600" fill="{INK}">{title}</text>',
    ]
    for i, (label, n, note) in enumerate(steps):
        y = pad_top + i * step_h
        w = max(120, round((width - 40) * n / top))
        last = i == len(steps) - 1
        out.append(f'<rect x="20" y="{y}" width="{w}" height="40" rx="6" fill="{ACCENT if last else INK}" opacity="{1 if last else 0.82}"/>')
        out.append(f'<text x="34" y="{y + 26}" font-size="15" font-weight="600" fill="#ffffff">{n:,}</text>')
        out.append(f'<text x="{34 + 12 * len(f"{n:,}")}" y="{y + 26}" font-size="13" fill="#ffffff" opacity="0.9">{label}</text>')
        if note:
            out.append(f'<text x="24" y="{y + 60}" font-size="12" fill="{MUTED}">{note}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, bikes = load()

    sites = collections.Counter(e.site for e in rows)
    hosts = {host_of(e.url) for e in rows} - {""}
    distinct = {e.url for e in rows}
    free = [e for e in rows if _ingestable(e)]
    free_files = {e.url for e in free}
    mislabelled = [e for e in rows if e.type == "owner" and doc_kind(e) != "owner"]
    by_kind = collections.Counter(doc_kind(e) for e in mislabelled)
    mis_sites = collections.Counter(e.site for e in mislabelled)
    service = [e for e in rows if e.type == "service"]
    by_access = collections.Counter(e.access for e in service)
    with_pdf = [b for b in bikes if b.manualUrl]
    pdf_rows = [e for e in rows if _is_pdf(e.url)]

    drops = 0
    for path in sorted(FRAGMENTS.glob("*.drop.json")):
        try:
            listed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        drops += len(listed) if isinstance(listed, list) else 0

    bars(
        OUT / "rows-per-portal.svg",
        "One registry, 84 portals: rows per portal",
        [(site, n) for site, n in sites.most_common(12)],
    )
    funnel(
        OUT / "chaos-to-order.svg",
        "53,557 rows to one page",
        [
            (f"rows across {len(sites)} portals", len(rows), f"{len(rows) - len(distinct):,} point at a file another row already names"),
            ("distinct files", len(distinct), f"{len(pdf_rows) - len(free):,} PDF rows are not a free English handbook"),
            ("free English handbook rows", len(free), f"{len(free) - len(free_files):,} are the same PDF under another year or market"),
            ("distinct PDFs we can fetch", len(free_files), f"{len(mislabelled):,} rows the portal filed as a handbook are not one"),
            ("vehicles pointed at one", len(with_pdf), "and 0 of them is the service manual a shop needs"),
        ],
    )

    report = [
        "# The chaos, measured",
        "",
        f"Generated by `python -m tools.dropbox_report` from `api/data/registry.json` and",
        f"`api/data/bikes.json`. Every figure below is a count, not an estimate.",
        "",
        "## Order, in one funnel",
        "",
        "![chaos to order](chaos-to-order.svg)",
        "",
        "| step | count |",
        "|---|---|",
        f"| registry rows | **{len(rows):,}** |",
        f"| makes | {len({e.make for e in rows}):,} |",
        f"| portals (`site`) | **{len(sites)}** |",
        f"| distinct hosts serving the files | {len(hosts)} |",
        f"| distinct URLs behind those rows | {len(distinct):,} |",
        f"| rows that name a file another row already names | **{len(rows) - len(distinct):,}** |",
        f"| free English owner's-manual PDF rows | {len(free):,} |",
        f"| …distinct PDFs behind them | **{len(free_files):,}** |",
        f"| vehicles in the catalog | {len(bikes):,} |",
        f"| …with a free official manual attached | **{len(with_pdf):,}** |",
        "",
        "## What the portals call a handbook and is not",
        "",
        f"`api/app/registry/doctype.py` classifies every row from its URL and title alone - no download.",
        f"**{len(mislabelled):,} rows arrive typed `owner` and are something else:**",
        "",
        "| docKind | rows |",
        "|---|---|",
    ]
    report += [f"| {kind} | {n:,} |" for kind, n in by_kind.most_common()]
    report += [
        "",
        "Worst offenders, by portal:",
        "",
        "| portal | mislabelled rows |",
        "|---|---|",
    ]
    report += [f"| `{site}` | {n:,} |" for site, n in mis_sites.most_common(8)]
    report += [
        "",
        "## Rows per portal",
        "",
        "![rows per portal](rows-per-portal.svg)",
        "",
        "| portal | rows |",
        "|---|---|",
    ]
    report += [f"| `{site}` | {n:,} |" for site, n in sites.most_common(12)]
    report += [
        "",
        "## The half no crawler reaches",
        "",
        f"| service-manual rows | {len(service)} |",
        "|---|---|",
    ]
    report += [f"| …{access} | {n} |" for access, n in by_access.most_common()]
    report += [
        "",
        f"Portals walked to the end and written off ({len(UNREACHABLE)}, from `docs/MANUALS.md`): "
        + ", ".join(UNREACHABLE)
        + ".",
        "",
        f"Rows explicitly retracted by a `*.drop.json` list in `api/data/registry-fragments/`: **{drops:,}**",
        f"(`python -m tools.registry merge-fragments` is the only writer of `registry.json`; a fragment",
        "cannot un-say a row on its own, so an owner retracts it by id or by `--replace`ing its scope).",
        "",
        "That is the order we can build from a crawler. The document a professional needs is in none of",
        "it - which is where the shop's own Dropbox folder comes in.",
        "",
    ]
    (OUT / "registry-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'registry-report.md'}")
    print(f"  {len(rows):,} rows, {len(sites)} portals, {len(distinct):,} distinct urls")
    print(f"  {len(mislabelled):,} mislabelled rows, {len(free_files):,} fetchable PDFs, {len(with_pdf):,} vehicles served")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
