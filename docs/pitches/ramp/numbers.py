#!/usr/bin/env python3
"""Recompute every number in the Ramp pitch from its inputs.

    python docs/pitches/ramp/numbers.py                 # print the tables
    python docs/pitches/ramp/numbers.py --md docs/pitches/ramp/numbers.md
    python docs/pitches/ramp/numbers.py --set search_share=0.10 --set lookups_per_day=40

Nothing here calls the network and nothing is cached: every figure below is either
ASSUMED (an input you may change) or MEASURED (a number we recorded, with its source).
Change an ASSUMED value and every table moves with it. MEASURED values are inputs too,
but changing one makes the document a lie, so they are kept apart.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# 1. ASSUMPTIONS — inputs a judge may disagree with. Every one carries a range.
# --------------------------------------------------------------------------------------


@dataclass
class A:
    """One assumption."""

    value: float
    low: float
    high: float
    unit: str
    why: str


ASSUMED: dict[str, A] = {
    "hours_per_year": A(
        2000, 1800, 2200, "h/year",
        "Owner-mechanic, full-time. Anchored on Eurostat lfsa_ewhuis 2024: a German "
        "full-time self-employed craft/trades worker usually works 44.3 h/week "
        "(all self-employed: 45.0). 44.3 x 45 working weeks = 1,994 h. "
        "The 45 weeks (5 weeks holiday + public holidays + sick) is the assumed part.",
    ),
    "search_share": A(
        0.20, 0.10, 0.20, "of working time",
        "HIS NUMBER, not ours: the founder's friend estimates ~20% of his working time "
        "goes to looking for a page. The low end halves it for the sceptic.",
    ),
    "working_days": A(
        230, 220, 240, "days/year",
        "45 working weeks x 5 days, rounded down for odd days off.",
    ),
    "lookups_per_day": A(
        25, 15, 40, "lookups/day",
        "How often a mechanic opens a manual. 40/day is the figure the cost report "
        "already prices the monthly bill at; 15/day is the sceptic's floor.",
    ),
    "rate_de": A(
        110, 75, 125, "EUR/h",
        "German independent-workshop labour rate. motor.com.de 2026: national average "
        "EUR 110/h, freie Werkstatt EUR 75-125/h, Vertragswerkstatt EUR 140-195/h. "
        "Cross-check from a real German KTM motorcycle workshop: FinkMoto publishes "
        "EUR 139/h including 19% VAT = EUR 116.81 net.",
    ),
    "rate_us": A(
        140, 120, 159, "USD/h",
        "US independent-shop labour rate. AutoLeap 2026: 'a national benchmark is near "
        "$140 for independent shops', range $120-159 across states.",
    ),
    "recovery": A(
        0.70, 0.30, 0.90, "of searching time",
        "The fraction of searching time the product actually removes. Not 1.0: the "
        "mechanic still has to read the page and decide. 0.30 is the hostile case.",
    ),
    "utilisation": A(
        0.80, 0.50, 1.00, "of recovered time",
        "Recovered hours only become money if there is work waiting to fill them. "
        "1.0 for a booked-out one-man shop, 0.5 for a slow one.",
    ),
    "price_de": A(
        49, 29, 99, "EUR/seat/month",
        "What we would charge a workshop per mechanic. Not yet validated by a sale. "
        "Payback is so short that the whole range lands in the same week.",
    ),
    "price_us": A(
        59, 39, 119, "USD/seat/month",
        "Same, at US rates.",
    ),
    "self_employed_hours": A(
        2000, 1800, 2200, "h/year",
        "Hours worked by a self-employed person in the sector. Eurostat publishes hours "
        "for EMPLOYEES only; the self-employed are added at this assumed figure.",
    ),
    "us_tech_hours": A(
        1800, 1700, 1900, "h/year",
        "US technician working year. No Eurostat equivalent; BLS blocks automated "
        "retrieval, so this one is an outright assumption.",
    ),
    "usd_per_eur": A(
        1.08, 1.02, 1.18, "USD per EUR",
        "Only used to put our dollar-denominated model cost next to a euro price. "
        "Nothing in the argument turns on it.",
    ),
}

# --------------------------------------------------------------------------------------
# 2. MEASURED — recorded in this repo or on the live service. Source on every line.
# --------------------------------------------------------------------------------------


@dataclass
class M:
    value: float
    unit: str
    source: str


MEASURED: dict[str, M] = {
    # --- time to the right page
    "ask_mean_s": M(1.60, "s", "api/eval/report.md, 150 queries, sequential, cold cache"),
    "ask_p95_s": M(3.33, "s", "api/eval/report.md, same run"),
    "ask_live_median_s": M(1.59, "s", "5 live asks vs mechanica.emilvinu.ch, 2026-09-20 (1.46/1.54/1.59/2.98/4.37)"),
    "ask_repeat_s": M(0.13, "s", "same run, the same question asked twice: 0.075 s and 0.179 s, $0"),
    "vin_s": M(0.11, "s", "live POST /api/identify/vin VBKJSA40XXXXXXXXX -> KTM 390 Duke 2024, 2026-09-20"),
    "photo_s": M(5.80, "s", "live POST /api/identify/photo x3, 2026-09-20: 5.01 / 5.80 / 7.66 s"),
    "manual_meta_s": M(0.09, "s", "live GET /api/manuals/ktm-390-duke-2023-eu-om, 2026-09-20"),
    "pdf_first_range_s": M(0.24, "s", "live GET .../file Range bytes=0-262143 (what pdf.js asks for), 2026-09-20"),
    "chat_first_token_p50_s": M(2.64, "s", "api/eval/chat-report.md"),
    "chat_first_token_p95_s": M(5.87, "s", "api/eval/chat-report.md"),
    "chat_full_p50_s": M(4.18, "s", "api/eval/chat-report.md"),
    "ingest_searchable_s": M(40.4, "s", "docs/pitches/general.md, live run KTM 390 Duke 2014, 182 p, 2026-09-20"),
    # --- money
    "ask_usd": M(0.00038, "USD/ask", "api/eval/report.md, cost-log delta over 150 asks"),
    "chat_usd": M(0.00420, "USD/answer", "docs/pitches/token-company/cost-report.md, 248 logged chat answers"),
    "ingest_usd": M(0.0951, "USD/manual", "api/data/mass_report.jsonl, 648 real ingests, paid once per manual"),
    "naive_usd": M(8.005, "USD/question", "cost-report.md: a 500-page workshop manual, 400k tokens, flagship, 2x long-context rule"),
    "naive_live_usd": M(12.40, "USD/question", "live GET /api/cost -> naivePerAsk, biggest manual in the deployed catalog"),
    "his_usd": M(4.00, "USD/question", "HIS bill, not ours: what the founder's friend measured when he tried an LLM"),
    # --- accuracy, because a time saving nobody trusts is not a saving
    "top1": M(1.00, "of 130 in-scope queries", "api/eval/report.md"),
    "oos": M(1.00, "of 20 off-topic queries returned empty", "api/eval/report.md"),
    "citations_verbatim": M(1.00, "of 43 chat quotes", "api/eval/chat-report.md"),
}

# --------------------------------------------------------------------------------------
# 3. SECTOR DATA — third-party, quoted with the URL.
# --------------------------------------------------------------------------------------

SECTOR = {
    # Eurostat SBS, sbs_ovw_act, pulled 2026-09-20 from the dissemination API.
    "de_g452_ent": 49922,       # 2024, Maintenance and repair of motor vehicles
    "de_g452_persons": 286455,  # 2024
    "de_g452_employees": 243055,  # 2024
    "de_g452_emp_hours": 328477640,  # 2024, hours worked BY EMPLOYEES
    "de_g452_va_meur": 16037.51,  # 2024
    "de_g452_va_per_hour": 48.82,  # 2024, Eurostat's own value added per hour worked
    "de_g454_ent": 4548,        # 2024, Sale, maintenance and repair of motorcycles
    "de_g454_persons": 22459,
    "de_g454_employees": 18057,
    "de_g454_emp_hours": 23340191,
    "de_g454_va_per_hour": 50.95,
    "eu_g452_ent": 502394,      # 2023
    "eu_g452_persons": 1418411,  # 2023
    "eu_g452_employees": 997975,  # 2023
    "eu_g452_hours_per_employee": 1585,  # 2021: 1,566,873,434 h / 988,260 employees
    "eu_g452_va_per_hour": 27.34,  # 2021
    "eu_g454_ent": 38000,       # 2023
    "eu_g454_persons": 109000,  # 2023
    "eu_g454_employees": 75679,  # 2022
    "eu_g454_hours_per_employee": 1602,  # 2023: 121,233,513 h / 75,679 employees
    "eu_g454_va_per_hour": 39.68,  # 2023
    # US
    "us_auto_shops": 307058,    # IBISWorld 2026, "Auto Mechanics in the US"
    "us_moto_dealers": 8346,    # poidata.io, August 2026
    "us_techs": 600406,         # BLS 2023 figure as cited by AutoLeap (BLS blocks bots)
    # Germany cross-check on the shop count
    "de_shops_listflix": 40968,  # listflix.de, 2026-09-20 (Autowerkstätten only)
}

SOURCES = [
    ("Eurostat `sbs_ovw_act` (Structural business statistics, NACE G45.2 / G45.4)",
     "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sbs_ovw_act?format=JSON&lang=EN&geo=DE&nace_r2=G452",
     "Enterprises, persons employed, employees, hours worked by employees, value added per hour. DE 2024, EU-27 2023."),
    ("Eurostat `lfsa_ewhuis` (LFS, usual weekly hours, self-employed, full-time, DE 2024)",
     "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/lfsa_ewhuis?format=JSON&lang=EN&geo=DE&sex=T&age=Y20-64&worktime=FT&wstatus=SELF&time=2024",
     "44.3 h/week for craft and related trades workers; 45.0 h/week for all self-employed."),
    ("motor.com.de — Werkstatt-Stundenlohn Deutschland (2026)",
     "https://www.motor.com.de/ratgeber/werkstatt-stundenlohn-deutschland",
     "National average EUR 110/h; freie Werkstatt EUR 75-125/h; Vertragswerkstatt EUR 140-195/h."),
    ("FinkMoto (ktm-fink.de) — a real German KTM motorcycle workshop's published rate",
     "https://ktm-fink.de/Stundensatz",
     "EUR 139/h incl. 19% VAT = EUR 116.81 net; the page itself breaks the rate into wages 28%, "
     "wage overheads 25%, operating overhead 23%, risk/profit 5%, VAT 19%."),
    ("AutoLeap — Average Automotive Repair Labor Rates by State (2026)",
     "https://autoleap.com/blog/average-automotive-repair-labor-rates-by-state/",
     "US national benchmark near $140/h for independent shops; $120-159 range; CA $155-175, NC $85-105."),
    ("IBISWorld — Auto Mechanics in the US, Number of Businesses (2026)",
     "https://www.ibisworld.com/united-states/number-of-businesses/automotive-repair-maintenance/1689/",
     "307,058 businesses as of 2026, +1.2% on 2025."),
    ("poidata.io — Motorcycle dealers in the United States (August 2026)",
     "https://poidata.io/index.php/report/motorcycle-dealer/united-states",
     "8,346 motorcycle dealers; FL 605, CA 441, TX 335. Weakest source here; treat as an order of magnitude."),
    ("listflix.de — Autowerkstätten in Deutschland (2026-09-20)",
     "https://listflix.de/statistik/autowerkstaetten/",
     "40,968 car repair shops, 49.4% sole proprietorships. Cross-check on the Eurostat enterprise count."),
    ("AutoLeap — How Many Auto Repair Shops Are in the United States",
     "https://autoleap.com/blog/auto-repair-shops-in-the-us/",
     "~600,406 mechanics (2023) and 239,100 repair facilities (Q4 2021), both quoted from BLS/Statista."),
]


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def eur(x: float, dp: int = 0) -> str:
    return f"EUR {x:,.{dp}f}"


def usd(x: float, dp: int = 2) -> str:
    return f"${x:,.{dp}f}"


def table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


class Model:
    def __init__(self, overrides: dict[str, float] | None = None):
        self.a = {k: v.value for k, v in ASSUMED.items()}
        self.a.update(overrides or {})
        self.m = {k: v.value for k, v in MEASURED.items()}

    # --- the one mechanic -------------------------------------------------------------
    @property
    def search_hours(self) -> float:
        """Top-down: his 20% of a working year."""
        return self.a["hours_per_year"] * self.a["search_share"]

    @property
    def implied_minutes_per_lookup(self) -> float:
        """The sanity check. If his 20% is real, this is what one lookup must cost him."""
        return self.search_hours * 60 / (self.a["working_days"] * self.a["lookups_per_day"])

    def bottom_up_hours(self, minutes: float, lookups: float | None = None) -> float:
        """The other direction: minutes x lookups x days."""
        k = self.a["lookups_per_day"] if lookups is None else lookups
        return k * self.a["working_days"] * minutes / 60

    @property
    def gross_de(self) -> float:
        return self.search_hours * self.a["rate_de"]

    @property
    def gross_us(self) -> float:
        return self.search_hours * self.a["rate_us"]

    @property
    def recovered_hours(self) -> float:
        return self.search_hours * self.a["recovery"]

    @property
    def recovered_de(self) -> float:
        return self.recovered_hours * self.a["utilisation"] * self.a["rate_de"]

    @property
    def recovered_us(self) -> float:
        return self.recovered_hours * self.a["utilisation"] * self.a["rate_us"]

    # --- the machine time -------------------------------------------------------------
    @property
    def path_typed_s(self) -> float:
        return self.m["vin_s"] + self.m["manual_meta_s"] + self.m["ask_live_median_s"] + self.m["pdf_first_range_s"]

    @property
    def path_photo_s(self) -> float:
        return self.m["photo_s"] + self.m["manual_meta_s"] + self.m["ask_live_median_s"] + self.m["pdf_first_range_s"]

    # --- the bill ---------------------------------------------------------------------
    def monthly(self, per_q: float, q_per_day: float = 40, days: float = 30) -> float:
        return per_q * q_per_day * days


# --------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------

def sec_assumptions(mo: Model) -> str:
    rows = []
    for k, a in ASSUMED.items():
        v = mo.a[k]
        rng = f"{a.low:,.2f} – {a.high:,.2f}".replace(".00", "")
        rows.append([f"`{k}`", f"**{v:,.2f}**".replace(".00", ""), a.unit, rng, a.why])
    return table(["input", "assumed", "unit", "range", "where it comes from / why"], rows)


def num(x: float) -> str:
    """Shortest honest rendering: keep every significant digit, drop trailing zeros."""
    if x == int(x):
        return f"{int(x):,}"
    s = f"{x:,.6f}".rstrip("0").rstrip(".")
    return s


def sec_measured(mo: Model) -> str:
    rows = []
    for k, v in MEASURED.items():
        shown = f"{v.value:.0%}" if v.unit.startswith("of ") else num(v.value)
        rows.append([f"`{k}`", f"**{shown}**", v.unit, v.source])
    return table(["input", "measured", "unit", "source"], rows)


def sec_one_mechanic(mo: Model) -> str:
    sh = mo.search_hours
    rows = [
        ["working hours in a year", "assumed", f"{mo.a['hours_per_year']:,.0f} h",
         "`hours_per_year`"],
        ["share spent looking for a page", "his number", f"{mo.a['search_share']:.0%}",
         "`search_share`"],
        ["**hours a year searching**", "= product", f"**{sh:,.0f} h**",
         "`hours_per_year x search_share`"],
        ["…as whole working days", "derived", f"{sh / 8:,.0f} days",
         f"`{sh:,.0f} / 8`"],
        ["…as minutes per working day", "derived", f"{sh * 60 / mo.a['working_days']:,.0f} min",
         "`search_hours x 60 / working_days`"],
        ["…so one lookup must cost him", "derived", f"**{mo.implied_minutes_per_lookup:.1f} min**",
         "`search_hours x 60 / (working_days x lookups_per_day)`"],
        ["at the German independent rate", "assumed rate", f"**{eur(mo.gross_de)}/year**",
         "`search_hours x rate_de`"],
        ["at the US independent rate", "assumed rate", f"**{usd(mo.gross_us, 0)}/year**",
         "`search_hours x rate_us`"],
    ]
    return table(["line", "kind", "value", "formula"], rows)


def sec_recovery(mo: Model) -> str:
    rows = [
        ["gross exposure", f"{mo.search_hours:,.0f} h", eur(mo.gross_de), usd(mo.gross_us, 0),
         "what a year of searching bills out at"],
        [f"x recovery {mo.a['recovery']:.0%}", f"{mo.recovered_hours:,.0f} h",
         eur(mo.recovered_hours * mo.a['rate_de']), usd(mo.recovered_hours * mo.a['rate_us'], 0),
         "the part the product actually removes"],
        [f"x utilisation {mo.a['utilisation']:.0%}", f"{mo.recovered_hours * mo.a['utilisation']:,.0f} h",
         f"**{eur(mo.recovered_de)}**", f"**{usd(mo.recovered_us, 0)}**",
         "the part that becomes billed work"],
    ]
    return table(["step", "hours/year", "Germany", "US", "what it means"], rows)


def sec_time_path(mo: Model) -> str:
    m = mo.m
    rows = [
        ["photo of the bike -> the exact model+year", f"{m['photo_s']:.2f} s", MEASURED["photo_s"].source],
        ["VIN -> the exact model+year", f"{m['vin_s']:.2f} s", MEASURED["vin_s"].source],
        ["manual metadata (chapters, specs)", f"{m['manual_meta_s']:.2f} s", MEASURED["manual_meta_s"].source],
        ["plain-words question -> the section and page", f"{m['ask_live_median_s']:.2f} s",
         MEASURED["ask_live_median_s"].source],
        ["…over 150 controlled queries", f"mean {m['ask_mean_s']:.2f} s, p95 {m['ask_p95_s']:.2f} s",
         MEASURED["ask_mean_s"].source],
        ["…the same question a second time", f"{m['ask_repeat_s']:.3f} s", MEASURED["ask_repeat_s"].source],
        ["the printed page renders (first PDF range)", f"{m['pdf_first_range_s']:.2f} s",
         MEASURED["pdf_first_range_s"].source],
        ["**typed or VIN -> the marked page**", f"**{mo.path_typed_s:.2f} s**", "sum of the rows above"],
        ["**photo -> the marked page**", f"**{mo.path_photo_s:.2f} s**", "sum of the rows above"],
        ["a manual we have never seen -> searchable", f"{m['ingest_searchable_s']:.1f} s",
         MEASURED["ingest_searchable_s"].source],
    ]
    return table(["step", "measured", "source"], rows)


def sec_before_after(mo: Model) -> str:
    after_min = mo.path_photo_s / 60
    rows = []
    for before in (3, 5, 8, 12):
        saved = (before - after_min) / 60 * mo.a["lookups_per_day"] * mo.a["working_days"]
        rows.append([
            f"{before} min",
            f"{after_min * 60:.1f} s ({after_min:.2f} min)",
            f"{before / after_min:,.0f}x",
            f"{saved:,.0f} h",
            f"{saved / mo.a['hours_per_year']:.0%}",
            eur(saved * mo.a["rate_de"]),
            eur(saved * mo.a["recovery"] * mo.a["utilisation"] * mo.a["rate_de"]),
        ])
    return table(["a lookup today (assumed)", "with Mechanica (measured)", "speed-up",
                  f"saved at {mo.a['lookups_per_day']:.0f} lookups x {mo.a['working_days']:.0f} days",
                  "…as a share of the year", "gross at the German rate",
                  "recovered (§4 deductions applied)"], rows)


def sec_payback(mo: Model) -> str:
    rows = []
    for n in (1, 3, 10):
        value = mo.recovered_de * n
        cost = mo.a["price_de"] * 12 * n
        per_day = value / mo.a["working_days"]
        rows.append([
            f"**{n}**",
            eur(value),
            eur(cost),
            f"{cost / value:.2%}",
            f"**{cost / per_day:.1f} working days**",
            f"{value / cost:,.0f}x",
        ])
    return table(["mechanics", "recovered billable work / year", f"our price ({eur(mo.a['price_de'])}/seat/mo)",
                  "price as % of the value", "payback", "return"], rows)


def sec_bill(mo: Model, q_per_day: float = 40) -> str:
    m = mo.m
    rows = []
    for label, per_q, note in [
        ("his lived bill when he tried an LLM", m["his_usd"], "HIS number: a 500-page manual pasted into a flagship model"),
        ("the same design today, priced out", m["naive_usd"], "400k tokens past the 272k long-context line, so 2x"),
        ("worst case in the deployed catalog", m["naive_live_usd"], "live `GET /api/cost` -> `naivePerAsk`"),
        ("ours, every question a written chat answer", m["chat_usd"], "worst case: 248 logged chat answers"),
        ("ours, the default path (question -> the page)", m["ask_usd"], "150-query eval, cost-log delta"),
    ]:
        rows.append([label, usd(per_q) if per_q >= 1 else f"${num(per_q)}",
                     usd(mo.monthly(per_q, q_per_day), 2),
                     usd(mo.monthly(per_q, q_per_day) * 12, 2),
                     note])
    return table([f"stack at {q_per_day:.0f} questions/day", "$ / question", "$ / month", "$ / year", "note"], rows)


def sec_margin(mo: Model) -> str:
    price_year_eur = mo.a["price_de"] * 12
    price_year_usd = price_year_eur * mo.a["usd_per_eur"]
    rows = []
    for label, per_q in [("default path (an ask)", mo.m["ask_usd"]),
                         ("worst case (every question a chat answer)", mo.m["chat_usd"])]:
        serve_year = mo.monthly(per_q) * 12
        rows.append([
            label,
            usd(serve_year, 2),
            f"{eur(price_year_eur)} = {usd(price_year_usd, 0)}",
            f"**{1 - serve_year / price_year_usd:.2%}**",
            f"{price_year_usd / serve_year:,.0f}x",
        ])
    return table(["what we serve", "model cost / seat / year", "price / seat / year",
                  "gross margin on the AI line", "price ÷ cost"], rows)


def sec_sensitivity(mo: Model) -> str:
    """Two axes: minutes per lookup, lookups per day. Money at the German rate, after recovery."""
    lookups = [15, 25, 40]
    head = ["minutes per lookup (assumed)"] + [f"{k}/day" for k in lookups]
    rows = []
    for minutes in (3, 5, 8, 12):
        r = [f"**{minutes} min**"]
        for k in lookups:
            hours = mo.bottom_up_hours(minutes, k)
            money = hours * mo.a["recovery"] * mo.a["utilisation"] * mo.a["rate_de"]
            share = hours / mo.a["hours_per_year"]
            r.append(f"{hours:,.0f} h · {share:.0%} · {eur(money)}")
        rows.append(r)
    return table(head, rows)


def sec_sensitivity_recovery(mo: Model) -> str:
    rows = []
    head = ["recovery \\ utilisation"] + [f"{u:.0%}" for u in (0.5, 0.8, 1.0)]
    for rec in (0.3, 0.5, 0.7, 0.9):
        r = [f"**{rec:.0%}**"]
        for util in (0.5, 0.8, 1.0):
            money = mo.search_hours * rec * util * mo.a["rate_de"]
            payback = (mo.a["price_de"] * 12) / (money / mo.a["working_days"])
            r.append(f"{eur(money)} · pays back in {payback:.1f} d")
        rows.append(r)
    return table(head, rows)


def sec_share_sensitivity(mo: Model) -> str:
    rows = []
    for share in (0.05, 0.10, 0.15, 0.20):
        hours = mo.a["hours_per_year"] * share
        money = hours * mo.a["recovery"] * mo.a["utilisation"] * mo.a["rate_de"]
        payback = (mo.a["price_de"] * 12) / (money / mo.a["working_days"])
        rows.append([f"**{share:.0%}**", f"{hours:,.0f} h", eur(hours * mo.a["rate_de"]),
                     eur(money), f"{payback:.1f} working days"])
    return table(["share of the year spent searching", "hours/year", "gross at the shop rate",
                  "recovered (after recovery x utilisation)", "payback on a seat"], rows)


def sec_market(mo: Model) -> str:
    s = SECTOR
    seh = mo.a["self_employed_hours"]

    share = mo.a["search_share"]

    def segment(emp_hours: float, self_persons: float, va_per_hour: float):
        hours = emp_hours + self_persons * seh
        return hours, hours * share * va_per_hour

    # Germany 2024: Eurostat publishes the employee hours directly.
    de_car = segment(s["de_g452_emp_hours"], s["de_g452_persons"] - s["de_g452_employees"],
                     s["de_g452_va_per_hour"])
    de_moto = segment(s["de_g454_emp_hours"], s["de_g454_persons"] - s["de_g454_employees"],
                      s["de_g454_va_per_hour"])
    de_hours, de_va_money = de_car[0] + de_moto[0], de_car[1] + de_moto[1]
    de_lost = de_hours * share

    # EU-27 2023: employee hours reconstructed from the published hours-per-employee.
    eu_car = segment(s["eu_g452_employees"] * s["eu_g452_hours_per_employee"],
                     s["eu_g452_persons"] - s["eu_g452_employees"], s["eu_g452_va_per_hour"])
    eu_moto = segment(s["eu_g454_employees"] * s["eu_g454_hours_per_employee"],
                      s["eu_g454_persons"] - s["eu_g454_employees"], s["eu_g454_va_per_hour"])
    eu_hours, eu_va_money = eu_car[0] + eu_moto[0], eu_car[1] + eu_moto[1]
    eu_lost = eu_hours * share

    us_hours = s["us_techs"] * mo.a["us_tech_hours"]
    us_lost = us_hours * share

    rows = [
        ["**Germany**",
         f"{s['de_g452_ent'] + s['de_g454_ent']:,}",
         f"{s['de_g452_persons'] + s['de_g454_persons']:,}",
         f"{de_hours / 1e6:,.0f} M h",
         f"**{de_lost / 1e6:,.0f} M h**",
         f"**{eur(de_va_money / 1e9, 1)} bn**",
         f"{eur(de_lost * mo.a['rate_de'] / 1e9, 1)} bn"],
        ["**EU-27**",
         f"{s['eu_g452_ent'] + s['eu_g454_ent']:,}",
         f"{s['eu_g452_persons'] + s['eu_g454_persons']:,}",
         f"{eu_hours / 1e9:,.2f} bn h",
         f"**{eu_lost / 1e6:,.0f} M h**",
         f"**{eur(eu_va_money / 1e9, 1)} bn**",
         f"{eur(eu_lost * mo.a['rate_de'] / 1e9, 1)} bn †"],
        ["**US**",
         f"{s['us_auto_shops'] + s['us_moto_dealers']:,}",
         f"{s['us_techs']:,}",
         f"{us_hours / 1e9:,.2f} bn h",
         f"**{us_lost / 1e6:,.0f} M h**",
         "not published",
         f"{usd(us_lost * mo.a['rate_us'] / 1e9, 1)} bn"],
    ]
    t1 = table(["region", "shops (repair of cars + motorcycles)", "people working in them",
                "hours worked / year", f"lost to searching at {mo.a['search_share']:.0%}",
                "**at sector value added / hour**", "at the shop labour rate"], rows)
    t1 += ("\n\n† The EU shop-rate column applies the *German* rate across 27 countries and is therefore"
           " too high — Eastern European labour rates are a fraction of it. Use the value-added column,"
           " which is each sector's own Eurostat figure"
           f" (DE cars {eur(s['de_g452_va_per_hour'], 2)}/h, DE motorcycles {eur(s['de_g454_va_per_hour'], 2)}/h,"
           f" EU cars {eur(s['eu_g452_va_per_hour'], 2)}/h, EU motorcycles {eur(s['eu_g454_va_per_hour'], 2)}/h).")

    seats = [
        ["Germany", f"{s['de_g452_persons'] + s['de_g454_persons']:,}", eur(mo.a["price_de"]),
         f"**{eur((s['de_g452_persons'] + s['de_g454_persons']) * mo.a['price_de'] * 12 / 1e6, 0)} M/year**"],
        ["EU-27", f"{s['eu_g452_persons'] + s['eu_g454_persons']:,}", eur(mo.a["price_de"]),
         f"**{eur((s['eu_g452_persons'] + s['eu_g454_persons']) * mo.a['price_de'] * 12 / 1e6, 0)} M/year**"],
        ["US", f"{s['us_techs']:,}", usd(mo.a["price_us"], 0),
         f"**{usd(s['us_techs'] * mo.a['price_us'] * 12 / 1e6, 0)} M/year**"],
    ]
    t2 = table(["region", "seats (persons employed in the sector)", "price / seat / month", "seat revenue if every seat bought"], seats)
    return t1, t2


# --------------------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------------------

def render(mo: Model) -> str:
    m = mo.m
    market_t1, market_t2 = sec_market(mo)
    q = 40

    monthly_his = mo.monthly(m["his_usd"], q)
    monthly_ours = mo.monthly(m["ask_usd"], q)
    monthly_worst = mo.monthly(m["chat_usd"], q)

    out = f"""# Ramp — the numbers

