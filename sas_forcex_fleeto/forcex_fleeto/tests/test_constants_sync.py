"""Guard-rail tests: catch "added a value in one place but not the other"."""

import glob
import json
import os
import unittest

from sas_forcex_fleeto.forcex_fleeto.services import ticket_flow
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    COMPONENT_ROUTE,
    ComponentType,
    Status,
    TicketType,
)

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..", "doctype")


class TestConstantsSync(unittest.TestCase):
    def test_every_component_has_a_route(self):
        self.assertEqual(set(COMPONENT_ROUTE), set(ComponentType.values()))

    def test_every_status_is_used_by_some_track(self):
        used = set()
        for lane in ticket_flow.TRANSITIONS.values():
            used |= set(lane) | {s for targets in lane.values() for s in targets}
        self.assertEqual(set(Status.values()) - used, set())

    def test_every_track_is_defined(self):
        self.assertEqual(set(ticket_flow.TRANSITIONS), set(TicketType.values()))

    def test_doctype_select_options_match_constants(self):
        """If a DocType JSON exists (after `bench export`), its Select options
        for status / component_type must equal the Python enums."""
        enums = {"component_type": set(ComponentType.values())}
        for path in glob.glob(os.path.join(DOCTYPE_DIR, "fx_material_inspection", "fx_material_inspection.json")):
            with open(path) as f:
                fields = {d["fieldname"]: d for d in json.load(f)["fields"]}
            for name, expected in enums.items():
                if name in fields:
                    opts = {o for o in fields[name].get("options", "").split("\n") if o}
                    self.assertEqual(opts, expected, f"{name} options out of sync in {path}")


if __name__ == "__main__":
    unittest.main()
