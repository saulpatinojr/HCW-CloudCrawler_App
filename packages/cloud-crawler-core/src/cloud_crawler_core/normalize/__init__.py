"""One normaliser per evidence kind. Each returns the common resource shape every detector reads."""

from cloud_crawler_core.normalize.resource_graph import IngestionError, parse_resource_graph_json

__all__ = ["IngestionError", "parse_resource_graph_json"]
