"""One normaliser per evidence kind. Resource Graph exports and Terraform state and plan documents become the common
resource shape every resource detector reads; Azure MCP results become typed observation rows per tool."""

from cloud_crawler_core.normalize.azure_mcp import PARSERS, ROOT_KEYS, parse_azure_mcp_result
from cloud_crawler_core.normalize.resource_graph import IngestionError, parse_resource_graph_json
from cloud_crawler_core.normalize.terraform import (
    TerraformEvidence,
    check_json_bounds,
    parse_terraform_plan,
    parse_terraform_state,
)

__all__ = [
    "PARSERS",
    "ROOT_KEYS",
    "IngestionError",
    "TerraformEvidence",
    "check_json_bounds",
    "parse_azure_mcp_result",
    "parse_resource_graph_json",
    "parse_terraform_plan",
    "parse_terraform_state",
]
