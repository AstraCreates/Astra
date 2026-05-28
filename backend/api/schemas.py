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


class ContinueRequest(BaseModel):
    founder_id: str
    instruction: str
    prior_session_id: str
    agents: Optional[list[str]] = None  # if None, planner decides


class BrainSyncRequest(BaseModel):
    sources: Optional[list[str]] = None
    limit: int = 20


class BrainSyncConfigRequest(BaseModel):
    enabled: bool = True
    sources: Optional[list[str]] = None
    interval_minutes: int = 60


class BrainRecordRequest(BaseModel):
    source: str
    title: str
    content: str
    kind: str = "note"
    url: Optional[str] = ""
    canonical: bool = False
    stale_risk: str = "medium"


class BrainIngestRequest(BaseModel):
    source: str
    records: list[dict]


class BrainProposalRequest(BaseModel):
    status: str = "resolved"


class BrainAskRequest(BaseModel):
    question: str
    limit: int = 8


class StripeEINUpgradeRequest(BaseModel):
    founder_id: str
    ein: str
    business_name: str


class StripeProductRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    amount: int              # in cents, e.g. 2900 = $29.00
    currency: Optional[str] = "usd"
    interval: Optional[str] = ""   # "month", "year", or "" for one-time


class StripeWebhookRegisterRequest(BaseModel):
    founder_id: str
    backend_url: Optional[str] = "http://localhost:8000"