*Generated by `docs/pitches/ramp/numbers.py`. Re-run it to change any input:*

```
api/.venv/Scripts/python ../docs/pitches/ramp/numbers.py --md ../docs/pitches/ramp/numbers.md
api/.venv/Scripts/python ../docs/pitches/ramp/numbers.py --set search_share=0.10 --set lookups_per_day=40
```

Three kinds of number live in this file and they are never mixed:

- **ASSUMED** — an input you may disagree with. Every one has a range and a reason. Section 1.
- **MEASURED** — recorded in this repo or on the live service today. Section 2. Source on every line.
- **HIS** — the founder's friend's own figures: 20% of his time, ~$4 a question. Marked wherever they appear.

---

## The headline

| | |
|---|---|
| a mechanic's year spent looking for a page | **{mo.search_hours:,.0f} hours** ({mo.search_hours / 8:,.0f} working days) |
| what that year of searching bills out at, Germany | **{eur(mo.gross_de)}** per mechanic |
| what that year of searching bills out at, US | **{usd(mo.gross_us, 0)}** per mechanic |
| what we defend as actually recoverable | **{eur(mo.recovered_de)}** per mechanic per year |
| photo of the bike → the marked page in the manufacturer's own manual | **{mo.path_photo_s:.1f} s** measured |
| typed or VIN → the marked page | **{mo.path_typed_s:.1f} s** measured |
| his bill when he tried an LLM | **{usd(m['his_usd'])} / question** → **{usd(monthly_his, 0)} / month** at {q} questions/day |
| our bill | **{usd(m['ask_usd'], 5)} / ask** → **{usd(monthly_ours, 2)} / month**; worst case {usd(monthly_worst, 2)} |
| payback on one seat | **{(mo.a['price_de'] * 12) / (mo.recovered_de / mo.a['working_days']):.1f} working days** |
| hours lost to searching, Germany / EU-27 / US, every year | see §8 |

