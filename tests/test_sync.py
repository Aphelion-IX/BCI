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
