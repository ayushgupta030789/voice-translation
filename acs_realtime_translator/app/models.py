import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TranslationCallSession:
    session_id: str
    incoming_language: str
    outbound_language: str
    outbound_phone_number: str

    incoming_call_connection_id: Optional[str] = None
    outbound_call_connection_id: Optional[str] = None
    incoming_connected: bool = False
    outbound_connected: bool = False
    outbound_started: bool = False
    closing: bool = False

    incoming_media_ws: Optional[Any] = None
    outbound_media_ws: Optional[Any] = None

    incoming_to_outbound_translator: Optional[Any] = None
    outbound_to_incoming_translator: Optional[Any] = None

    incoming_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    outbound_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
