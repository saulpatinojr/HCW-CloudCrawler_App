# Cloud Crawler App edition. Every target is a plain uv invocation. Nothing here reaches Azure in this slice.
.PHONY: setup lock lint test test-contract run run-recorded run-stdio image clean

setup:
	uv python pin 3.14.6
	uv sync --all-packages

lock:
	uv lock
	uv export --format requirements-txt --no-dev --no-emit-project --no-emit-workspace --no-header -o requirements.lock.txt

lint:
	uv run ruff check .
	uv run ruff format --check .
	bash scripts/check-lockfiles.sh
	uv run python scripts/check-release-version.py

test:
	uv run pytest -q --cov=packages --cov=src --cov-report=term-missing

# Starts the real Azure MCP Server 3.0.0 through npx (Node.js 22 and network needed; no Azure sign-in).
test-contract:
	uv run pytest tests/contract -q -m azmcp

run:
	PORT=8080 uv run python -m cloud_crawler_appliance

# The appliance with the recorded Azure MCP host: collection_run_azure replays samples/azure-mcp (no Azure access).
run-recorded:
	PORT=8080 CC_AZMCP_MODE=recorded uv run python -m cloud_crawler_appliance

# The development model: Azure MCP Server 3.0.0 as a child process over stdio with your own credential chain
# (for example AZURE_TOKEN_CREDENTIALS=AzureCliCredential after az login). Every call is read-only.
run-stdio:
	PORT=8080 CC_AZMCP_MODE=stdio uv run python -m cloud_crawler_appliance

image:
	docker build -f infrastructure/docker/Dockerfile -t hcw-cloud-crawler-appliance:dev .

clean:
	rm -rf .venv .pytest_cache .ruff_cache .coverage coverage.xml htmlcov dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
