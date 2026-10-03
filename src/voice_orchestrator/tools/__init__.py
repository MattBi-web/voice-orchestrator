from .account_tool import CheckAccountStatusTool
from .base import Tool, ToolResult
from .knowledge_tool import KnowledgeLookupTool
from .transfer_tool import TransferToHumanTool

REGISTRY: dict[str, Tool] = {
    tool.id: tool
    for tool in (CheckAccountStatusTool(), TransferToHumanTool(), KnowledgeLookupTool())
}


def get_tool(tool_id: str) -> Tool:
    try:
        return REGISTRY[tool_id]
    except KeyError:
        raise ValueError(f"Unknown tool id={tool_id!r}. Known tools: {sorted(REGISTRY)}") from None


__all__ = ["Tool", "ToolResult", "REGISTRY", "get_tool"]
