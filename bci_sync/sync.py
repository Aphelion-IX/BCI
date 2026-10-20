"""Pull projects (and optionally companies) from BCI and upsert them into Dynamics 365."""
import argparse
import datetime
import logging
import os
import sys

import yaml

from .bci import BciClient
from .dynamics import DynamicsClient

log = logging.getLogger("bci_sync")


def convert(value):
    """Make BCI values Dataverse-friendly: drop empties, trim strings, ISO dates stay as-is."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value.strip() if isinstance(value, str) else value


def map_record(row, mapping):
    """mapping: {crm_field: BCI_FIELD}. Missing/empty BCI values are skipped."""
    out = {}
    for crm_field, bci_field in mapping.items():
        v = convert(row.get(bci_field.upper()))
        if v is not None:
            out[crm_field] = v
    return out


def build_filters(cfg):
    f = dict(cfg.get("filters") or {})
    for k, v in list(f.items()):
        if isinstance(v, (list, tuple)):
            f[k] = ",".join(map(str, v))
    return f


def sync_entity(rows, entity_cfg, crm, dry_run):
    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    key_crm, key_bci = entity_cfg["key"]["crm_field"], entity_cfg["key"]["bci_field"].upper()
    for row in rows:
        key = convert(row.get(key_bci))
        if key is None:
            counts["skipped"] += 1
            continue
        record = map_record(row, entity_cfg["mapping"])
        if dry_run:
            log.info("DRY RUN %s %s=%s %s", entity_cfg["entity_set"], key_crm, key, record)
            counts["skipped"] += 1
            continue
        try:
            counts[crm.upsert(entity_cfg["entity_set"], key_crm, key, record)] += 1
        except Exception as e:  # keep going; one bad row must not stop the batch
            log.error("upsert failed for %s=%s: %s", key_crm, key, e)
            counts["failed"] += 1
    return counts


def run(cfg, bci, crm, dry_run=False):
    filters = build_filters(cfg)
    if "updatedate" not in filters and "updatedate_from" not in filters:
        filters["updatedate"] = cfg.get("window_days", 2)  # overlapping window; upserts are idempotent
    projects_cfg = cfg["projects"]
    fields = sorted({v.upper() for v in projects_cfg["mapping"].values()} | {projects_cfg["key"]["bci_field"].upper()})
    projects = list(bci.projects(filters, fields=fields, since_last=cfg.get("since_last", False)))
    log.info("fetched %d projects from BCI", len(projects))
    results = {"projects": sync_entity(projects, projects_cfg, crm, dry_run)}

    companies_cfg = cfg.get("companies")
    if companies_cfg and companies_cfg.get("enabled") and projects:
        refids = [p["PROJECTREFID"] for p in projects if p.get("PROJECTREFID")]
        roles = list(bci.roles(refids, fields=["PROJECTREFID", "COMPANYID"]))
        company_ids = sorted({int(r["COMPANYID"]) for r in roles if r.get("COMPANYID")})
        cfields = sorted({v.upper() for v in companies_cfg["mapping"].values()} | {companies_cfg["key"]["bci_field"].upper()})
        companies = list(bci.companies(company_ids, fields=cfields))
        log.info("fetched %d companies from BCI", len(companies))
        results["companies"] = sync_entity(companies, companies_cfg, crm, dry_run)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="fetch from BCI and print mapped records; write nothing to CRM")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config) as fh:
        cfg = yaml.safe_load(fh)
    env = os.environ
    bci = BciClient(env["BCI_CLIENT_ID"], env["BCI_PASSWORD"])
    crm = None if args.dry_run else DynamicsClient(
        env["DYNAMICS_ORG_URL"], env["AZURE_TENANT_ID"], env["AZURE_CLIENT_ID"], env["AZURE_CLIENT_SECRET"])
    results = run(cfg, bci, crm, args.dry_run)
    log.info("done %s", results)
    return 1 if any(r["failed"] for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
