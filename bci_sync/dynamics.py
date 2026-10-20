"""Dynamics 365 / Dataverse Web API upserts using alternate keys."""
import time
import requests


class DynamicsClient:
    def __init__(self, org_url, tenant_id, client_id, client_secret, session=None, api="v9.2"):
        self.org = org_url.rstrip("/")
        self.api = f"{self.org}/api/data/{api}"
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.http = session or requests.Session()
        self._token, self._expires = None, 0

    def _auth(self):
        if time.time() > self._expires - 60:
            r = self.http.post(
                f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                data={"grant_type": "client_credentials", "client_id": self.client_id,
                      "client_secret": self.client_secret, "scope": f"{self.org}/.default"}, timeout=60)
            r.raise_for_status()
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + body["expires_in"]
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                "OData-MaxVersion": "4.0", "OData-Version": "4.0"}

    def upsert(self, entity_set, key_field, key_value, record):
        """PATCH on an alternate key: creates if missing, updates otherwise.

        If-Match/If-None-Match are intentionally omitted so both outcomes are allowed.
        Returns "created" or "updated".
        """
        key = f"{key_field}='{key_value}'" if isinstance(key_value, str) else f"{key_field}={key_value}"
        r = self.http.patch(f"{self.api}/{entity_set}({key})", json=record, headers=self._auth(), timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            return self.upsert(entity_set, key_field, key_value, record)
        r.raise_for_status()
        return "created" if r.status_code == 201 else "updated"
