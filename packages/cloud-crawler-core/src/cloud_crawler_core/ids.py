"""Record identifiers: a short prefix and a time-ordered UUID (version 7), so a ledger sorts by creation."""

from __future__ import annotations

import uuid

PREFIXES = {
    "evidence": "ev",
    "decision": "dec",
    "claim": "clm",
    "alternative": "alt",
    "finding": "fnd",
    "contradiction": "ctr",
    "proposal": "prp",
    "approval": "apr",
    "run": "run",
}


def new_id(kind: str) -> str:
    """`ev_<uuid7>`, `dec_<uuid7>`, ... Raises KeyError for an unknown kind, on purpose: ids are never ad hoc."""
    return f"{PREFIXES[kind]}_{uuid.uuid7()}"
