import json
from datetime import UTC, datetime
from secrets import compare_digest
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine, get_db
from .models import (
    Approval,
    AuditEvent,
    CostEvent,
    Execution,
    ExecutionRelation,
    Policy,
    Workflow,
)
from .n8n import N8nInvocationError, N8nSyncError, fetch_n8n_workflows, invoke_n8n
from .policy_engine import PolicyContext, evaluate
from .schemas import (
    ApprovalDecision,
    ApprovalRead,
    AuditRead,
    CostEventCreate,
    CostEventRead,
    ExecutionCreate,
    ExecutionRead,
    McpRequest,
    N8nEvent,
    N8nSyncResult,
    PolicyCreate,
    PolicyRead,
    ReplayRequest,
    TraceRead,
    WorkflowCreate,
    WorkflowRead,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> datetime:
    return datetime.now(UTC)


def record_audit(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    data: dict,
) -> None:
    db.add(
        AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            data=data,
        )
    )


def run_execution(db: Session, execution: Execution, workflow: Workflow, actor: str) -> None:
    execution.status = "running"
    execution.started_at = now()
    record_audit(
        db,
        "execution.started",
        "execution",
        execution.id,
        actor,
        {"workflow_id": workflow.id},
    )
    db.commit()
    try:
        output = invoke_n8n(workflow.webhook_url, execution.id, execution.input)
        execution.status = "completed"
        execution.output = output
        execution.finished_at = now()
        record_audit(db, "execution.completed", "execution", execution.id, "n8n", output)
    except N8nInvocationError as exc:
        execution.status = "failed"
        execution.error = str(exc)
        execution.finished_at = now()
        record_audit(
            db,
            "execution.failed",
            "execution",
            execution.id,
            "system",
            {"error": str(exc)},
        )
    db.commit()
    db.refresh(execution)


def seed_defaults(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Workflow)) == 0:
        db.add(
            Workflow(
                slug="guarded-action-demo",
                name="Guarded Action Demo",
                description="High-risk example that demonstrates the approval gate before n8n execution.",
                webhook_url="http://n8n:5678/webhook/guarded-action",
                risk_level="high",
            )
        )
    if db.scalar(select(func.count()).select_from(Policy)) == 0:
        db.add_all(
            [
                Policy(
                    name="Deny critical operations",
                    action="deny",
                    risk_levels=["critical"],
                    priority=100,
                ),
                Policy(
                    name="Approve high-risk operations",
                    action="require_approval",
                    risk_levels=["high"],
                    priority=90,
                ),
                Policy(
                    name="Approve expensive operations",
                    action="require_approval",
                    risk_levels=[],
                    min_cost_usd=settings.max_auto_cost_usd,
                    priority=80,
                ),
                Policy(
                    name="Allow routine operations",
                    action="allow",
                    risk_levels=["low", "medium"],
                    priority=10,
                ),
            ]
        )
    db.commit()