---

## 1. Assumptions — the column you are allowed to argue with

{sec_assumptions(mo)}

## 2. Measured — the column you are not

{sec_measured(mo)}

## 3. One mechanic, one year

{sec_one_mechanic(mo)}

**Why the {mo.implied_minutes_per_lookup:.1f} minutes matters.** We never assert how long a lookup takes.
We take his 20%, divide by the number of lookups, and *derive* it. {mo.implied_minutes_per_lookup:.1f} minutes to find
a torque figure in a {268}-page PDF on a phone with dirty hands is not a dramatic claim — it is a boring one.
If you think the 20% is inflated, §7 runs it the other way: pick the minutes and the lookups you believe,
and read off the share of the year they imply.

## 4. From gross exposure to money you would defend

Not every searching hour turns into a billed hour. Two deductions, both assumptions, both arguable:

{sec_recovery(mo)}

Say the small number on stage. **{eur(mo.recovered_de)}** is the one we would put in a contract;
{eur(mo.gross_de)} is the one that is true but flattering.

**Per-shop payback.** Our price is an assumption ({eur(mo.a['price_de'])}/seat/month, `price_de`);
the value is the recovered column above.

{sec_payback(mo)}

Payback is measured in working days, not months, and it does not improve or worsen with shop size — it is a
per-seat number multiplied by seats. What changes with size is the absolute figure: the ten-mechanic shop is
looking at {eur(mo.recovered_de * 10)} of work it is currently spending on PDFs.

