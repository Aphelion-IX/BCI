from bci_sync.bci import normalise_rows
from bci_sync.sync import map_record, run, build_filters

CFG = {
    "window_days": 2,
    "filters": {"state": [1, 2]},
    "projects": {"entity_set": "new_bciprojects",
                 "key": {"crm_field": "new_ref", "bci_field": "PROJECTREFID"},
                 "mapping": {"new_name": "PROJECT_NAME", "new_value": "VALUE"}},
}


class FakeBci:
    def projects(self, filters, fields=None, since_last=False):
        self.filters = filters
        return [{"PROJECTREFID": 7.0, "PROJECT_NAME": " School ", "VALUE": 1.5e7},
                {"PROJECTREFID": None, "PROJECT_NAME": "no key"}]


class FakeCrm:
    def __init__(self):
        self.calls = []

    def upsert(self, es, kf, kv, rec):
        self.calls.append((es, kf, kv, rec))
        return "created"


def test_normalise_both_shapes():
    assert normalise_rows([{"a": 1}]) == [{"A": 1}]
    assert normalise_rows({"COLUMNS": ["a", "b"], "DATA": [[1, 2]]}) == [{"A": 1, "B": 2}]


def test_map_record_trims_and_drops_empty():
    assert map_record({"PROJECT_NAME": " x ", "VALUE": ""}, {"n": "PROJECT_NAME", "v": "VALUE"}) == {"n": "x"}


def test_run_upserts_and_skips_missing_key():
    bci, crm = FakeBci(), FakeCrm()
    res = run(CFG, bci, crm)
    assert res["projects"] == {"created": 1, "updated": 0, "skipped": 1, "failed": 0}
    assert crm.calls[0][2] == 7 and crm.calls[0][3] == {"new_name": "School", "new_value": 15000000}
    assert bci.filters == {"state": "1,2", "updatedate": 2}


def test_dry_run_writes_nothing():
    crm = FakeCrm()
    run(CFG, FakeBci(), crm, dry_run=True)
    assert crm.calls == []


def test_export_xml(tmp_path):
    import xml.etree.ElementTree as ET
    out = tmp_path / "p.xml"
    run(CFG, FakeBci(), FakeCrm(), export_xml=str(out))
    root = ET.parse(out).getroot()
    assert root.get("count") == "2"
    assert root[0].find("project_name").text == " School "


def test_xml_escapes_and_strips_control_chars():
    from bci_sync.export import to_xml
    x = to_xml([{"A": "a<b&\x01", "B": None}])
    assert "a&lt;b&amp;" in x and "\x01" not in x and "<b />" in x


E1_PAGES = [
    {"data": [{"projectId": "p1", "projectName": "Tower", "address": "1 St", "category": "Commercial",
               "budget": {"low": 1, "high": None}, "status": "Active", "url": "u",
               "consultants": [{"name": "Arch", "website": None}],
               "tenders": [{"id": "t2", "name": "Late", "quotesDueAt": "2026-12-01", "status": "Open",
                            "matchedKeywords": ["steel"]},
                           {"id": "t1", "name": "Early", "quotesDueAt": "2026-11-01", "status": "Open",
                            "builder": {"name": "BuildCo"}, "matchedKeywords": ["glass", "steel"]}],
               "tenderingSubcontractors": []}],
     "_metadata": {"nextCursor": "c2", "hasNextPage": True}},
    {"data": [{"projectId": "p2", "projectName": "Shed", "tenders": [{"id": "t3"}]}],
     "_metadata": {"nextCursor": None, "hasNextPage": False}},
]


class FakeResp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self):
        self.gets = []

    def post(self, url, **kw):
        return FakeResp({"access_token": "tok", "expires_in": 3600})

    def get(self, url, params=None, headers=None, **kw):
        self.gets.append((url, params, headers))
        if len(self.gets) == 1:
            return FakeResp({}, 429)  # throttled once, must retry
        return FakeResp(E1_PAGES[0] if "cursor" not in params else E1_PAGES[1])


def test_e1_paginates_retries_and_flattens(monkeypatch):
    from bci_sync import estimateone
    from bci_sync.estimateone import EstimateOneClient, flatten
    monkeypatch.setattr(estimateone.time, "sleep", lambda s: None)
    http = FakeHttp()
    projects = list(EstimateOneClient("cid", "sec", "123", session=http).results())
    assert [p["projectId"] for p in projects] == ["p1", "p2"]
    assert http.gets[1][0].endswith("/api/tender/supplier/v1/companies/123/speci-finder/results")
    assert http.gets[1][2] == {"Authorization": "Bearer tok", "x-e1-client-id": "cid"}
    assert http.gets[2][1]["cursor"] == "c2"
    row = flatten(projects[0])
    assert row["TENDER_ID"] == "t1" and row["BUILDER"] == "BuildCo" and row["BUDGET_HIGH"] is None
    assert row["MATCHED_KEYWORDS"] == "glass, steel" and row["CONSULTANTS"] == "Arch"
    assert flatten(projects[1])["TENDER_ID"] == "t3"


def test_run_estimateone_upserts_and_exports(tmp_path):
    from bci_sync.sync import run_estimateone
    cfg = {"estimateone": {"entity_set": "new_e1projects",
                           "key": {"crm_field": "new_e1projectid", "bci_field": "PROJECTID"},
                           "mapping": {"new_name": "PROJECT_NAME"}}}

    class FakeE1:
        def results(self):
            return [E1_PAGES[1]["data"][0]]

    crm = FakeCrm()
    out = tmp_path / "e1.xml"
    res = run_estimateone(cfg, FakeE1(), crm, export_xml=str(out))
    assert res["estimateone"]["created"] == 1 and crm.calls[0][2:] == ("p2", {"new_name": "Shed"})
    assert "<project_name>Shed</project_name>" in out.read_text()
