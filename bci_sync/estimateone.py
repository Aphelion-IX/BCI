"""Client for the EstimateOne (E1) Supplier API: Speci-finder results.

Docs: https://developer.api.estimateone.com/reference/supplier-api.html
"""
import time

import requests

API = "https://api.estimateone.com"
TOKEN_URL = "https://auth.api.estimateone.com/oauth2/token"
RESULTS_PATH = "/api/tender/supplier/v1/companies/{company_id}/speci-finder/results"
LIMIT = 100  # API maximum page size
MAX_RETRIES = 6


class EstimateOneClient:
    def __init__(self, client_id, client_secret, company_id, session=None):
        self.client_id, self.client_secret, self.company_id = client_id, client_secret, company_id
        self.http = session or requests.Session()
        self._token, self._expires = None, 0

    def _auth(self):
        if time.time() > self._expires - 60:
            r = self.http.post(TOKEN_URL, data={
                "grant_type": "client_credentials", "client_id": self.client_id,
                "client_secret": self.client_secret, "scope": "speci-finder/read"}, timeout=60)
            r.raise_for_status()
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + body.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}", "x-e1-client-id": self.client_id}

    def _get(self, url, params):
        """GET with exponential backoff on 429/5xx (docs: start ~1s, cap ~60s; 429 has no Retry-After)."""
        delay = 1
        for attempt in range(MAX_RETRIES):
            r = self.http.get(url, params=params, headers=self._auth(), timeout=120)
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()
                return r.json()
            if attempt == MAX_RETRIES - 1:
                r.raise_for_status()
            time.sleep(delay)
            delay = min(delay * 2, 60)

    def results(self):
        """Yield every matched project, following the opaque cursor until hasNextPage is false."""
        url = API + RESULTS_PATH.format(company_id=self.company_id)
        cursor = None
        while True:
            params = {"limit": LIMIT}
            if cursor:
                params["cursor"] = cursor
            page = self._get(url, params)
            yield from page.get("data", [])
            meta = page.get("_metadata") or {}
            if not meta.get("hasNextPage"):
                return
            cursor = meta["nextCursor"]


def _names(parties):
    return "; ".join(p["name"] for p in parties or [] if p.get("name"))


def flatten(project):
    """One flat row per project, keyed by upper-case field names (same convention as the BCI rows).

    A project can have several tenders; the one with the earliest quotes-due date is used for the
    headline columns and all tenders are listed in TENDER_NAMES.
    """
    tenders = sorted(project.get("tenders") or [], key=lambda t: t.get("quotesDueAt") or "9999-12-31")
    first = tenders[0] if tenders else {}
    budget = project.get("budget") or {}
    return {
        "PROJECTID": project.get("projectId"),
        "PROJECT_NAME": project.get("projectName"),
        "ADDRESS": project.get("address"),
        "CATEGORY": project.get("category"),
        "STATUS": project.get("status"),
        "URL": project.get("url"),
        "BUDGET_LOW": budget.get("low"),
        "BUDGET_HIGH": budget.get("high"),
        "TENDER_ID": first.get("id"),
        "TENDER_NAME": first.get("name"),
        "TENDER_TYPE": first.get("type"),
        "TENDER_STATUS": first.get("status"),
        "TENDER_OPEN_AT": first.get("tenderOpenAt"),
        "QUOTES_DUE_AT": first.get("quotesDueAt"),
        "BUILDER": (first.get("builder") or {}).get("name"),
        "BUILDER_WEBSITE": (first.get("builder") or {}).get("website"),
        "MATCHED_KEYWORDS": ", ".join(sorted({k for t in tenders for k in t.get("matchedKeywords") or []})),
        "TENDER_NAMES": "; ".join(t["name"] for t in tenders if t.get("name")),
        "CONSULTANTS": _names(project.get("consultants")),
        "TENDERING_SUBCONTRACTORS": _names(project.get("tenderingSubcontractors")),
    }