## 5. The product path, in time units

Every row measured against the live service at `https://mechanica.emilvinu.ch/api`.

{sec_time_path(mo)}

Those end-to-end figures are **machine time on the critical path** — what the service spends, not what a
stopwatch on stage will read. Add the mechanic's own taps and his reading of the page and the stopwatch number
is maybe two to three times that (estimate, not measured). What collapsed is the *finding*, and the finding is
{m['ask_live_median_s']:.2f} seconds.

**Before and after, per lookup.** The "before" column is the assumption; everything right of it follows from
the measured {mo.path_photo_s:.1f} s. The last two columns are the same saving gross and after the §4 deductions.

{sec_before_after(mo)}

Sanity bound: a row whose share of the year runs past about 25% is describing a mechanic who barely touches a
bike. The 3- and 5-minute rows are the ones to quote.

## 6. The cost side — his bill and ours

{sec_bill(mo, q)}

Ours does not move with page count: the prompt never holds the manual, only the pages BM25 returned.
His did — that is the whole of the {usd(m['his_usd'])}. Plus {usd(m['ingest_usd'], 4)} once per manual
({MEASURED['ingest_usd'].source}), never per question.

**What that does to the unit economics of a seat:**

{sec_margin(mo)}

The point for Ramp: the AI line item is
**{mo.monthly(m['chat_usd']) * 12 / (mo.a['price_de'] * 12 * mo.a['usd_per_eur']):.1%} of the subscription in the
worst case** and {mo.monthly(m['ask_usd']) * 12 / (mo.a['price_de'] * 12 * mo.a['usd_per_eur']):.2%} on the
default path. It is not a cost that scales badly with usage — it is a rounding error that scales with the number
of distinct manuals, and there are only so many motorcycles. Every AI budget line in this company is a fixed
cost in disguise; the variable one is the ingest, {usd(m['ingest_usd'], 4)} a manual, paid once and shared by
every shop that ever opens that bike.

