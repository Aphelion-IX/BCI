"""Saved automations: persistence, scheduling and execution on top of the sync functions."""
import copy
import datetime
import json
import os
import threading
import uuid

from .crossref import cross_reference
from .estimateone import flatten
from .export import write_xml
from .sync import run, run_estimateone

DATA_DIR = os.environ.get("BCI_DATA_DIR", "data")
# Only real BCI search parameters may be set from the UI (never token/fields/paging).
ALLOWED_FILTERS = {
    "state", "cat", "subcat", "status", "stage", "ownership", "development", "postcode", "town", "council",
    "region", "country", "funding", "green", "keyword", "address", "da_number", "project_value_min",
    "project_value_max", "storeys_min", "storeys_max", "floor_area_min", "floor_area_max", "units_min",
    "units_max", "companyid", "main_contractor_appointed", "main_contractor_listed", "contract_typeid"}
ACTIONS = ("preview", "xml", "crm")  # preview = fetch + cross-reference only; xml = also write files; crm = upsert to Dynamics
CROSSREF_BCI_FIELDS = ["PROJECTREFID", "PROJECT_NAME", "ADDRESS", "TOWN", "POSTCODE", "VALUE", "PROJECT_STATUS", "PROJECTSTAGE"]
_lock = threading.Lock()


def _path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


def load(name, default):
    try:
        with open(_path(name)) as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def save(name, data):
    with _lock:
        tmp = _path(name) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, _path(name))


def validate(a):
    """Normalise and validate an automation dict from the UI; raises ValueError with a readable message."""
    out = {
        "id": a.get("id") or uuid.uuid4().hex[:8],
        "name": (a.get("name") or "").strip(),
        "enabled": bool(a.get("enabled", True)),
        "sources": [s for s in a.get("sources", []) if s in ("bci", "estimateone")],
        "filters": {str(k): str(v) for k, v in (a.get("filters") or {}).items() if str(v).strip()},
        "window_days": int(a.get("window_days") or 2),
        "action": a.get("action", "preview"),
        "crossref": bool(a.get("crossref", True)),
        "threshold": float(a.get("threshold") or 0.6),
        "schedule": a.get("schedule") or {"type": "manual"},
    }
    if not out["name"]:
        raise ValueError("Name is required")
    if not out["sources"]:
        raise ValueError("Pick at least one source")
    bad = set(out["filters"]) - ALLOWED_FILTERS
    if bad:
        raise ValueError(f"Unknown filter(s): {', '.join(sorted(bad))}")
    if out["action"] not in ACTIONS:
        raise ValueError("Unknown action")
    if out["crossref"] and set(out["sources"]) != {"bci", "estimateone"}:
        out["crossref"] = False  # needs both sources
    sch = out["schedule"]
    if sch.get("type") == "interval":
        sch["minutes"] = max(15, int(sch.get("minutes") or 0))
    elif sch.get("type") == "daily":
        datetime.datetime.strptime(sch.get("time", ""), "%H:%M")
    elif sch.get("type") != "manual":
        raise ValueError("Unknown schedule type")
    return out


def is_due(automation, last_run_iso, now):
    """Pure scheduling rule. `now` and stored timestamps are naive local datetimes."""
    sch = automation.get("schedule") or {}
    if not automation.get("enabled") or sch.get("type") in (None, "manual"):
        return False
    last = datetime.datetime.fromisoformat(last_run_iso) if last_run_iso else None
    if sch["type"] == "interval":
        return last is None or now - last >= datetime.timedelta(minutes=sch["minutes"])
    hh, mm = map(int, sch["time"].split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now >= slot and (last is None or last < slot)


class Cached:
    """Fetches each source at most once per run, shared by sync, export and cross-reference."""

    def __init__(self, bci, e1):
        self.bci, self.e1, self._p, self._e = bci, e1, None, None

    def projects(self, filters, fields=None, since_last=False):
        if self._p is None:
            want = sorted(set(fields or []) | set(CROSSREF_BCI_FIELDS))
            self._p = list(self.bci.projects(filters, fields=want, since_last=since_last))
        return iter(self._p)

    def roles(self, *a, **k):
        return self.bci.roles(*a, **k)

    def companies(self, *a, **k):
        return self.bci.companies(*a, **k)

    def results(self):
        if self._e is None:
            self._e = list(self.e1.results())
        return iter(self._e)


def run_automation(a, base_cfg, bci, e1, crm):
    """Execute one automation; returns a run record (also appended to the history by the caller)."""
    started = datetime.datetime.now().isoformat(timespec="seconds")
    record = {"id": uuid.uuid4().hex[:8], "automation_id": a["id"], "automation": a["name"], "started": started,
              "action": a["action"], "counts": {}, "files": [], "status": "ok", "message": ""}
    try:
        if a["action"] == "crm" and crm is None:
            raise RuntimeError("Dynamics 365 credentials are not configured on this server")
        cfg = copy.deepcopy(base_cfg)
        cfg["filters"] = a["filters"]
        cfg["window_days"] = a["window_days"]
        src = Cached(bci, e1)
        write = a["action"] in ("xml", "crm")
        stamp = started.replace(":", "").replace("-", "")
        counts, bci_rows, e1_rows = {}, [], []
        if "bci" in a["sources"]:
            f = os.path.join(DATA_DIR, "exports", f"{a['id']}-{stamp}-bci.xml") if a["action"] == "xml" else None
            f and os.makedirs(os.path.dirname(f), exist_ok=True)
            counts.update(run(cfg, src, crm if a["action"] == "crm" else None, dry_run=not write, export_xml=f))
            bci_rows = list(src.projects(a["filters"]))
            f and record["files"].append(os.path.basename(f))
        if "estimateone" in a["sources"]:
            f = os.path.join(DATA_DIR, "exports", f"{a['id']}-{stamp}-e1.xml") if a["action"] == "xml" else None
            f and os.makedirs(os.path.dirname(f), exist_ok=True)
            counts.update(run_estimateone(cfg, src, crm if a["action"] == "crm" else None, dry_run=not write, export_xml=f))
            e1_rows = [flatten(p) for p in src.results()]
            f and record["files"].append(os.path.basename(f))
        record["counts"] = counts
        record["fetched"] = {"bci": len(bci_rows), "estimateone": len(e1_rows)}
        if a["crossref"]:
            x = cross_reference(bci_rows, e1_rows, a["threshold"], load("links.json", {}))
            record["crossref"] = {"matched": len(x["matches"]), "bci_only": len(x["bci_only"]), "e1_only": len(x["e1_only"])}
            if a["action"] == "xml":
                f = os.path.join(DATA_DIR, "exports", f"{a['id']}-{stamp}-crossref.xml")
                write_xml(f, [{"bci_id": m["bci"]["id"], "bci_name": m["bci"]["name"], "e1_id": m["e1"]["id"],
                               "e1_name": m["e1"]["name"], "score": m["score"], "status": m["status"]} for m in x["matches"]],
                          root="matches", item="match")
                record["files"].append(os.path.basename(f))
        if any(c["failed"] for c in counts.values()):
            record["status"] = "partial"
    except Exception as e:  # surface any failure in the history rather than killing the scheduler
        record["status"], record["message"] = "error", str(e)
    record["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    return record


def append_run(record, keep=200):
    runs = load("runs.json", [])
    runs.insert(0, record)
    save("runs.json", runs[:keep])
