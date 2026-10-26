# Testing

Run the same checks on your computer that the project runs on every pull request, and learn what each one proves.

## Before you start

- Do the [Quick start](quick-start.md) steps 1 to 3, so the code and packages are on your computer.
- Stay in the `HCW-CloudCrawler_App` folder.
- For step 7 only, install [Node.js](https://nodejs.org/en/download) 22 and be online. For step 9 only, run Docker Desktop
  ([install](https://docs.docker.com/desktop/setup/install/windows-install/)).

The commands are the same in PowerShell 7 and Git Bash. Steps 5 and 9 start `bash`, so on Windows Git for Windows must be
installed.

## Steps

1. **Check the code style rules** with [Ruff](https://docs.astral.sh/ruff/).

    ```text
    uv run --frozen ruff check .
    ```

    You should see `All checks passed!`.

2. **Check the code layout.**

    ```text
    uv run --frozen ruff format --check .
    ```

    You should see a line ending `files already formatted`.

3. **Run the tests, and require that 96 percent of the code is exercised** (see [pytest](https://docs.pytest.org/en/stable/)).

    ```text
    uv run --frozen pytest -q --cov=packages --cov=src --cov-fail-under=96
    ```

    You should see a last line with the `passed` and `skipped` counts and, above it, `Required test coverage of 96% reached`.
    Tests that need `bash` and `jq` are skipped on a computer without them; that is normal.

4. **Check that every file that names the version agrees.**

    ```text
    uv run --frozen python scripts/check-release-version.py
    ```

    You should see `release version consistent: 0.1.0`.

5. **Check the lock files match.** After you change `pyproject.toml`, `make lock` fixes a mismatch.

    ```text
    bash scripts/check-lockfiles.sh
    ```

    You should see `lockfile export matches uv.lock`.

6. **Check the packages for known vulnerabilities** with [pip-audit](https://pypi.org/project/pip-audit/).

    ```text
    uv run --frozen pip-audit -r requirements.lock.txt --strict
    ```

    You should see `No known vulnerabilities found`.

7. **Check the Azure MCP contract.** This starts the real Azure MCP Server 3.0.0 through `npx` and compares its tool list
   with the saved list. It makes no Azure call and needs no sign-in.

    ```text
    uv run --frozen pytest tests/contract -q -m azmcp
    ```

    You should see `1 passed`. A failure means the server's tools changed; do not update the saved list without review.

8. **Build the documentation site and check its links.**

    ```text
    uv run --locked --only-group docs python scripts/build-pages.py
    ```

    You should see `built` and a page count, then `every internal link and fragment resolves`. The site is in `_site/`.

9. **Scan the container image** (build it first: [Installation](installation.md), Route 2, step 3).

    ```text
    bash scripts/scan-image.sh hcw-cloud-crawler-appliance:dev
    ```

    You should see `gate (fixable HIGH,CRITICAL, unaccepted): PASS.` Read about the scanner at
    [Trivy](https://trivy.dev/docs/latest/guide/).

`make lint`, `make test` and `make test-contract` run some of these where `make` is installed.

## What the tests do not prove

- **Real Azure behaviour.** The recorded results are hand-written with made-up values.
- **A real Entra directory.** Every test token is made on the spot and the signing key is served locally.
- **How GitHub runs the workflows.** The tests read the workflow files as text; only running them shows how they behave.

[Known limitations](known-limitations.md) and the repository's [validation record](../VALIDATION.md) list every check that was
run and every one that was not.
