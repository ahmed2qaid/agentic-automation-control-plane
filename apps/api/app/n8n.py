import httpx

from .config import get_settings


class N8nInvocationError(RuntimeError):
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
