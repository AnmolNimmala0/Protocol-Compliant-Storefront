import uuid
from threading import Lock


_sessions = {}
_sessions_lock = Lock()


def create_session():
    session_id = str(uuid.uuid4())

    with _sessions_lock:
        _sessions[session_id] = {
            "status": "running",
            "mandate_id": None,
            "answer": None,
            "messages": [],
        }

    return session_id


def update_session(
    session_id,
    status=None,
    mandate_id=None,
    answer=None,
):
    with _sessions_lock:
        session = _sessions.get(session_id)

        if session is None:
            return

        if status is not None:
            session["status"] = status

        if mandate_id is not None:
            session["mandate_id"] = mandate_id

        if answer is not None:
            session["answer"] = answer


def add_message(
    session_id,
    role,
    content,
):
    with _sessions_lock:
        session = _sessions.get(session_id)

        if session is None:
            return

        session["messages"].append({
            "role": role,
            "content": content,
        })


def get_messages(session_id):
    with _sessions_lock:
        session = _sessions.get(session_id)

        if session is None:
            return []

        return list(session["messages"])


def get_session(session_id):
    with _sessions_lock:
        session = _sessions.get(session_id)

        if session is None:
            return None

        return {
            "status": session["status"],
            "mandate_id": session["mandate_id"],
            "answer": session["answer"],
            "messages": list(session["messages"]),
        }