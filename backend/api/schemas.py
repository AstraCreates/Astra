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
