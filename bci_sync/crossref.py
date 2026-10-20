"""Cross-reference BCI projects with EstimateOne (E1) Speci-finder matches.

The two systems share no ID, so projects are paired by fuzzy name + address similarity.
Manual decisions ("confirmed" / "rejected" pairs) always win over the score.
"""
import difflib
import re

STOP = {"stage", "project", "the", "and", "of", "new", "building", "development", "works", "construction", "pty", "ltd"}
ABBREV = {"street": "st", "road": "rd", "avenue": "ave", "drive": "dr", "place": "pl", "highway": "hwy",
          "court": "ct", "parade": "pde", "boulevard": "bvd", "lane": "ln", "crescent": "cres", "terrace": "tce"}


def tokens(text, drop_stop=False):
    toks = [ABBREV.get(t, t) for t in re.findall(r"[a-z0-9]+", (text or "").lower())]
    return [t for t in toks if not (drop_stop and t in STOP)]


def name_similarity(a, b):
    ta, tb = tokens(a, True), tokens(b, True)
    if not ta or not tb:
        return 0.0
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    sa, sb = set(ta), set(tb)
    return (seq + len(sa & sb) / len(sa | sb)) / 2


def address_similarity(a, b):
    sa, sb = set(tokens(a)), set(tokens(b))
    if not sa or not sb:
        return None  # unknown, not zero
    return len(sa & sb) / min(len(sa), len(sb))


def score(bci, e1):
    n = name_similarity(bci["name"], e1["name"])
    a = address_similarity(bci["address"], e1["address"])
    total = n * 0.85 if a is None else 0.6 * n + 0.4 * a
    return round(total, 3), round(n, 3), None if a is None else round(a, 3)


def summarise_bci(row):
    addr = " ".join(str(row.get(k) or "") for k in ("ADDRESS", "TOWN", "POSTCODE")).strip()
    return {"id": str(row.get("PROJECTREFID") or row.get("PROJECTID")), "name": row.get("PROJECT_NAME") or "",
            "address": addr, "status": row.get("PROJECT_STATUS") or "", "value": row.get("VALUE"),
            "extra": row.get("PROJECTSTAGE") or ""}


def summarise_e1(row):
    return {"id": str(row.get("PROJECTID")), "name": row.get("PROJECT_NAME") or "", "address": row.get("ADDRESS") or "",
            "status": row.get("TENDER_STATUS") or row.get("STATUS") or "", "value": row.get("BUDGET_LOW"),
            "extra": f"Quotes due {row['QUOTES_DUE_AT']}" if row.get("QUOTES_DUE_AT") else ""}


def cross_reference(bci_rows, e1_rows, threshold=0.6, links=None):
    """Greedy one-to-one pairing, best score first.

    links: {"confirmed": [[bci_id, e1_id], ...], "rejected": [[bci_id, e1_id], ...]}
    Returns {"matches": [...], "bci_only": [...], "e1_only": [...]}.
    """
    links = links or {}
    confirmed = {tuple(map(str, p)) for p in links.get("confirmed", [])}
    rejected = {tuple(map(str, p)) for p in links.get("rejected", [])}
    bci = [summarise_bci(r) for r in bci_rows]
    e1 = [summarise_e1(r) for r in e1_rows]

    cands = []
    for b in bci:
        for e in e1:
            pair = (b["id"], e["id"])
            if pair in rejected:
                continue
            if pair in confirmed:
                cands.append((2.0, b, e, 1.0, 1.0, 1.0, "confirmed"))
                continue
            total, n, a = score(b, e)
            if total >= threshold:
                cands.append((total, b, e, total, n, a, "high" if total >= 0.8 else "possible"))
    cands.sort(key=lambda c: -c[0])

    used_b, used_e, matches = set(), set(), []
    for _, b, e, total, n, a, status in cands:
        if b["id"] in used_b or e["id"] in used_e:
            continue
        used_b.add(b["id"])
        used_e.add(e["id"])
        matches.append({"bci": b, "e1": e, "score": total, "name_score": n, "address_score": a, "status": status})
    return {"matches": matches,
            "bci_only": [b for b in bci if b["id"] not in used_b],
            "e1_only": [e for e in e1 if e["id"] not in used_e]}
