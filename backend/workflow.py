"""
Session workflow/state-machine for interview module orchestration.
"""

from typing import Dict, Optional

STATE_CREATED = "CREATED"
STATE_RESUME_UPLOADED = "RESUME_UPLOADED"
STATE_FACE_VERIFIED = "FACE_VERIFIED"
STATE_INTERVIEW_IN_PROGRESS = "INTERVIEW_IN_PROGRESS"
STATE_INTERVIEW_FINISHED = "INTERVIEW_FINISHED"

VALID_STATES = {
    STATE_CREATED,
    STATE_RESUME_UPLOADED,
    STATE_FACE_VERIFIED,
    STATE_INTERVIEW_IN_PROGRESS,
    STATE_INTERVIEW_FINISHED,
}

# Allowed "next states" from a current state
ALLOWED_TRANSITIONS: Dict[str, set] = {
    STATE_CREATED: {STATE_RESUME_UPLOADED},
    STATE_RESUME_UPLOADED: {STATE_FACE_VERIFIED},
    STATE_FACE_VERIFIED: {STATE_INTERVIEW_IN_PROGRESS},
    STATE_INTERVIEW_IN_PROGRESS: {STATE_INTERVIEW_FINISHED},
    STATE_INTERVIEW_FINISHED: set(),
}


def can_transition(current_state: str, next_state: str) -> bool:
    if current_state not in VALID_STATES or next_state not in VALID_STATES:
        return False
    if current_state == next_state:
        return True
    return next_state in ALLOWED_TRANSITIONS.get(current_state, set())


def validate_or_none(state: Optional[str]) -> Optional[str]:
    if not state:
        return None
    if state in VALID_STATES:
        return state
    return None
