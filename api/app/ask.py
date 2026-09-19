"""STUB. Owner: search agent.

answer(): router (MODEL_ROUTER, structured) -> get_index().query / .spec -> picker (MODEL_PICKER, structured, ids only,
server-validated) -> AskResponse. Spec intents answer with zero picker call.
"""

from .models import AskResponse


def answer(manual_id: str, query: str) -> AskResponse:
    raise NotImplementedError
