from app.main import MCP_TOOLS
from app.n8n import normalize_n8n_workflows


def test_normalize_n8n_workflows_discovers_webhooks():
    payload = {
        "data": [
            {
                "id": "42",
                "name": "Send customer update",
                "active": True,
                "nodes": [
                    {
                        "type": "n8n-nodes-base.webhook",
                        "parameters": {"path": "customer-update"},
                    }
                ],
            },
            {
                "id": "43",
                "name": "No webhook workflow",
                "active": True,
                "nodes": [{"type": "n8n-nodes-base.manualTrigger", "parameters": {}}],
            },
        ]
    }

    result = normalize_n8n_workflows(payload, "http://n8n:5678")

    assert len(result) == 1
    assert result[0]["slug"] == "n8n-42"
    assert result[0]["webhook_url"] == "http://n8n:5678/webhook/customer-update"
    assert result[0]["enabled"] is True


def test_mcp_gateway_exposes_guarded_tools():
    names = {tool["name"] for tool in MCP_TOOLS}

    assert "flowguard.list_workflows" in names
    assert "flowguard.request_execution" in names
    assert "flowguard.execution_trace" in names
