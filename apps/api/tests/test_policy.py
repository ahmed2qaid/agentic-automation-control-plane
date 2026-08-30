from dataclasses import dataclass

from app.policy_engine import PolicyContext, evaluate


@dataclass
class FakePolicy:
    id: str
    name: str
    action: str
    risk_levels: list[str]
    workflow_id: str | None = None
    min_cost_usd: float | None = None
    priority: int = 0
    enabled: bool = True


def ctx(risk: str = "low", cost: float = 0, dry_run: bool = False) -> PolicyContext:
    return PolicyContext("wf-1", risk, cost, dry_run)


def test_dry_run_never_executes():
    decision = evaluate(ctx(dry_run=True), [], 0.5)
    assert decision.action == "dry_run"


def test_high_risk_requires_approval_by_default():
    decision = evaluate(ctx(risk="high"), [], 0.5)
    assert decision.action == "require_approval"


def test_critical_is_denied_by_default():
    decision = evaluate(ctx(risk="critical"), [], 0.5)
    assert decision.action == "deny"


def test_policy_priority_wins():
    policies = [
        FakePolicy("allow", "allow", "allow", ["high"], priority=10),
        FakePolicy("deny", "deny", "deny", ["high"], priority=100),
    ]
    decision = evaluate(ctx(risk="high"), policies, 0.5)
    assert decision.action == "deny"
    assert decision.policy_id == "deny"


def test_cost_guard_requires_approval():
    decision = evaluate(ctx(risk="low", cost=2.0), [], 0.5)
    assert decision.action == "require_approval"
