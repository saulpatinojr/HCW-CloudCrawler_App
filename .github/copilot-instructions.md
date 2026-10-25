# Repository instructions for GitHub Copilot

These apply to Copilot code review, Copilot coding agent and Copilot Chat in
this repository. `CONTRIBUTING.md` is the contract; this file points at it.

## When reviewing a pull request

- Put correctness, security and data handling first. Skip style that a
  formatter or linter already enforces.
- Name the input or state that triggers a defect, the wrong result, and the
  fix. A finding without a failure path is a suggestion, not a blocker.
- Check the description against the pull request template in `.github/`: every
  section present, verification stated as commands and results, checks not
  run named.
- Flag any credential, token, connection string, personal data or private
  endpoint in code, tests, fixtures, examples, workflow files or comments.
- Flag a GitHub Action referenced by tag or branch instead of a commit SHA,
  and a workflow whose `permissions` are wider than its steps need.
- A change to `infrastructure/docker/` or the workflows should say what it does to the image (base image, user,
  ports, writable paths) and how it was checked (`bash scripts/scan-image.sh`, the `image` job). A base image moves
  by digest, in `versions.env` and both `FROM` lines together.
- Check the rules of `CLAUDE.md` that must not weaken: Azure MCP Server stays at 3.0.0, the startup refusal under
  Azure client secrets, content-free logs, payload redaction, `callsAzure: false` on tools that do not call Azure.
- `CHANGELOG.md` is updated in the same pull request, and a change that reaches the AddOn (engine surface, tool
  schemas, detector ids, release workflows) names its `docs/whats-new-upstream.md` entry or says why none is needed.

## When writing code

- Follow the existing structure, naming and tooling of the directory you
  are in; do not introduce a second formatter, test runner or lint config.
- Do not add a dependency, base image or Action without stating why and
  pinning it.
- Keep secrets out of source; read them from the environment or the
  platform's secret store.
- Add or update tests with the change, including the failure path.
- Do not merge, approve, publish, deploy or rewrite history.
