"""Local web UI: cross-reference BCI vs EstimateOne and manage automations.

Run:  python -m bci_sync.webapp   (binds 127.0.0.1:8080; API credentials stay server-side)
Without BCI/E1 credentials in the environment the matching source runs on built-in demo data.
"""
import datetime
import os
import threading
import time

import yaml
from flask import Flask, jsonify, request, send_from_directory

from . import automations as au
from .bci import BciClient
from .crossref import cross_reference
from .demo import DemoBci, DemoE1
from .dynamics import DynamicsClient
from .estimateone import EstimateOneClient, flatten
from .export import to_xml

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
_cache = {"at": 0, "key": None, "bci": [], "e1": []}


def env_clients():
    e = os.environ
    bci_live = bool(e.get("BCI_CLIENT_ID") and e.get("BCI_PASSWORD"))
    e1_live = all(e.get(k) for k in ("E1_CLIENT_ID", "E1_CLIENT_SECRET", "E1_COMPANY_ID"))
    crm_live = all(e.get(k) for k in ("DYNAMICS_ORG_URL", "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
    bci = BciClient(e["BCI_CLIENT_ID"], e["BCI_PASSWORD"]) if bci_live else DemoBci()
    e1 = EstimateOneClient(e["E1_CLIENT_ID"], e["E1_CLIENT_SECRET"], e["E1_COMPANY_ID"]) if e1_live else DemoE1()
    crm = DynamicsClient(e["DYNAMICS_ORG_URL"], e["AZURE_TENANT_ID"], e["AZURE_CLIENT_ID"], e["AZURE_CLIENT_SECRET"]) if crm_live else None
    return bci, e1, crm, {"bci_live": bci_live, "e1_live": e1_live, "crm_live": crm_live}


def base_cfg():
    with open(os.environ.get("BCI_CONFIG", "config.yaml")) as fh:
        return yaml.safe_load(fh)


def err(msg, code=400):
    return jsonify({"error": msg}), code


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/status")
def status():
    return jsonify(env_clients()[3])


def fetch_both(days, refresh):
    """Pull both sources (cached 5 min so page reloads do not burn the E1 rate limit of 100 req / 5 min)."""
    key = days
    if not refresh and _cache["key"] == key and time.time() - _cache["at"] < 300:
        return _cache["bci"], _cache["e1"]
    bci, e1, _, _ = env_clients()
    cached = au.Cached(bci, e1)
    filters = {**(base_cfg().get("filters") or {}), "updatedate": days}
    _cache.update(at=time.time(), key=key, bci=list(cached.projects(filters, fields=au.CROSSREF_BCI_FIELDS)),
                  e1=[flatten(p) for p in cached.results()])
    return _cache["bci"], _cache["e1"]


def crossref_result():
    a = request.args
    bci_rows, e1_rows = fetch_both(int(a.get("days", 7)), a.get("refresh") == "1")
    return cross_reference(bci_rows, e1_rows, float(a.get("threshold", 0.6)), au.load("links.json", {}))


@app.get("/api/crossref")
def crossref():
    try:
        return jsonify(crossref_result())
    except Exception as e:
        return err(str(e), 502)


@app.get("/api/crossref.xml")
def crossref_xml():
    x = crossref_result()
    rows = [{"bci_id": m["bci"]["id"], "bci_name": m["bci"]["name"], "e1_id": m["e1"]["id"], "e1_name": m["e1"]["name"],
             "score": m["score"], "status": m["status"]} for m in x["matches"]]
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(rows, "matches", "match"),
                              mimetype="application/xml", headers={"Content-Disposition": "attachment; filename=crossref.xml"})


@app.post("/api/links")
def set_link():
    d = request.get_json(force=True)
    pair = [str(d.get("bci_id")), str(d.get("e1_id"))]
    links = au.load("links.json", {"confirmed": [], "rejected": []})
    for k in ("confirmed", "rejected"):
        links[k] = [p for p in links.get(k, []) if p != pair]
    if d.get("decision") in ("confirmed", "rejected"):
        links[d["decision"]].append(pair)
    au.save("links.json", links)
    return jsonify(links)


@app.get("/api/automations")
def list_automations():
    return jsonify(au.load("automations.json", []))


@app.post("/api/automations")
def create_automation():
    try:
        a = au.validate({**request.get_json(force=True), "id": None})
    except (ValueError, TypeError) as e:
        return err(str(e))
    items = au.load("automations.json", [])
    items.append(a)
    au.save("automations.json", items)
    return jsonify(a), 201


@app.put("/api/automations/<aid>")
def update_automation(aid):
    items = au.load("automations.json", [])
    if not any(i["id"] == aid for i in items):
        return err("Not found", 404)
    try:
        a = au.validate({**request.get_json(force=True), "id": aid})
    except (ValueError, TypeError) as e:
        return err(str(e))
    au.save("automations.json", [a if i["id"] == aid else i for i in items])
    return jsonify(a)


@app.delete("/api/automations/<aid>")
def delete_automation(aid):
    au.save("automations.json", [i for i in au.load("automations.json", []) if i["id"] != aid])
    return "", 204


def execute(a):
    bci, e1, crm, _ = env_clients()
    record = au.run_automation(a, base_cfg(), bci, e1, crm)
    au.append_run(record)
    return record


@app.post("/api/automations/<aid>/run")
def run_now(aid):
    a = next((i for i in au.load("automations.json", []) if i["id"] == aid), None)
    return jsonify(execute(a)) if a else err("Not found", 404)


@app.get("/api/runs")
def runs():
    return jsonify(au.load("runs.json", []))


@app.get("/api/exports/<name>")
def export_file(name):
    return send_from_directory(os.path.join(au.DATA_DIR, "exports"), name, as_attachment=True)


def scheduler_loop():
    while True:
        try:
            now = datetime.datetime.now()
            history = au.load("runs.json", [])
            for a in au.load("automations.json", []):
                last = next((r["started"] for r in history if r["automation_id"] == a["id"]), None)
                if au.is_due(a, last, now):
                    execute(a)
                    history = au.load("runs.json", [])
        except Exception as e:  # never let the scheduler thread die
            print("scheduler error:", e)
        time.sleep(30)


def main():
    threading.Thread(target=scheduler_loop, daemon=True).start()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    main()
