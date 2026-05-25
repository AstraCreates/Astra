from pydantic import BaseModel
from typing import Optional


class GoalRequest(BaseModel):
    founder_id: str
    instruction: str
    constraints: dict = {}


class ApproveRequest(BaseModel):
    task_id: str
    approval_token: str
    note: Optional[str] = None


class RejectRequest(BaseModel):
    task_id: str
    reason: str
    redirect_instruction: Optional[str] = None


class AskRequest(BaseModel):
    target_agent: str
    question: str
    context: Optional[str] = None
    founder_id: str


class SetupRequest(BaseModel):
    founder_id: str
    email: str
    password: str
    base_url: Optional[str] = "http://localhost:8000"


class SaveCredentialRequest(BaseModel):
    founder_id: str
    service: str  # "github" | "sendgrid" | "vercel" | "composio"
    credentials: dict  # e.g. {"token": "ghp_..."} or {"api_key": "SG...."}


class SteerRequest(BaseModel):
    session_id: str
    message: str  # founder directive to the orchestrator mid-run
