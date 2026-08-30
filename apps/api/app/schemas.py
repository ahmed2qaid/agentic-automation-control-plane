from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

RiskLevel = Literal["low", "medium", "high", "critical"]
PolicyAction = Literal["allow", "require_approval", "deny"]


class WorkflowCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=2, max_length=180)
    description: str | None = None
    webhook_url: HttpUrl
    risk_level: RiskLevel = "medium"
    enabled: bool = True


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slug: str
    name: str
    description: str | None
    webhook_url: str
    risk_level: str
    enabled: bool
    created_at: datetime


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    action: PolicyAction
    risk_levels: list[RiskLevel] = Field(default_factory=list)
    workflow_id: str | None = None
    min_cost_usd: float | None = Field(default=None, ge=0)
    priority: int = Field(default=0, ge=0, le=1000)
    enabled: bool = True


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    action: str
    risk_levels: list[str]
    workflow_id: str | None
    min_cost_usd: float | None
    priority: int
    enabled: bool
    created_at: datetime


class ExecutionCreate(BaseModel):
    workflow_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = Field(default=0, ge=0)
    dry_run: bool = False
    requested_by: str = Field(default="anonymous", min_length=1, max_length=180)


class ReplayRequest(BaseModel):
    requested_by: str = Field(default="dashboard-user", min_length=1, max_length=180)
    dry_run: bool | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workflow_id: str
    status: str
    decision: str
    risk_level: str
    dry_run: bool
    estimated_cost_usd: float
    requested_by: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ExecutionRelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_execution_id: str
    target_execution_id: str
    relation_type: str
    actor: str
    created_at: datetime


class CostEventCreate(BaseModel):
    provider: str = Field(default="unknown", min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    execution_id: str
    provider: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    metadata_json: dict[str, Any]
    created_at: datetime


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    data: dict[str, Any]
    created_at: datetime


class TraceRead(BaseModel):
    execution: ExecutionRead
    workflow: WorkflowRead
    events: list[AuditRead]
    costs: list[CostEventRead]
    relations: list[ExecutionRelationRead]
    actual_cost_usd: float


class ApprovalDecision(BaseModel):
    approved: bool
    decided_by: str = Field(min_length=1, max_length=180)
    note: str | None = Field(default=None, max_length=2000)


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    execution_id: str
    status: str
    decided_by: str | None
    note: str | None
    requested_at: datetime
    decided_at: datetime | None


class N8nEvent(BaseModel):
    execution_id: str | None = None
    event_type: str = "n8n.event"
    status: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class N8nSyncResult(BaseModel):
    discovered: int
    imported: int
    updated: int
    skipped: int
    workflows: list[WorkflowRead]


class McpRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
