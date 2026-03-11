"""Pydantic models for request/response validation."""
from pydantic import BaseModel


class LoginRequest(BaseModel):
    code: str


class MessageRequest(BaseModel):
    content: str


class NewSessionRequest(BaseModel):
    persona_id: str
    scenario_number: int
    mission: str | None = None  # "A", "B", "C", or None for open dialog
