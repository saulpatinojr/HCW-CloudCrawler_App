# CLAUDE.md — working agreement for Claude Code in this repository

This is `saulpatinojr/HCW-CloudCrawler_App`, the **App edition** of Cloud Crawler: Hybrid Cloud Works' Azure
architecture appliance (evidence ledger, decision records, deterministic drift, review proposals) built around
**Azure MCP Server 3.0.0** as the source of truth for Azure observations. The engine (`packages/cloud-crawler-core`)
is seeded and versioned here and **moves downstream unchanged** to `saulpatinojr/HCW-CloudCrawler_AddOn` (ADR 0002).
The website integrates only with the AddOn; this repository is the reference implementation, the enterprise
deployment and the proving ground. The design is the website proposal
`docs/architecture/azure-architecture-mcp-appliance.md` in `HCW-HybridCloudWorks`.

- Run `uv sync --all-packages`, then `uv run ruff check . && uv run ruff format --check .`,
  `bash scripts/check-lockfiles.sh` and `uv run pytest -q --cov=packages --cov=src` before claiming anything works;
  `make test-contract` for anything touching the Azure MCP contract (it starts the real 3.0.0 server through npx,
  no Azure sign-in). Never claim a check passed that you did not run.
- **Azure MCP Server stays at 3.0.0** (ADR 0001): npm `@azure/mcp@3.0.0`, container
  `mcr.microsoft.com/azure-sdk/azure-mcp:3.0.0` by digest. `tests/contract/snapshots/azmcp-3.0.0-tools.json` is the
  contract; regenerate it only with `CC_UPDATE_SNAPSHOT=1`, locally, in a reviewed change that says why. Never
  substitute a 4.x beta.
- Never weaken: the startup refusal under `AZURE_CLIENT_SECRET`, `AZURE_CLIENT_CERTIFICATE_PATH`,
  `AZURE_CLIENT_CERTIFICATE_PASSWORD`, `AZURE_USERNAME`, `AZURE_PASSWORD` (`edition.py`); the content-free log writer
  (`security/logging.py`, every event through `assert_no_visitor_data`); payload redaction at ingest; the raw payload
  hash taken before redaction; the "not an audit" bundle text; the `callsAzure: false` metadata on every tool that
  does not call Azure (the AddOn's security suite reads it).
- Identity: a managed identity or a delegated token forwarded per request through Azure MCP's on-behalf-of flow,
  never a secret, never a stored user token. No client-secret credential class anywhere in `src` or `packages`
  (CI greps for it).
- Engine rules: pydantic only (no HTTP client, no cloud SDK, no I/O); verdicts come from detectors, never from a
  model; **unknown lowers coverage, never score**; severity weights critical 4 / high 3 / medium 2 / low 1; detector
  ids and evidence kinds are only added, never renamed; every model forbids unknown fields; ids are
  `<prefix>_<uuid7>`.
- MCP tools use `namespace_action` names, return `structuredContent` plus concise text, and declare annotations and
  `meta.callsAzure`. The HTTP transport is streamable HTTP, stateless, mounted at `/mcp`; `/api/health` is flat
  (`id`, `version`, `edition` at the top level).
- No secrets, tokens, customer inventories or real tenant/subscription ids anywhere, fixtures and tests included.
  Samples use subscription `00000000-0000-0000-0000-000000000001` and `hcw-sample-*` names only, with one
  Azure-imposed exception: storage account names take no hyphen, so the sample accounts are `hcwsamplest*`
  (`tests/security/test_no_secrets.py` enforces the identifiers).
- Owner-pasteable commands: no placeholders; bash and PowerShell both acceptable; say which shell.
- ADRs in `docs/adr/` follow the template there (next number: 0004). Record limitations in `VALIDATION.md`. Keep
  `CHANGELOG.md` current in the same pull request. Pull requests open ready for review and follow
  `.github/PULL_REQUEST_TEMPLATE.md`.

## How to communicate with the owner

The owner is not a specialist in every tool used here. Write for a junior administrator with limited experience and no
memory of earlier sessions.

- **Be conversational and human.** Plain, friendly sentences. Say what happened and why it matters before the detail.
- **Assume little context.** Do not rely on repository history, ticket numbers or earlier chat. Restate what a thing is
  the first time it appears.
- **Avoid jargon.** When a technical term is unavoidable, explain it in a few words the first time, for example
  "a lockfile (the file that records the exact versions installed)".
- **When the owner must act, give numbered steps.** One action per step, short, saying where to click or what to run and
  which shell (bash or PowerShell). Say what they should see when it worked.
- **When you ask the owner a question, make it answerable.** Say what is being decided and why it matters, list the
  options in plain words with what each one means, give a recommendation, and say exactly how to answer (a word to reply
  with, or the steps and the link for where to click). Never ask a bare "A, B or C?" or "OK to proceed?".
- **Include links.** Point to the exact settings page, the issue or pull request, and the official documentation
  (Microsoft Learn, GitHub Docs and similar) whenever one exists.
- **Be honest about status.** Separate what was checked, what is assumed, and what is blocked. Never present a guess as a result.

This applies to chat replies, pull request and issue text, and documentation. It does not apply to code comments or
machine-readable files, which keep following the surrounding style.
