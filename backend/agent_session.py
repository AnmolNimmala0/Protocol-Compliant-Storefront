import uuid


# In-memory session registry.
#
# For the hackathon this is intentionally simple.
# PostgreSQL remains the source of truth for audit events.
_sessions = {}


def create_session():
    session_id = str(uuid.uuid4())

    _sessions[session_id] = {
        "status": "running",
        "mandate_id": None,
    }

    return session_id


def update_session(
    session_id,
    status=None,
    mandate_id=None
):
    session = _sessions.get(session_id)

    if session is None:
        return

    if status is not None:
        session["status"] = status

    if mandate_id is not None:
        session["mandate_id"] = mandate_id


def get_session(session_id):
    return _sessions.get(session_id)