## 7. Sensitivity — run it the other way

**(a) If a lookup takes 3 minutes and not 8.** Pick a cell. Each shows hours/year · what share of a
{mo.a['hours_per_year']:,.0f}-hour year that is · recovered euros at {mo.a['recovery']:.0%} recovery and
{mo.a['utilisation']:.0%} utilisation.

{sec_sensitivity(mo)}

Read the {mo.a['lookups_per_day']:.0f}/day column: his 20% shows up at roughly
{mo.implied_minutes_per_lookup:.1f} minutes a lookup. Nothing had to be stretched to get there. Cells past
about 25% of the year are arithmetic, not people — a mechanic searching 60% of his week has no shop left.

**(b) If only half the searching time is recoverable.** Rows are how much of the searching time the product
removes; columns are how much of the freed time turns into billed work.

{sec_sensitivity_recovery(mo)}

Every cell in that table pays back a seat inside one working month. The pitch does not depend on the
optimistic corner.

**(c) If his 20% is really 5%.**

{sec_share_sensitivity(mo)}

At **5%** — a quarter of what he says — a seat still pays for itself in under
{(mo.a['price_de'] * 12) / ((mo.a['hours_per_year'] * 0.05 * mo.a['recovery'] * mo.a['utilisation'] * mo.a['rate_de']) / mo.a['working_days']):.0f} working days.

