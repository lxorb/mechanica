"""GET /cost/ttc - what The Token Company middleware saved. Owner: chat agent.

Kept out of /cost on purpose: /cost reports dollars spent at an OpenAI price, and compression spends
nothing. Its unit is tokens removed before the prompt was ever billed, counted per route in app/ttc.py.
"""

from fastapi import APIRouter

from . import ttc

router = APIRouter()


@router.get("/cost/ttc")
def cost_ttc():
    return ttc.stats()
