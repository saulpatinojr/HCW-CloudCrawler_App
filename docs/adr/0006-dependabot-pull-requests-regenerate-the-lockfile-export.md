# 0006. Dependabot edits uv.lock only, and a workflow regenerates the lockfile export on its pull requests

- **Status:** Accepted (merged in #68); amended 2026-11-04 to reuse the HCW Main Admin GitHub App (issue #70)
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
   installation token of the **HCW Main Admin GitHub App** (`actions/create-github-app-token`,
   `permission-contents: write`, no `owner` or `repositories` input, so the token covers this repository only). The
   job's own `GITHUB_TOKEN` stays read-only. Amended 2026-11-04 (issue #70): this said a new dedicated "lockfile App".
   The owner asked to reuse an existing App instead. HCW Main Admin already does exactly this job for the four add-on
   repositories (their `core-update.yml` and `base-update.yml` open pull requests with it so that the required checks
   run), and each token it mints here is narrowed to contents on this one repository.
4. The push has to be made by the App, not by `GITHUB_TOKEN`. A push made with `GITHUB_TOKEN` starts no workflow
   ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)), and the one exception it has,
   `workflow_dispatch`, does not help: checks from a `workflow_dispatch` run never satisfy a pull request's required
   checks ([Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated)).
   CodeRabbit pointed this out on the first version of this change, which dispatched `ci` and `security`. A push
   made with an App token is an ordinary `synchronize` of the pull request, so the required checks run as usual.
5. The App's client id and private key are **Dependabot secrets** (`HCW_MAIN_ADMIN_CLIENT_ID`,
   `HCW_MAIN_ADMIN_PRIVATE_KEY`, the names the add-ons use for the same App): a workflow that Dependabot starts can
   read Dependabot secrets and no others
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
| A new dedicated App with Contents write only (this record's first version) | The smallest possible key | One more App to create, install and rotate | The owner chose to reuse HCW Main Admin (issue #70); the token is narrowed to the same scope either way, and only the key's own reach differs |
| Reuse the website repository's manifest App | Already exists | Its key could then write to the public website repository, whose pull requests merge on their own | The wrong blast radius for a lockfile push |
| A personal access token as a Dependabot secret | No App | Acts as the owner, is long-lived and is not limited to one file's worth of permission | A dedicated App's token is short-lived and contents-only |
| `pull_request_target` | Actions secrets available | Runs with write access in the base context; banned by `tests/unit/test_workflows.py` | Not needed: Dependabot secrets reach a `pull_request` run |

## Consequences

- Once the App is set up, Dependabot Python pull requests get a matching export and the required checks run on that
  commit without a person. A real problem (a stale `uv.lock`, a failing test, a known vulnerability) still fails CI and
  needs a person.
- The owner installs HCW Main Admin on this repository and on CloudAssessor App and adds two Dependabot secrets to
  each (steps below). Its key can do whatever the App's permissions allow in every repository it is installed on, now
  the four add-ons and these two App repositories. Inside these workflows the key is read only by this job, which runs
  no dependency code: a Dependabot secret reaches only a workflow that names it, and `ci.yml`, which does run the new
  dependency's code, names none. Use a separate private key for the App repositories, so it can be revoked without
  touching the add-ons.
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
- Owner setup, once, for this repository and CloudAssessor App together (the steps and values are in issue #70):
  1. Open HCW Main Admin from <https://github.com/settings/apps>, then **Permissions & events**. Check that
     **Repository permissions** include **Contents: Read and write** (the add-ons' pushes already need it).
  2. On the App's **General** page, copy the **Client ID** (the same value as the add-ons' `HCW_MAIN_ADMIN_CLIENT_ID`
     variable), then **Generate a private key** (a `.pem` file downloads): a new key used only by these two
     repositories.
  3. **Install App** → the gear next to your account → **Repository access** → add `HCW-CloudCrawler_App` and
     `HCW-CloudAssessor_App` → **Save**.
  4. In each of the two repositories, **Settings → Secrets and variables → Dependabot → New repository secret**:
     `HCW_MAIN_ADMIN_CLIENT_ID` = the Client ID; `HCW_MAIN_ADMIN_PRIVATE_KEY` = the whole `.pem` file. Then delete the
     downloaded `.pem`.
- Not yet seen on GitHub: the first run is on Dependabot's next weekly `uv` pull request after the setup. It worked
  when that pull request shows a commit "Regenerate requirements.lock.txt from uv.lock (make lock)" and the `lint`,
  `test`, `contract`, `image`, `pip-audit` and `secret-scan` checks run and pass on it by themselves.

## Rollback or revisit trigger

Delete the workflow and the `exclude-paths` entry, remove these two repositories from HCW Main Admin's installation,
delete the two Dependabot secrets and the App key made for them to return to running `make lock` by hand. Revisit if
the export moves into the image build (then nothing needs pushing).
