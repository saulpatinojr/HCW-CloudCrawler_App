"""The MCP host: the appliance as a client of Azure MCP Server 3.0.0 (website proposal, sections 10 and 13).

`contract` pins the server and the tool allow-list; `host` is the client over stdio (the development model) and a
recorded host that replays fictional results from `samples/azure-mcp`; `collect` runs the standard collection
sequence and turns every result into observed evidence. Nothing here holds a credential: over stdio the server
authenticates with the developer's own credential chain, and the appliance never sees a token.
"""

from cloud_crawler_appliance.mcp_host.collect import collect
from cloud_crawler_appliance.mcp_host.contract import ALLOWED_TOOLS, NAMESPACES, PIN, server_params
from cloud_crawler_appliance.mcp_host.host import (
    AzureMcpHost,
    HostError,
    RecordedAzureMcpHost,
    StdioAzureMcpHost,
    ToolResult,
    evidence_from_result,
)

__all__ = [
    "ALLOWED_TOOLS",
    "NAMESPACES",
    "PIN",
    "AzureMcpHost",
    "HostError",
    "RecordedAzureMcpHost",
    "StdioAzureMcpHost",
    "ToolResult",
    "collect",
    "evidence_from_result",
    "server_params",
]
