"""One normaliser per evidence kind. Resource Graph exports become the common resource shape every resource detector
reads; Azure MCP results become typed observation rows per tool."""

from cloud_crawler_core.normalize.azure_mcp import PARSERS, ROOT_KEYS, parse_azure_mcp_result
from cloud_crawler_core.normalize.resource_graph import IngestionError, parse_resource_graph_json

__all__ = ["PARSERS", "ROOT_KEYS", "IngestionError", "parse_azure_mcp_result", "parse_resource_graph_json"]
