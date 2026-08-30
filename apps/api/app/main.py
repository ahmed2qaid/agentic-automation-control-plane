from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine, get_db
from .models import Approval, AuditEvent, Execution, Policy, Workflow
from .n8n import N8nInvocationError, invoke_n8n
from .policy_engine import PolicyContext, evaluate
from .schemas import (
    ApprovalDecision,
    ApprovalRead,
    AuditRead,
    ExecutionCreate,
    ExecutionRead,
    N8nEvent,
    PolicyCreate,
    PolicyRead,
    WorkflowCreate,
    WorkflowRead,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def record_audit(db: Session, event_type: str, entity_type: str, entity_id: str, actor: str, data: dict) -> None:
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
    record_audit(db, "execution.started", "execution", execution.id, actor, {"workflow_id": workflow.id})
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
        record_audit(db, "execution.failed", "execution", execution.id, "system", {"error": str(exc)})
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
                Policy(name="Deny critical operations", action="deny", risk_levels=["critical"], priority=100),
                Policy(name="Approve high-risk operations", action="require_approval", risk_levels=["high"], priority=90),
                Policy(
                    name="Approve expensive operations",
                    action="require_approval",
                    risk_levels=[],
                    min_cost_usd=settings.max_auto_cost_usd,
                    priority=80,
                ),
                Policy(name="Allow routine operations", action="allow", risk_levels=["low", "medium"], priority=10),
            ]
        )
    db.commit()


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        seed_defaults(db)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "flowguard-api", "version": "0.1.0"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    workflows = db.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all()
    executions = db.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(12)).all()
    approvals = db.scalars(select(Approval).where(Approval.status == "pending").order_by(Approval.requested_at.desc())).all()
    policies = db.scalars(select(Policy).where(Policy.enabled.is_(True)).order_by(Policy.priority.desc())).all()
    return {
        "metrics": {
            "workflows": len(workflows),
            "enabled_workflows": sum(1 for item in workflows if item.enabled),
            "pending_approvals": len(approvals),
            "recent_failures": sum(1 for item in executions if item.status == "failed"),
            "active_policies": len(policies),
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
    record_audit(db, "workflow.registered", "workflow", workflow.id, "api", {"slug": workflow.slug})
    db.commit()
    return workflow


@app.get("/api/workflows", response_model=list[WorkflowRead])
def list_workflows(db: Session = Depends(get_db)) -> list[Workflow]:
    return list(db.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all())


@app.post("/api/policies", response_model=PolicyRead, status_code=201)
def create_policy(payload: PolicyCreate, db: Session = Depends(get_db)) -> Policy:
    if payload.workflow_id and not db.get(Workflow, payload.workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    policy = Policy(**payload.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    record_audit(db, "policy.created", "policy", policy.id, "api", {"action": policy.action, "priority": policy.priority})
    db.commit()
    return policy


@app.get("/api/policies", response_model=list[PolicyRead])
def list_policies(db: Session = Depends(get_db)) -> list[Policy]:
    return list(db.scalars(select(Policy).order_by(Policy.priority.desc(), Policy.created_at.desc())).all())


@app.post("/api/executions", response_model=ExecutionRead, status_code=201)
def create_execution(payload: ExecutionCreate, db: Session = Depends(get_db)) -> Execution:
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
    record_audit(
        db,
        "execution.requested",
        "execution",
        execution.id,
        payload.requested_by,
        {"decision": decision.action, "reason": decision.reason, "policy_id": decision.policy_id},
    )

    if decision.action == "require_approval":
        approval = Approval(execution_id=execution.id)
        db.add(approval)
        db.flush()
        record_audit(db, "approval.requested", "approval", approval.id, "system", {"execution_id": execution.id})

    db.commit()
    db.refresh(execution)

    if decision.action == "allow":
        run_execution(db, execution, workflow, payload.requested_by)
    return execution


@app.get("/api/executions", response_model=list[ExecutionRead])
def list_executions(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[Execution]:
    return list(db.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(limit)).all())


@app.get("/api/approvals", response_model=list[ApprovalRead])
def list_approvals(status: str = Query(default="pending"), db: Session = Depends(get_db)) -> list[Approval]:
    statement = select(Approval).order_by(Approval.requested_at.desc())
    if status != "all":
        statement = statement.where(Approval.status == status)
    return list(db.scalars(statement).all())


@app.post("/api/approvals/{approval_id}/decision", response_model=ExecutionRead)
def decide_approval(approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db)) -> Execution:
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
def list_audit(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all())


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
