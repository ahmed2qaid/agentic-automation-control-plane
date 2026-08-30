import re
from typing import Any

import httpx

from .config import get_settings


class N8nInvocationError(RuntimeError):
    pass


class N8nSyncError(RuntimeError):
    pass


def invoke_n8n(webhook_url: str, execution_id: str, payload: dict) -> dict:
    settings = get_settings()
    headers = {
        "X-FlowGuard-Secret": settings.n8n_shared_secret,
        "X-FlowGuard-Execution": execution_id,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                webhook_url,
                json={"execution_id": execution_id, "input": payload},
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise N8nInvocationError(str(exc)) from exc

    try:
        data = response.json()
    except ValueError:
        data = {"text": response.text}
    return {"status_code": response.status_code, "response": data}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "n8n-workflow"


def _webhook_path(nodes: list[dict[str, Any]]) -> str | None:
    for node in nodes:
        node_type = str(node.get("type", ""))
        if node_type.endswith(".webhook") or node_type == "n8n-nodes-base.webhook":
            parameters = node.get("parameters") or {}
            path = parameters.get("path")
            if path:
                return str(path).lstrip("/")
    return None


def normalize_n8n_workflows(payload: dict[str, Any], public_base_url: str) -> list[dict[str, Any]]:
    raw_items = payload.get("data", payload.get("workflows", []))
    normalized: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        path = _webhook_path(item.get("nodes") or [])
        if not path:
            continue
        name = str(item.get("name") or f"n8n workflow {item.get('id', '')}").strip()
        external_id = str(item.get("id") or "")
        base_slug = f"n8n-{slugify(external_id)}" if external_id else slugify(name)
        slug = base_slug
        suffix = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        seen_slugs.add(slug)
        normalized.append(
            {
                "external_id": external_id,
                "slug": slug,
                "name": name,
                "description": f"Synced from n8n workflow {item.get('id', 'unknown')}.",
                "webhook_url": f"{public_base_url.rstrip('/')}/webhook/{path}",
                "enabled": bool(item.get("active", False)),
            }
        )
    return normalized


def fetch_n8n_workflows() -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.n8n_api_key:
        raise N8nSyncError("N8N_API_KEY is not configured")

    headers = {"X-N8N-API-KEY": settings.n8n_api_key}
    url = f"{settings.n8n_api_url.rstrip('/')}/api/v1/workflows"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise N8nSyncError(str(exc)) from exc

    data = response.json()
    return normalize_n8n_workflows(data, settings.n8n_public_url)
