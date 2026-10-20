"""Sample data so the UI is usable before any API credentials are configured."""

BCI = [
    {"PROJECTREFID": 10037304, "PROJECT_NAME": "Esperance Primary School - redevelopment", "ADDRESS": "106 Andrew St",
     "TOWN": "Esperance", "POSTCODE": 6450, "VALUE": 11500000, "PROJECT_STATUS": "Construction Commenced", "PROJECTSTAGE": "Construction"},
    {"PROJECTREFID": 10041022, "PROJECT_NAME": "Harbour Point Apartments Stage 2", "ADDRESS": "14 Marine Parade",
     "TOWN": "Fremantle", "POSTCODE": 6160, "VALUE": 62000000, "PROJECT_STATUS": "Tender", "PROJECTSTAGE": "Tendering"},
    {"PROJECTREFID": 10050311, "PROJECT_NAME": "Westfield Logistics Hub", "ADDRESS": "Lot 5 Dunn Rd",
     "TOWN": "Kwinana", "POSTCODE": 6167, "VALUE": 38000000, "PROJECT_STATUS": "Documentation", "PROJECTSTAGE": "Design"},
    {"PROJECTREFID": 10052870, "PROJECT_NAME": "Mount Lawley Medical Centre", "ADDRESS": "220 Beaufort Street",
     "TOWN": "Mount Lawley", "POSTCODE": 6050, "VALUE": 9400000, "PROJECT_STATUS": "Tender", "PROJECTSTAGE": "Tendering"},
    {"PROJECTREFID": 10053001, "PROJECT_NAME": "Bunbury Aquatic Centre Upgrade", "ADDRESS": "Blair St",
     "TOWN": "Bunbury", "POSTCODE": 6230, "VALUE": 21000000, "PROJECT_STATUS": "Planning", "PROJECTSTAGE": "Planning"},
]

def _e1(pid, name, address, due, low, builder):
    """Raw EstimateOne Speci-finder project, as the real API returns it."""
    return {"projectId": pid, "projectName": name, "address": address, "category": "Commercial", "status": "Active",
            "budget": {"low": low, "high": None}, "url": f"https://app.estimateone.com/project/{pid}",
            "consultants": [], "tenderingSubcontractors": [],
            "tenders": [{"id": pid + "-t1", "name": "Main works", "type": "Tender", "builder": {"name": builder, "website": None},
                         "tenderOpenAt": None, "quotesDueAt": due, "status": "Open", "matchedKeywords": ["demo"]}]}


E1 = [
    _e1("e1-881", "Esperance Primary School Redevelopment", "106 Andrew Street, Esperance WA 6450", "2026-11-12", 10000000, "Pindan"),
    _e1("e1-902", "Harbour Point Apartments - Stage 2", "14 Marine Pde, Fremantle WA 6160", "2026-11-20", 55000000, "Probuild"),
    _e1("e1-933", "Medical Centre Fitout", "220 Beaufort St, Mount Lawley WA 6050", "2026-11-05", 3000000, "Doric"),
    _e1("e1-950", "Joondalup Library Refurbishment", "102 Boas Ave, Joondalup WA 6027", "2026-12-01", 4500000, "Hall & Prior"),
]


class DemoBci:
    def projects(self, filters, fields=None, since_last=False):
        return iter(BCI)

    def roles(self, projectrefids, fields=None):
        return iter([])

    def companies(self, companyids, fields=None):
        return iter([])


class DemoE1:
    def results(self):
        return iter(E1)
