"""Group the rulebook instead of the vehicle: who prints what, and how little it varies.

Build-time. The same ClimateRule[] artefact #1 produces, read sideways. Two sub-analyses:

  cross-OEM agreement  does every maker print the same threshold for the same thing?
  model-year drift     within one model family, did the printed value change between years?

Family normalisation is the fuzzy join in this project, so every cluster is written out WITH its
members in families.json. A human can audit a bad merge; nothing is matched silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from .paths import climate_dir, rules_dir
from .rules import DETERMINISTIC
from .stations import manuals_with_rules, rules_for

# Trailing tokens that make one model look like three. Stripped for the family key, never for display.
VARIANT = re.compile(
    r"\b(factory|edition|fe|evo|track|gt|rr|rs|se|sp|abs|dct|adventure|super|r|s|x)\b")
MARKET = re.compile(r"-([a-z]{2})-(om|rm|sm)$")
YEAR = re.compile(r"\b(19|20)\d{2}\b")
TOKEN = re.compile(r"[a-z0-9]+")


def parts_of(manual_id: str) -> tuple[str, str, str]:
    """manual id -> (make, market, family key). The ids are slugs: make-model-year-market-om."""
    market = MARKET.search(manual_id)
    body = manual_id[: market.start()] if market else manual_id
    make = body.split("-", 1)[0]
    stripped = YEAR.sub(" ", body.replace("-", " "))
    tokens = [t for t in TOKEN.findall(stripped) if not VARIANT.fullmatch(t)]
    return make, (market.group(1) if market else "ww"), " ".join(tokens)


def token_ratio(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def families(ids: list[str]) -> dict[str, list[str]]:
    """Cluster manual ids into model families by token-set ratio >= 0.9 over the normalised key."""
    keys = {mid: parts_of(mid)[2] for mid in ids}
    clusters: dict[str, list[str]] = {}
    for mid, key in sorted(keys.items()):
        for head in clusters:
            if token_ratio(key, keys[clusters[head][0]]) >= 0.9:
                clusters[head].append(mid)
                break
        else:
            clusters[key] = [mid]
    return clusters


def build(log: Callable[..., None] = print) -> list[dict]:
    ids = manuals_with_rules()
    per_type: dict[tuple[str, str], dict] = {}
    by_family: dict[str, dict[str, set]] = {}
    clusters = families(ids)
    family_of = {mid: head for head, members in clusters.items() for mid in members}

    for manual_id in ids:
        make, market, _key = parts_of(manual_id)
        year_hit = YEAR.search(manual_id)
        year = year_hit.group(0) if year_hit else ""
        for rule in {(r.ruleType, r.value or "", r.name) for r in rules_for(manual_id)}:
            rule_type, value, _name = rule
            slot = per_type.setdefault((rule_type, value), {
                "ruleType": rule_type, "value": value, "manuals": 0,
                "markets": {}, "makes": {}, "years": {}})
            slot["manuals"] += 1
            slot["markets"][market] = slot["markets"].get(market, 0) + 1
            slot["makes"][make] = slot["makes"].get(make, 0) + 1
            if year:
                slot["years"][year] = slot["years"].get(year, 0) + 1
            fam = by_family.setdefault(family_of.get(manual_id, manual_id), {})
            fam.setdefault(rule_type, set()).add((value, year))

    grouped: dict[str, list[dict]] = {}
    for (rule_type, _value), slot in per_type.items():
        grouped.setdefault(rule_type, []).append(slot)

    rows = []
    for rule_type, slots in sorted(grouped.items()):
        slots.sort(key=lambda s: -s["manuals"])
        total = sum(s["manuals"] for s in slots)
        top = slots[0]["manuals"] if slots else 0
        # spread: 0.0 = every manual that prints this rule prints the same value.
        spread = round(1.0 - (top / total), 4) if total else 0.0
        markets: dict[str, int] = {}
        makes: dict[str, int] = {}
        for s in slots:
            for k, v in s["markets"].items():
                markets[k] = markets.get(k, 0) + v
            for k, v in s["makes"].items():
                makes[k] = makes.get(k, 0) + v
        rows.append({
            "ruleType": rule_type,
            # Only the deterministic types have a comparable spread: for the model-extracted ones
            # `value` is free text, so some of the variety is label noise, not real disagreement.
            "deterministic": rule_type in DETERMINISTIC,
            "values": [[s["value"], s["manuals"]] for s in slots],
            "manuals": total,
            "distinct": len(slots),
            "markets": dict(sorted(markets.items(), key=lambda kv: -kv[1])),
            "makes": dict(sorted(makes.items(), key=lambda kv: -kv[1])),
            "spread": spread,
        })

    drift = []
    for head, per_rule in sorted(by_family.items()):
        for rule_type, pairs in per_rule.items():
            values = {v for v, _y in pairs}
            if len(values) > 1:
                drift.append({"family": head, "ruleType": rule_type,
                              "values": sorted(f"{v} ({y})" for v, y in pairs),
                              "members": clusters.get(head, [])})

    out = {"rows": rows, "drift": drift, "familyCount": len(clusters), "manuals": len(ids)}
    (climate_dir() / "anomalies.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (climate_dir() / "families.json").write_text(
        json.dumps({"clusters": clusters, "drift": drift}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"anomalies: {len(rows)} rule types over {len(ids)} manuals, {len(clusters)} model families, "
        f"{len(drift)} with a value that moved between model years")
    for r in rows:
        log(f"  {r['ruleType']:18s} {r['manuals']:4d} manuals  {r['distinct']:3d} distinct value(s)  "
            f"spread {r['spread']:<7} markets {len(r['markets'])}  makes {len(r['makes'])}  "
            f"{'regex' if r['deterministic'] else 'model'}")
    return out["rows"]


__all__ = ["build", "families", "parts_of"]