def create_execution_record(
    db: Session,
    payload: ExecutionCreate,
    *,
    relation_from: Execution | None = None,
    relation_type: str | None = None,
) -> Execution:
    workflow = db.get(Workflow, payload.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not workflow.enabled:
        raise HTTPException(status_code=409, detail="Workflow is disabled")

    policies = db.scalars(select(Policy).where(Policy.enabled.is_(True))).all()
    decision = evaluate(
        PolicyContext(
            workflow_id=workflow.id,
            risk_level=workflow.risk_level,
            estimated_cost_usd=payload.estimated_cost_usd,
            dry_run=payload.dry_run,
        ),
        policies,
        settings.max_auto_cost_usd,
    )
    status_map = {
        "dry_run": "dry_run",
        "deny": "denied",
        "require_approval": "pending_approval",
        "allow": "queued",
    }
    execution = Execution(
        workflow_id=workflow.id,
        status=status_map[decision.action],
        decision=decision.action,
        risk_level=workflow.risk_level,
        dry_run=payload.dry_run,
        estimated_cost_usd=payload.estimated_cost_usd,
        requested_by=payload.requested_by,
        input=payload.input,
    )
    db.add(execution)
    db.flush()

    if relation_from and relation_type:
        db.add(
            ExecutionRelation(
                source_execution_id=relation_from.id,
                target_execution_id=execution.id,
                relation_type=relation_type,
                actor=payload.requested_by,
            )
        )
        record_audit(
            db,
            f"execution.{relation_type}",
            "execution",
            execution.id,
            payload.requested_by,
            {"source_execution_id": relation_from.id},
        )

    record_audit(
        db,
        "execution.requested",
        "execution",
        execution.id,
        payload.requested_by,
        {
            "decision": decision.action,
            "reason": decision.reason,
            "policy_id": decision.policy_id,
        },
    )

    if decision.action == "require_approval":
        approval = Approval(execution_id=execution.id)
        db.add(approval)
        db.flush()
        record_audit(
            db,
            "approval.requested",
            "approval",
            approval.id,
            "system",
            {"execution_id": execution.id},
        )

    db.commit()
    db.refresh(execution)

    if decision.action == "allow":
        run_execution(db, execution, workflow, payload.requested_by)
    return execution


def trace_for_execution(db: Session, execution_id: str) -> dict[str, Any]:
    execution = db.get(Execution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    workflow = db.get(Workflow, execution.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    approval_ids = select(Approval.id).where(Approval.execution_id == execution.id)
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(
                or_(
                    (AuditEvent.entity_type == "execution")
                    & (AuditEvent.entity_id == execution.id),
                    (AuditEvent.entity_type == "approval")
                    & (AuditEvent.entity_id.in_(approval_ids)),
                )
            )
            .order_by(AuditEvent.created_at.asc())
        ).all()
    )
    costs = list(
        db.scalars(
            select(CostEvent)
            .where(CostEvent.execution_id == execution.id)
            .order_by(CostEvent.created_at.asc())
        ).all()
    )
    relations = list(
        db.scalars(
            select(ExecutionRelation)
            .where(
                or_(
                    ExecutionRelation.source_execution_id == execution.id,
                    ExecutionRelation.target_execution_id == execution.id,
                )
            )
            .order_by(ExecutionRelation.created_at.asc())
        ).all()
    )
    return {
        "execution": execution,
        "workflow": workflow,
        "events": events,
        "costs": costs,
        "relations": relations,
        "actual_cost_usd": sum(item.cost_usd for item in costs),
    }


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        seed_defaults(db)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "flowguard-api", "version": "0.2.0"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    workflows = db.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all()
    executions = db.scalars(
        select(Execution).order_by(Execution.created_at.desc()).limit(12)
    ).all()
    approvals = db.scalars(
        select(Approval)
        .where(Approval.status == "pending")
        .order_by(Approval.requested_at.desc())
    ).all()
    policies = db.scalars(
        select(Policy)
        .where(Policy.enabled.is_(True))
        .order_by(Policy.priority.desc())
    ).all()
    actual_cost = db.scalar(select(func.coalesce(func.sum(CostEvent.cost_usd), 0.0))) or 0.0
    return {
        "metrics": {
            "workflows": len(workflows),
            "enabled_workflows": sum(1 for item in workflows if item.enabled),
            "pending_approvals": len(approvals),
            "recent_failures": sum(1 for item in executions if item.status == "failed"),
            "active_policies": len(policies),
            "actual_cost_usd": float(actual_cost),
        },
        "workflows": [WorkflowRead.model_validate(item) for item in workflows],
        "executions": [ExecutionRead.model_validate(item) for item in executions],
        "approvals": [ApprovalRead.model_validate(item) for item in approvals],
        "policies": [PolicyRead.model_validate(item) for item in policies],
    }


@app.post("/api/workflows", response_model=WorkflowRead, status_code=201)
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db)) -> Workflow:
    workflow = Workflow(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        webhook_url=str(payload.webhook_url),
        risk_level=payload.risk_level,
        enabled=payload.enabled,
    )
    db.add(workflow)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Workflow slug already exists") from exc
    db.refresh(workflow)
    record_audit(
        db,
        "workflow.registered",
        "workflow",
        workflow.id,
        "api",
        {"slug": workflow.slug},
    )
    db.commit()
    return workflow


@app.get("/api/workflows", response_model=list[WorkflowRead])
def list_workflows(db: Session = Depends(get_db)) -> list[Workflow]:
    return list(db.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all())


@app.post("/api/workflows/sync/n8n", response_model=N8nSyncResult)
def sync_n8n_workflows(db: Session = Depends(get_db)) -> dict:
    try:
        discovered = fetch_n8n_workflows()
    except N8nSyncError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    imported = 0
    updated = 0
    skipped = 0
    touched: list[Workflow] = []

    for item in discovered:
        workflow = db.scalar(select(Workflow).where(Workflow.slug == item["slug"]))
        if workflow:
            changed = any(
                [
                    workflow.name != item["name"],
                    workflow.webhook_url != item["webhook_url"],
                    workflow.enabled != item["enabled"],
                ]
            )
            if changed:
                workflow.name = item["name"]
                workflow.webhook_url = item["webhook_url"]
                workflow.enabled = item["enabled"]
                workflow.description = item["description"]
                updated += 1
                record_audit(
                    db,
                    "workflow.synced",
                    "workflow",
                    workflow.id,
                    "n8n-sync",
                    {"external_id": item["external_id"], "mode": "updated"},
                )
            else:
                skipped += 1
            touched.append(workflow)
            continue

        workflow = Workflow(
            slug=item["slug"],
            name=item["name"],
            description=item["description"],
            webhook_url=item["webhook_url"],
            risk_level="medium",
            enabled=item["enabled"],
        )
        db.add(workflow)
        db.flush()
        imported += 1
        touched.append(workflow)
        record_audit(
            db,
            "workflow.synced",
            "workflow",
            workflow.id,
            "n8n-sync",
            {"external_id": item["external_id"], "mode": "imported"},
        )

    db.commit()
    for workflow in touched:
        db.refresh(workflow)
    return {
        "discovered": len(discovered),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "workflows": touched,
    }


