from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PolicyContext:
    workflow_id: str
    risk_level: str
    estimated_cost_usd: float
    dry_run: bool


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    policy_id: str | None = None


def evaluate(context: PolicyContext, policies: Iterable[object], max_auto_cost_usd: float) -> Decision:
    if context.dry_run:
        return Decision("dry_run", "Dry-run requested; no external side effect will execute.")

    for policy in sorted(policies, key=lambda item: item.priority, reverse=True):
        if not policy.enabled:
            continue
        if policy.workflow_id and policy.workflow_id != context.workflow_id:
            continue
        if policy.risk_levels and context.risk_level not in policy.risk_levels:
            continue
        if policy.min_cost_usd is not None and context.estimated_cost_usd < policy.min_cost_usd:
            continue
        return Decision(policy.action, f"Matched policy: {policy.name}", policy.id)

    if context.risk_level == "critical":
        return Decision("deny", "Critical-risk workflows are denied by default.")
    if context.risk_level == "high":
        return Decision("require_approval", "High-risk workflows require human approval.")
    if context.estimated_cost_usd > max_auto_cost_usd:
        return Decision("require_approval", "Estimated cost exceeds the automatic execution budget.")
    return Decision("allow", "Risk and cost are within automatic execution limits.")
