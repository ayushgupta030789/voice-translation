import asyncio
from typing import Optional
from app.models import TranslationCallSession


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TranslationCallSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: TranslationCallSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Optional[TranslationCallSession]:
        return self._sessions.get(session_id)

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)


session_manager = SessionManager()
