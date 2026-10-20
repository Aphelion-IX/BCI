# BCI → Dynamics 365 sync

Pulls newly updated construction projects (and optionally their companies) from the
[BCI Australia API](https://api.bciaustralia.com/doc/home.htm) and upserts them into Dynamics 365 / Dataverse.
Runs daily via GitHub Actions; safe to re-run (upserts on an alternate key).

## Setup
1. **Dataverse**: create a table for projects (default `new_bciprojects`) with the columns in `config.yaml`,
   and define an **alternate key** on `new_bciprojectrefid` (whole number). For companies, add an alternate key
   `new_bcicompanyid` to Account. Edit `config.yaml` to match your real column names.
2. **Azure**: register an app, create a secret, and add it as an Application User in Dynamics with write access to those tables.
3. **GitHub secrets**: `BCI_CLIENT_ID`, `BCI_PASSWORD`, `DYNAMICS_ORG_URL` (e.g. `https://org.crm6.dynamics.com`),
   `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`.
4. Set your `filters` (states, categories, stages, value...) in `config.yaml`.
5. Run the workflow manually with **dry run** first, check the log, then let the schedule take over.

## EstimateOne (Speci-finder)
A second source: matched open tenders from the EstimateOne Supplier API
(`GET /api/tender/supplier/v1/companies/{companyId}/speci-finder/results`, OAuth2 client credentials, scope `speci-finder/read`).
Set `estimateone.enabled: true` in `config.yaml`, add secrets `E1_CLIENT_ID`, `E1_CLIENT_SECRET`, `E1_COMPANY_ID`
(your "Account #"), and create the `new_e1projects` table with an alternate key on `new_e1projectid` (text).
Each project is flattened to one row (earliest-closing tender for the headline columns; consultants, subcontractors,
keywords joined). The client follows the cursor pagination and backs off on 429/5xx (limit is 100 requests per 5 minutes).
Note: the API only returns data if Speci-finder keywords are configured on the E1 account; consultants need the E1 add-on.

```
python -m bci_sync.sync --source estimateone --dry-run
python -m bci_sync.sync --source estimateone --export-only --export-e1-xml e1.xml
```

## Web console (cross-reference + automations)
```
python -m bci_sync.webapp        # http://127.0.0.1:8080
```
- **Cross-reference**: pairs BCI projects with EstimateOne matches by name and address similarity (adjustable threshold),
  lists what is only in one system, lets you confirm / reject / manually link pairs (saved in `data/links.json`), and exports XML.
- **Automations**: saved jobs with sources, BCI filters, an action (`preview`, `xml`, or `crm` sync to Dynamics), optional
  cross-reference, and a schedule (manual, every N minutes, daily). Schedules run while the web server is running.
- **Run history**: results, counts and links to exported files (`data/exports/`).
- Uses the same env vars as the CLI. Any source without credentials runs on built-in **demo data** (badge in the header).
- The app has **no login** and can write to your CRM, so it binds to `127.0.0.1` by default. Don't expose it (`HOST=0.0.0.0`)
  without putting authentication in front of it. Credentials stay server-side and are never sent to the browser.
- The GitHub Actions cron and the in-app scheduler are independent; use one or the other for the same job.

## Local use
```
pip install -r requirements.txt
export BCI_CLIENT_ID=... BCI_PASSWORD=...
python -m bci_sync.sync --dry-run      # fetch + show mapped records only
python -m bci_sync.sync --export-xml out.xml --export-only   # XML file only, no CRM needed
python -m pytest
```
`--export-xml` can also be combined with a normal run to save a copy of each batch.

## Notes
- Incremental by default: each run fetches projects updated in the last `window_days` (overlap makes missed runs harmless).
- Written against the BCI docs without live credentials: the exact JSON shape is handled defensively, but do a dry run first
  and adjust `mapping` / field names if BCI returns something different.
- Contacts (people) are not synced yet; add via the BCI `contacts` API if needed.
