"""STUB. Owner: mass-ingest agent. Ingest a bike's free official manual on first request, once, and cache it."""


def ensure(bike_id: str) -> dict:
    """{"status": "ready"|"running"|"none", "manualId": str|None, "jobId": str|None, "done": int, "pages": int}"""
    return {"status": "none", "manualId": None, "jobId": None, "done": 0, "pages": 0}