## 8. The bigger picture

Hours are built from Eurostat's own *hours worked by employees* where it publishes them, plus self-employed
people at {seh_note(mo)}. Two money columns on purpose: **value added per hour** is Eurostat's own figure and is
the defensible one; **the shop labour rate** is what the customer is charged and is the flattering one.

{market_t1}

Cross-check on the German shop count: listflix.de counted {SECTOR['de_shops_listflix']:,} Autowerkstätten on
2026-09-20 against Eurostat's {SECTOR['de_g452_ent']:,} enterprises in NACE G45.2 for 2024 — different
definitions, same order of magnitude.

**And the part of it that is a business for us** — seats, not saved hours:

{market_t2}

We do not claim every seat. The reachable wedge is the independent shop: Eurostat puts
{SECTOR['de_g452_persons'] / SECTOR['de_g452_ent']:.0f} people in the average German car-repair enterprise and
{SECTOR['de_g454_persons'] / SECTOR['de_g454_ent']:.0f} in the average motorcycle one, and listflix puts 49.4% of
German car workshops at a single sole proprietor. This is a market of one- to six-person shops — which is
exactly the shop in the story, and exactly the shop nobody sells software to.

## 9. Why the time saving is allowed to count

A time saving nobody trusts is not a saving — he goes and checks the manual anyway, and you have added a step.