@app.post("/api/policies", response_model=PolicyRead, status_code=201)
def create_policy(payload: PolicyCreate, db: Session = Depends(get_db)) -> Policy:
    if payload.workflow_id and not db.get(Workflow, payload.workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    policy = Policy(**payload.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    record_audit(
        db,
        "policy.created",
        "policy",
        policy.id,
        "api",
        {"action": policy.action, "priority": policy.priority},
    )
    db.commit()
    return policy


@app.get("/api/policies", response_model=list[PolicyRead])
def list_policies(db: Session = Depends(get_db)) -> list[Policy]:
    return list(
        db.scalars(select(Policy).order_by(Policy.priority.desc(), Policy.created_at.desc())).all()
    )


@app.post("/api/executions", response_model=ExecutionRead, status_code=201)
def create_execution(payload: ExecutionCreate, db: Session = Depends(get_db)) -> Execution:
    return create_execution_record(db, payload)


@app.get("/api/executions", response_model=list[ExecutionRead])
def list_executions(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Execution]:
    return list(
        db.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(limit)).all()
    )


@app.get("/api/executions/{execution_id}/trace", response_model=TraceRead)
def execution_trace(execution_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return trace_for_execution(db, execution_id)


@app.post("/api/executions/{execution_id}/retry", response_model=ExecutionRead, status_code=201)
def retry_execution(
    execution_id: str,
    payload: ReplayRequest,
    db: Session = Depends(get_db),
) -> Execution:
    source = db.get(Execution, execution_id)
    if not source:
        raise HTTPException(status_code=404, detail="Execution not found")
    if source.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed executions can be retried")
    return create_execution_record(
        db,
        ExecutionCreate(
            workflow_id=source.workflow_id,
            input=source.input,
            estimated_cost_usd=(
                payload.estimated_cost_usd
                if payload.estimated_cost_usd is not None
                else source.estimated_cost_usd
            ),
            dry_run=payload.dry_run if payload.dry_run is not None else source.dry_run,
            requested_by=payload.requested_by,
        ),
        relation_from=source,
        relation_type="retry",
    )


@app.post("/api/executions/{execution_id}/replay", response_model=ExecutionRead, status_code=201)
def replay_execution(
    execution_id: str,
    payload: ReplayRequest,
    db: Session = Depends(get_db),
) -> Execution:
    source = db.get(Execution, execution_id)
    if not source:
        raise HTTPException(status_code=404, detail="Execution not found")
    return create_execution_record(
        db,
        ExecutionCreate(
            workflow_id=source.workflow_id,
            input=source.input,
            estimated_cost_usd=(
                payload.estimated_cost_usd
                if payload.estimated_cost_usd is not None
                else source.estimated_cost_usd
            ),
            dry_run=payload.dry_run if payload.dry_run is not None else True,
            requested_by=payload.requested_by,
        ),
        relation_from=source,
        relation_type="replay",
    )


@app.post("/api/executions/{execution_id}/costs", response_model=CostEventRead, status_code=201)
def record_cost(
    execution_id: str,
    payload: CostEventCreate,
    x_flowguard_secret: str = Header(default=""),
    db: Session = Depends(get_db),
) -> CostEvent:
    if not compare_digest(x_flowguard_secret, settings.n8n_shared_secret):
        raise HTTPException(status_code=401, detail="Invalid FlowGuard secret")
    if not db.get(Execution, execution_id):
        raise HTTPException(status_code=404, detail="Execution not found")
    event = CostEvent(
        execution_id=execution_id,
        provider=payload.provider,
        model=payload.model,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cost_usd=payload.cost_usd,
        metadata_json=payload.metadata,
    )
    db.add(event)
    db.flush()
    record_audit(
        db,
        "cost.recorded",
        "execution",
        execution_id,
        payload.provider,
        {
            "model": payload.model,
            "input_tokens": payload.input_tokens,
            "output_tokens": payload.output_tokens,
            "cost_usd": payload.cost_usd,
        },
    )
    db.commit()
    db.refresh(event)
    return event


@app.get("/api/approvals", response_model=list[ApprovalRead])
def list_approvals(
    status: str = Query(default="pending"),
    db: Session = Depends(get_db),
) -> list[Approval]:
    statement = select(Approval).order_by(Approval.requested_at.desc())
    if status != "all":
        statement = statement.where(Approval.status == status)
    return list(db.scalars(statement).all())


@app.post("/api/approvals/{approval_id}/decision", response_model=ExecutionRead)
def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
) -> Execution:
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval has already been decided")
    execution = db.get(Execution, approval.execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    workflow = db.get(Workflow, execution.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    approval.status = "approved" if payload.approved else "rejected"
    approval.decided_by = payload.decided_by
    approval.note = payload.note
    approval.decided_at = now()
    record_audit(
        db,
        f"approval.{approval.status}",
        "approval",
        approval.id,
        payload.decided_by,
        {"execution_id": execution.id, "note": payload.note},
    )

    if not payload.approved:
        execution.status = "rejected"
        execution.finished_at = now()
        db.commit()
        db.refresh(execution)
        return execution

    execution.decision = "allow"
    db.commit()
    run_execution(db, execution, workflow, payload.decided_by)
    return execution


@app.get("/api/audit", response_model=list[AuditRead])
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    return list(
        db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    )


@app.post("/api/webhooks/n8n/events")
def receive_n8n_event(
    payload: N8nEvent,
    x_flowguard_secret: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict:
    if not compare_digest(x_flowguard_secret, settings.n8n_shared_secret):
        raise HTTPException(status_code=401, detail="Invalid FlowGuard secret")

    entity_id = payload.execution_id or "external"
    if payload.execution_id and payload.status:
        execution = db.get(Execution, payload.execution_id)
        if execution:
            execution.status = payload.status
            if payload.status in {"completed", "failed", "rejected"}:
                execution.finished_at = now()
    record_audit(db, payload.event_type, "execution", entity_id, "n8n", payload.data)
    db.commit()
    return {"accepted": True, "execution_id": payload.execution_id}


MCP_TOOLS = [
    {
        "name": "flowguard.list_workflows",
        "description": "List workflows registered in the FlowGuard control plane.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "flowguard.request_execution",
        "description": "Request a guarded workflow execution. Policy and approval rules always apply.",
        "inputSchema": {
            "type": "object",
            "required": ["workflow_id"],
            "properties": {
                "workflow_id": {"type": "string"},
                "input": {"type": "object"},
                "estimated_cost_usd": {"type": "number", "minimum": 0},
                "dry_run": {"type": "boolean"},
                "requested_by": {"type": "string"},
            },
        },
    },
    {
        "name": "flowguard.execution_trace",
        "description": "Read the audit, cost, and retry/replay trace for one execution.",
        "inputSchema": {
            "type": "object",
            "required": ["execution_id"],
            "properties": {"execution_id": {"type": "string"}},
        },
    },
]


def mcp_result(request_id: str | int | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def mcp_error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@app.post("/mcp")
def mcp_gateway(payload: McpRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.method == "initialize":
        return mcp_result(
            payload.id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "flowguard", "version": "0.2.0"},
            },
        )

    if payload.method == "tools/list":
        return mcp_result(payload.id, {"tools": MCP_TOOLS})

    if payload.method != "tools/call":
        return mcp_error(payload.id, -32601, f"Method not found: {payload.method}")

    name = str(payload.params.get("name", ""))
    arguments = payload.params.get("arguments") or {}

    try:
        if name == "flowguard.list_workflows":
            workflows = list(
                db.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all()
            )
            data = [WorkflowRead.model_validate(item).model_dump(mode="json") for item in workflows]
        elif name == "flowguard.request_execution":
            execution = create_execution_record(
                db,
                ExecutionCreate(
                    workflow_id=str(arguments.get("workflow_id", "")),
                    input=arguments.get("input") or {},
                    estimated_cost_usd=float(arguments.get("estimated_cost_usd", 0)),
                    dry_run=bool(arguments.get("dry_run", True)),
                    requested_by=str(arguments.get("requested_by", "mcp-client")),
                ),
            )
            data = ExecutionRead.model_validate(execution).model_dump(mode="json")
        elif name == "flowguard.execution_trace":
            trace = trace_for_execution(db, str(arguments.get("execution_id", "")))
            data = TraceRead.model_validate(trace).model_dump(mode="json")
        else:
            return mcp_error(payload.id, -32602, f"Unknown tool: {name}")
    except (HTTPException, ValueError) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return mcp_error(payload.id, -32000, str(message))

    return mcp_result(
        payload.id,
        {
            "content": [{"type": "text", "text": json.dumps(data)}],
            "structuredContent": data,
            "isError": False,
        },
    )
