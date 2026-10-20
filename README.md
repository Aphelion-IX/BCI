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
