from pydantic import BaseModel
from typing import Optional


class GoalRequest(BaseModel):
    founder_id: str
    instruction: str
    stack_id: Optional[str] = None
    constraints: dict = {}
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None


class StackRecommendRequest(BaseModel):
    instruction: str
    company_stage: Optional[str] = None


class StackPackageRequest(BaseModel):
    instruction: str
    founder_id: Optional[str] = ""
    company_stage: Optional[str] = None
    company_name: Optional[str] = None


class ApproveRequest(BaseModel):
    task_id: str
    approval_token: str
    note: Optional[str] = None


class RejectRequest(BaseModel):
    task_id: str
    reason: str
    redirect_instruction: Optional[str] = None


class StackApprovalDecisionRequest(BaseModel):
    session_id: str
    gate_key: str
    decision: str  # "approved" | "skipped" | "rejected"
    founder_id: Optional[str] = None
    request_id: Optional[str] = None
    note: Optional[str] = None


class SessionAskRequest(BaseModel):
    question: str
    founder_id: Optional[str] = None


class AskRequest(BaseModel):
    target_agent: str
    question: str
    context: Optional[str] = None
    founder_id: str
    session_id: Optional[str] = None    # for Obsidian note lookup
    company_name: Optional[str] = None  # company name for this session
    goal: Optional[str] = None          # original goal/instruction


class SetupRequest(BaseModel):
    founder_id: str
    email: str
    password: str
    base_url: Optional[str] = "http://localhost:8000"
    stack_id: Optional[str] = ""
    required_only: bool = False
    include_foundation: bool = True
    preview_only: bool = False


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
    owner_id: Optional[str] = None
    visibility: str = "team"
    allowed_roles: Optional[list[str]] = None
    metadata: Optional[dict] = None


class BrainRecordRevisionRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    canonical: Optional[bool] = None
    stale_risk: Optional[str] = None
    editor_id: Optional[str] = None


class BrainAccessRequest(BaseModel):
    roles: Optional[dict[str, str]] = None
    role_permissions: Optional[dict[str, list[str]]] = None


class OrgMemberRequest(BaseModel):
    actor_id: str
    user_id: str
    role: str = "viewer"
    status: str = "active"


class OrgSubscriptionRequest(BaseModel):
    actor_id: str
    plan: Optional[str] = None
    status: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_end: Optional[str] = None


class OrgControlsRequest(BaseModel):
    actor_id: str
    controls: dict


class OrgUsageRequest(BaseModel):
    actor_id: str = "system"
    runs: int = 0
    connector_syncs: int = 0
    approval_decisions: int = 0


class BillingCheckoutRequest(BaseModel):
    plan: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    customer_email: Optional[str] = None


class BillingPortalRequest(BaseModel):
    return_url: Optional[str] = None


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


class InputResponse(BaseModel):
    data: dict  # field_name → value


class CustomStackRequest(BaseModel):
    agents: list[str]           # subset of ["research","legal","web","marketing","technical","ops"]
    instruction: str
    founder_id: Optional[str] = ""
    company_name: Optional[str] = None
