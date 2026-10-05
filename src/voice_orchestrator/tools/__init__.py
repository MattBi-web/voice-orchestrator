from .account_tool import CheckAccountStatusTool
from .base import Tool, ToolResult
from .end_call_tool import EndCallTool
from .knowledge_tool import KnowledgeLookupTool
from .mcp_tool import MCPServerConfig, MCPTool, load_mcp_tools
from .transfer_tool import TransferToHumanTool
from .webhook_tool import WebhookTool, WebhookToolConfig, load_webhook_tools

REGISTRY: dict[str, Tool] = {
    tool.id: tool
    for tool in (
        CheckAccountStatusTool(),
        TransferToHumanTool(),
        EndCallTool(),
        KnowledgeLookupTool(),
        *load_mcp_tools(),  # config/mcp_servers.yaml — [] if absent, never raises
        *load_webhook_tools(),  # config/webhook_tools.yaml — [] if absent, never raises
    )
}


def get_tool(tool_id: str) -> Tool:
    try:
        return REGISTRY[tool_id]
    except KeyError:
        raise ValueError(f"Unknown tool id={tool_id!r}. Known tools: {sorted(REGISTRY)}") from None


__all__ = [
    "Tool",
    "ToolResult",
    "REGISTRY",
    "get_tool",
    "MCPServerConfig",
    "MCPTool",
    "load_mcp_tools",
    "EndCallTool",
    "WebhookTool",
    "WebhookToolConfig",
    "load_webhook_tools",
]
