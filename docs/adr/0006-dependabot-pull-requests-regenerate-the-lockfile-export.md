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
   regenerates the export and, if it changed, commits only `requirements.lock.txt` and pushes it with a short-lived
   installation token of a dedicated **lockfile GitHub App** that may write repository contents and nothing else
   (`actions/create-github-app-token`, `permission-contents: write`). The job's own `GITHUB_TOKEN` stays read-only.
4. The push has to be made by the App, not by `GITHUB_TOKEN`. A push made with `GITHUB_TOKEN` starts no workflow
   ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)), and the one exception it has,
   `workflow_dispatch`, does not help: checks from a `workflow_dispatch` run never satisfy a pull request's required
   checks ([Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated)).
   CodeRabbit pointed this out on the first version of this change, which dispatched `ci` and `security`. A push
   made with an App token is an ordinary `synchronize` of the pull request, so the required checks run as usual.
5. The App's client id and private key are **Dependabot secrets** (`LOCKFILES_APP_CLIENT_ID`,
   `LOCKFILES_APP_PRIVATE_KEY`): a workflow that Dependabot starts can read Dependabot secrets and no others
   ([Troubleshooting Dependabot on GitHub Actions](https://docs.github.com/en/code-security/reference/supply-chain-security/troubleshoot-dependabot/dependabot-on-actions)).
   Until they exist, the job stops with an error naming them, and the pull request needs a hand-run `make lock` as
   before.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Keep running `make lock` by hand on each Dependabot pull request | No new automation | Every pull request fails first; open ones need a fix and a rebase each time another merges | The failure is certain and recurring |
| Stop committing the export; build it inside the Dockerfile from `uv.lock` | One file, nothing to drift | Changes the image build, `pip-audit`'s input and the documented release contract | A larger change than the problem; can still be chosen later |
| Push with `GITHUB_TOKEN` and start `ci` and `security` with `workflow_dispatch` (the first version of this change) | No App to create | Checks from a `workflow_dispatch` run never count as the pull request's required checks, so every Dependabot pull request would stay blocked | Does not work, by GitHub's documented design |
| Reuse the repository-admin App (HCW Portfolio Admin) | Already exists | It can change rulesets; its key would have to become a Dependabot secret, and it sits behind the `admin-ops` environment, which needs the owner's approval on every run | Far more power than writing one file needs, and a manual step again |
| A personal access token as a Dependabot secret | No App | Acts as the owner, is long-lived and is not limited to one file's worth of permission | A dedicated App's token is short-lived and contents-only |
| `pull_request_target` | Actions secrets available | Runs with write access in the base context; banned by `tests/unit/test_workflows.py` | Not needed: Dependabot secrets reach a `pull_request` run |

## Consequences

- Once the App is set up, Dependabot Python pull requests get a matching export and the required checks run on that
  commit without a person. A real problem (a stale `uv.lock`, a failing test, a known vulnerability) still fails CI and
  needs a person.
- The owner creates and keeps one small GitHub App and two Dependabot secrets per repository (steps below). The App's
  key can write contents in the repositories it is installed on, so it is installed only on the repositories that use
  this workflow.
- Because a commit that is not Dependabot's sits on the branch, Dependabot no longer rebases that pull request by
  itself. After another pull request merges, comment `@dependabot recreate` on it; the workflow runs again on the new
  commit.
- The job's own token is read-only. The App's token is minted only after the export has been written, is limited to
  contents on this repository, and lives for at most an hour. No dependency code runs: the export reads `uv.lock` only,
  and `tests/unit/test_workflows.py` fails if the workflow ever runs `uv lock`, `uv sync`, `uv run`, `make` or `pytest`,
  asks for a write permission on `GITHUB_TOKEN`, pushes with anything but the App's token, adds anything but
  `requirements.lock.txt`, gates on the spoofable `github.actor`, or goes back to `workflow_dispatch`.

## Validation

- `tests/unit/test_workflows.py` pins the gates, the permissions, the App token and the export script; `zizmor`
  reports no finding on the workflow; actionlint and shellcheck are clean.
- Owner setup, once (the same App serves CloudAssessor; create it once and install it on both):
  1. Create the App at <https://github.com/settings/apps/new>: name `HCW Lockfile Sync`, description "Pushes the
     regenerated requirements lock export to Dependabot pull requests in the HCW App repositories.", homepage URL
     `https://github.com/saulpatinojr/HCW-CloudCrawler_App`; untick **Webhook → Active**; under **Repository
     permissions** set **Contents: Read and write** (Metadata becomes read-only by itself) and nothing else; **Only on
     this account**.
  2. On the App's page, note its **Client ID**, then **Generate a private key** (a `.pem` file downloads).
  3. **Install App** → **Only select repositories** → `HCW-CloudCrawler_App` and `HCW-CloudAssessor_App`.
  4. In each repository, **Settings → Secrets and variables → Dependabot → New repository secret**: name
     `LOCKFILES_APP_CLIENT_ID`, value the Client ID; then `LOCKFILES_APP_PRIVATE_KEY`, value the whole `.pem` file.
     Then delete the downloaded `.pem`.
- Not yet seen on GitHub: the first run is on Dependabot's next weekly `uv` pull request after the setup. It worked
  when that pull request shows a commit "Regenerate requirements.lock.txt from uv.lock (make lock)" and the `lint`,
  `test`, `contract`, `image`, `pip-audit` and `secret-scan` checks run and pass on it by themselves.

## Rollback or revisit trigger

Delete the workflow and the `exclude-paths` entry, uninstall the App and delete the two Dependabot secrets to return
to running `make lock` by hand. Revisit if the export moves into the image build (then nothing needs pushing).
