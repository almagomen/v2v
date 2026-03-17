"""Speakers and misc endpoints."""
from fastapi import APIRouter

from api.schemas import SpeakerOption
from api.service import SPEAKER_OPTIONS

router = APIRouter(prefix="/api", tags=["speakers"])


@router.get("/speakers", response_model=list[SpeakerOption])
def get_speakers():
    """Return list of available speaker/voice options."""
    return [SpeakerOption(label=k, value=v) for k, v in SPEAKER_OPTIONS.items()]
