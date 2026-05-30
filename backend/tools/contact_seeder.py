"""
Contact seeder — stub only.

The contact database is now populated dynamically by the Sales agent using
Hunter.io domain search based on the founder's specific ICP. There is no
static pre-seed. See backend/specialists/sales.py for the flow.
"""

GLOBAL_FOUNDER_ID = "__global__"


def is_seeding(founder_id: str) -> bool:  # noqa: ARG001
    return False


def seed_contact_database(founder_id: str = GLOBAL_FOUNDER_ID) -> dict:
    return {"status": "noop", "note": "Seeding is now handled by the Sales agent per ICP."}
