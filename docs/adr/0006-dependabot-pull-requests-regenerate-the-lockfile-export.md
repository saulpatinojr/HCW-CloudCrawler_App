# 0006. Dependabot edits uv.lock only, and a workflow regenerates the lockfile export on its pull requests

- **Status:** Proposed (becomes Accepted when the pull request that adds it is merged)
- **Date:** 2026-11-04
- **Owners:** Workload owner
- **Issue:** none; it closes the failure every Dependabot Python pull request had (#62 and #65 were the latest)

## Context

The image installs `requirements.lock.txt`, a hash-pinned export of `uv.lock`, and `scripts/check-lockfiles.sh` fails
`lint` when the two differ. Dependabot's `uv` support edits `pyproject.toml` and `uv.lock` but cannot run the export, so
every Dependabot Python pull request failed `lint` until a person ran `make lock` on it, and each one that merged forced
the next to be rebased and fixed again. Worse, Dependabot also read `requirements.lock.txt` as a hand-written
requirements file: on #65 it moved `sse-starlette` in the export alone and left `uv.lock` behind, the wrong way round.

## Decision

1. `.github/dependabot.yml` excludes `requirements.lock.txt` from the `uv` entry (`exclude-paths`, documented in the
   [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#exclude-paths-)),
   so Dependabot changes `pyproject.toml` and `uv.lock` only.
2. `scripts/export-lockfiles.sh` is the one place the export flags live. `make lock`, `scripts/check-lockfiles.sh` and
   the new workflow call it. It runs `uv export --frozen`, which reads `uv.lock` and resolves, downloads and builds
   nothing.
3. `.github/workflows/dependabot-lockfiles.yml` runs on `pull_request` (never `pull_request_target`) when Dependabot
   opened the pull request on a `dependabot/uv/` branch of this repository and the newest commit is Dependabot's. It
   regenerates the export, commits only `requirements.lock.txt` if it changed, pushes with the job's `GITHUB_TOKEN`
   (`contents: write`, which GitHub allows a Dependabot-triggered `pull_request` workflow to request, as in
   [Automating Dependabot with GitHub Actions](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions)),
   and starts `ci.yml` and `security.yml` on the new commit with `workflow_dispatch` (`actions: write`), because a push
   made with `GITHUB_TOKEN` starts no workflow by itself and `workflow_dispatch` is the
   [documented exception](https://docs.github.com/en/actions/concepts/security/github_token). `security.yml` gains a
   `workflow_dispatch` trigger with no inputs for this.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Keep running `make lock` by hand on each Dependabot pull request | No new automation | Every pull request fails first; open ones need a fix and a rebase each time another merges | The failure is certain and recurring |
| Stop committing the export; build it inside the Dockerfile from `uv.lock` | One file, nothing to drift | Changes the image build, `pip-audit`'s input and the documented release contract | A larger change than the problem; can still be chosen later |
| Push with the repository-admin GitHub App so the push starts CI itself | No `workflow_dispatch` | That App sits behind the `admin-ops` environment, which needs the owner's approval on every run | Would bring back a manual step |
| `pull_request_target` with the App token | Secrets available | Runs with write access in the base context; banned by `tests/unit/test_workflows.py` | Not needed: the built-in token is enough |

## Consequences

- Dependabot Python pull requests arrive with a matching export and run the required checks on that commit without a
  person. A real problem (a stale `uv.lock`, a failing test, a known vulnerability) still fails CI and needs a person.
- Because a commit that is not Dependabot's sits on the branch, Dependabot no longer rebases that pull request by
  itself. After another pull request merges, comment `@dependabot recreate` on it; the workflow runs again on the new
  commit.
- The job holds a write token for one branch for a few seconds and runs no dependency code: the export reads `uv.lock`
  only, and `tests/unit/test_workflows.py` fails if the workflow ever runs `uv lock`, `uv sync`, `uv run`, `make` or
  `pytest`, adds anything but `requirements.lock.txt`, or gates on the spoofable `github.actor`.

## Validation

- `tests/unit/test_workflows.py` pins the gates, the permissions, the export script and the `workflow_dispatch`
  triggers; `zizmor` reports no finding on the workflow; actionlint and shellcheck are clean.
- Not yet seen on GitHub: the first run is on Dependabot's next weekly `uv` pull request. It worked when that pull
  request shows a commit by `github-actions[bot]` named "Regenerate requirements.lock.txt from uv.lock (make lock)"
  and the `lint`, `test`, `contract`, `image`, `pip-audit` and `secret-scan` checks on it.

## Rollback or revisit trigger

Delete the workflow and the `exclude-paths` entry to return to running `make lock` by hand. Revisit if the dispatched
checks do not satisfy the `main` ruleset's required checks, or if the export moves into the image build.
