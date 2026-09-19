"""STUB. Owner: voice agent. ElevenLabs Agents webhook tools + Deepgram temp keys."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/config")
def config():
    raise HTTPException(501)
