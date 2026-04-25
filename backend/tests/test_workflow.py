from workflow import (
    STATE_CREATED,
    STATE_FACE_VERIFIED,
    STATE_INTERVIEW_FINISHED,
    STATE_INTERVIEW_IN_PROGRESS,
    STATE_RESUME_UPLOADED,
    can_transition,
    validate_or_none,
)


def test_workflow_valid_transitions():
    assert can_transition(STATE_CREATED, STATE_RESUME_UPLOADED)
    assert can_transition(STATE_RESUME_UPLOADED, STATE_FACE_VERIFIED)
    assert can_transition(STATE_FACE_VERIFIED, STATE_INTERVIEW_IN_PROGRESS)
    assert can_transition(STATE_INTERVIEW_IN_PROGRESS, STATE_INTERVIEW_FINISHED)


def test_workflow_invalid_transitions():
    assert not can_transition(STATE_CREATED, STATE_FACE_VERIFIED)
    assert not can_transition(STATE_RESUME_UPLOADED, STATE_INTERVIEW_FINISHED)
    assert not can_transition(STATE_INTERVIEW_FINISHED, STATE_CREATED)


def test_validate_or_none():
    assert validate_or_none("INVALID") is None
    assert validate_or_none(None) is None
    assert validate_or_none(STATE_INTERVIEW_IN_PROGRESS) == STATE_INTERVIEW_IN_PROGRESS