| gate | measured | source |
|---|---|---|
| right section first, in-scope queries | **{m['top1']:.0%}** of 130 | `api/eval/report.md` |
| off-topic questions returned empty instead of guessed at | **{m['oos']:.0%}** of 20 | `api/eval/report.md` |
| chat quotes verbatim on the page they name | **{m['citations_verbatim']:.0%}** of 43 | `api/eval/chat-report.md` |

The answer is the manufacturer's page with a marker on the line. If we are wrong, he sees it in half a second,
because he is looking at the manual and not at a paragraph.

## 10. Sources

{sources_block()}

Pulled 2026-09-20. The two Eurostat rows are live API calls — paste the URL into a browser and you get the
same JSON. The measured rows are this repo and this morning's calls against the live service.

### Known weaknesses, stated rather than hidden

- **`lookups_per_day` has no source.** It is the load-bearing assumption in §7(a). We derive the minutes per
  lookup from his 20% rather than asserting both, but one of the two has to be assumed.
- **`recovery` and `utilisation` have no source either.** They exist to stop us quoting {eur(mo.gross_de)} as
  if it were revenue.
- **The US technician count is second-hand.** BLS blocks automated retrieval, so {SECTOR['us_techs']:,} comes
  from AutoLeap quoting BLS, not from BLS directly.
