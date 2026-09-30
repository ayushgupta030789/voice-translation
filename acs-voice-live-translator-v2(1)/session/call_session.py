import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CallSession:
    session_id: str
    language_a: str
    language_b: str

    incoming_call_id: Optional[str] = None
    outbound_call_id: Optional[str] = None

    incoming_call_connection = None
    outbound_call_connection = None

    ws_a = None
    ws_b = None

    translator_a_to_b = None
    translator_b_to_a = None

    call_a_connected: asyncio.Event = field(default_factory=asyncio.Event)
    call_b_connected: asyncio.Event = field(default_factory=asyncio.Event)
    media_a_connected: asyncio.Event = field(default_factory=asyncio.Event)
    media_b_connected: asyncio.Event = field(default_factory=asyncio.Event)

    closed: bool = False

    async def close(self):
        self.closed = True

        for translator in (self.translator_a_to_b, self.translator_b_to_a):
            if translator:
                try:
                    await translator.close()
                except Exception:
                    pass

        for ws in (self.ws_a, self.ws_b):
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass


class SessionStore:
    def __init__(self):
        self._sessions = {}

    def create(self, session: CallSession):
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str):
        return self._sessions.get(session_id)

    def remove(self, session_id: str):
        return self._sessions.pop(session_id, None)

    def all(self):
        return self._sessions


sessions = SessionStore()
