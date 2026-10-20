"""Minimal client for the BCI Australia REST API (https://api.bciaustralia.com/doc/home.htm)."""
import requests

BASE = "https://api.bciaustralia.com/rest"
PAGE_SIZE = 100


def normalise_rows(payload):
    """Return a list of dicts with upper-cased keys.

    ColdFusion serialises queries either as a list of structs or as
    {"COLUMNS": [...], "DATA": [[...], ...]}; accept both.
    """
    if isinstance(payload, dict):
        if "COLUMNS" in payload and "DATA" in payload:
            cols = [c.upper() for c in payload["COLUMNS"]]
            return [dict(zip(cols, row)) for row in payload["DATA"]]
        if isinstance(payload.get("DATA"), list):
            payload = payload["DATA"]
        else:
            return [{k.upper(): v for k, v in payload.items()}]
    return [{k.upper(): v for k, v in row.items()} for row in payload]


class BciClient:
    def __init__(self, client_id, password, session=None):
        self.client_id = client_id
        self.password = password
        self.http = session or requests.Session()
        self.token = None

    def login(self):
        r = self.http.get(f"{BASE}/auth.json", params={
            "clientID": self.client_id, "password": self.password, "ver": "latest"}, timeout=60)
        r.raise_for_status()
        data = r.json()
        data = {k.upper(): v for k, v in data.items()} if isinstance(data, dict) else {}
        if not data.get("TOKEN"):
            raise RuntimeError("BCI login failed: no TOKEN in response")
        self.token = data["TOKEN"]

    def _get(self, path, **params):
        if not self.token:
            self.login()
        params = {k: v for k, v in params.items() if v not in (None, "")}
        r = self.http.get(f"{BASE}/{path}.json", params={**params, "token": self.token}, timeout=120)
        r.raise_for_status()
        return normalise_rows(r.json())

    def _paged(self, path, **params):
        start = 1
        while True:
            rows = self._get(path, NumberOfRows=PAGE_SIZE, StartRow=start, **params)
            yield from rows
            if len(rows) < PAGE_SIZE:
                return
            start += PAGE_SIZE

    def projects(self, filters, fields=None, since_last=False):
        """Latest published version of each project matching `filters`."""
        method = "projects/getAllSinceLastQuery" if since_last else "projects"
        return self._paged(method, fields=",".join(fields or []), **filters)

    def roles(self, projectrefids, fields=None):
        """Companies/contacts attached to projects, batched to keep URLs short."""
        ids = list(projectrefids)
        for i in range(0, len(ids), 50):
            yield from self._paged("projectroles", projectrefid=",".join(map(str, ids[i:i + 50])),
                                   fields=",".join(fields or []))

    def companies(self, companyids, fields=None):
        ids = list(companyids)
        for i in range(0, len(ids), 50):
            yield from self._paged("companies", companyid=",".join(map(str, ids[i:i + 50])),
                                   fields=",".join(fields or []))