- **`poidata.io` is the weakest source in the file.** The US motorcycle dealer count should be treated as an
  order of magnitude, and it barely moves the market number next to {SECTOR['us_auto_shops']:,} car shops.
- **p50 for an ask is not in the committed eval report** — it publishes mean {m['ask_mean_s']:.2f} s and
  p95 {m['ask_p95_s']:.2f} s. The {m['ask_live_median_s']:.2f} s median is our own 5-query live run today.
  `api/eval/run.py --json` records per-query `seconds` if you want the real p50 over 150.
- **The price is not validated by a sale.** {eur(mo.a['price_de'])}/seat/month is what we would charge, not
  what anyone has paid.
"""
    return out


def seh_note(mo: Model) -> str:
    return f"an assumed {mo.a['self_employed_hours']:,.0f} h/year (`self_employed_hours`)"


def sources_block() -> str:
    rows = [[f"[{name}]({url})", note] for name, url, note in SOURCES]
    return table(["source", "what we took from it"], rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--md", help="write the whole document to this path")
    p.add_argument("--set", action="append", default=[], metavar="key=value",
                   help="override an assumption, e.g. --set search_share=0.10")
    args = p.parse_args()

    overrides: dict[str, float] = {}
    for item in args.set:
        k, _, v = item.partition("=")
        if k not in ASSUMED:
            print(f"unknown assumption {k!r}; known: {', '.join(ASSUMED)}", file=sys.stderr)
            return 2
        overrides[k] = float(v)

    doc = render(Model(overrides))
    if args.md:
        with open(args.md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(doc)
        print(f"wrote {args.md} ({len(doc):,} chars)")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
