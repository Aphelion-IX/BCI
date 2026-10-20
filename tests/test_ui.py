import datetime

import pytest

from bci_sync import automations as au
from bci_sync.crossref import cross_reference, address_similarity
from bci_sync.demo import BCI, E1
from bci_sync.estimateone import flatten


def test_crossref_pairs_demo_data():
    x = cross_reference(BCI, [flatten(p) for p in E1])
    pairs = {(m["bci"]["id"], m["e1"]["id"]) for m in x["matches"]}
    assert ("10037304", "e1-881") in pairs and ("10041022", "e1-902") in pairs
    assert {e["id"] for e in x["e1_only"]} >= {"e1-950"}
    assert address_similarity("106 Andrew St Esperance 6450", "106 Andrew Street, Esperance WA 6450") == 1.0


def test_manual_links_override_score():
    rows = [flatten(p) for p in E1]
    x = cross_reference(BCI, rows, links={"rejected": [["10037304", "e1-881"]], "confirmed": [["10053001", "e1-950"]]})
    pairs = {(m["bci"]["id"], m["e1"]["id"]): m["status"] for m in x["matches"]}
    assert ("10037304", "e1-881") not in pairs
    assert pairs[("10053001", "e1-950")] == "confirmed"


def test_validate_rejects_bad_input():
    ok = {"name": "n", "sources": ["bci"], "filters": {"state": "1"}}
    assert au.validate(ok)["crossref"] is False  # needs both sources
    for bad in ({**ok, "name": " "}, {**ok, "sources": []}, {**ok, "filters": {"token": "x"}}, {**ok, "action": "rm -rf"}):
        with pytest.raises(ValueError):
            au.validate(bad)


def test_is_due():
    now = datetime.datetime(2026, 10, 20, 6, 0)
    daily = {"enabled": True, "schedule": {"type": "daily", "time": "05:00"}}
    assert au.is_due(daily, None, now)
    assert au.is_due(daily, "2026-10-19T05:00:10", now)
    assert not au.is_due(daily, "2026-10-20T05:00:10", now)
    assert not au.is_due(daily, None, now.replace(hour=4))
    interval = {"enabled": True, "schedule": {"type": "interval", "minutes": 60}}
    assert au.is_due(interval, "2026-10-20T04:30:00", now) and not au.is_due(interval, "2026-10-20T05:30:00", now)
    assert not au.is_due({**interval, "enabled": False}, None, now)
    assert not au.is_due({"enabled": True, "schedule": {"type": "manual"}}, None, now)


def test_web_api_end_to_end(tmp_path, monkeypatch):
    for k in ("BCI_CLIENT_ID", "E1_CLIENT_ID", "DYNAMICS_ORG_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(au, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BCI_CONFIG", "config.yaml")
    from bci_sync import webapp
    c = webapp.app.test_client()
    assert c.get("/api/status").get_json() == {"bci_live": False, "e1_live": False, "crm_live": False}
    d = c.get("/api/crossref?refresh=1").get_json()
    assert len(d["matches"]) >= 3
    assert c.get("/api/crossref.xml").mimetype == "application/xml"
    a = c.post("/api/automations", json={"name": "Daily", "sources": ["bci", "estimateone"], "action": "xml",
                                          "filters": {"state": "6"}}).get_json()
    r = c.post(f"/api/automations/{a['id']}/run").get_json()
    assert r["status"] == "ok" and r["fetched"] == {"bci": 5, "estimateone": 4} and len(r["files"]) == 3
    assert (tmp_path / "exports" / r["files"][0]).exists()
    crm = c.post("/api/automations", json={"name": "CRM", "sources": ["bci"], "action": "crm"}).get_json()
    assert "Dynamics" in c.post(f"/api/automations/{crm['id']}/run").get_json()["message"]
    assert len(c.get("/api/runs").get_json()) == 2
    assert c.post("/api/automations", json={"name": "x", "sources": ["bci"], "filters": {"token": "1"}}).status_code == 400
    assert c.delete(f"/api/automations/{a['id']}").status_code == 204
