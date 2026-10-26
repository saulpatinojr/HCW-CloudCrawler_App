# Quick start

Run Cloud Crawler on your own computer in about five minutes, with no Azure account, using made-up Azure data that ships
with the repository.

> **Not production.** The program reports `"production": false`. Run it on your own machine only.

## Before you start

- [Git](https://git-scm.com/install/windows) is installed. Check with `git --version`.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) is installed. It installs the right Python and the exact
  package versions for you. Check with `uv --version`.
- Nothing else is using port 8080 on your computer.

## Steps

The steps work in PowerShell 7 and in Git Bash. Where a command differs, both are shown.

1. **Download the code.**

    ```text
    git clone https://github.com/saulpatinojr/HCW-CloudCrawler_App.git
    ```

    You should see `Cloning into 'HCW-CloudCrawler_App'...` and then your prompt again.

2. **Go into the folder.**

    ```text
    cd HCW-CloudCrawler_App
    ```

    You should see nothing; the prompt now ends in `HCW-CloudCrawler_App`.

3. **Install the packages.** The first run can take a minute, because uv also downloads the Python version the project
   pins ([how uv chooses Python](https://docs.astral.sh/uv/concepts/python-versions/)).

    ```text
    uv sync --frozen --all-packages
    ```

    You should see a list of package names, each starting with `+`, and no error.

4. **Start the program with the recorded Azure data.** The window stays busy while it runs. Leave it open.

    PowerShell:

    ```powershell
    $env:CC_AZMCP_MODE = "recorded"; uv run python -m cloud_crawler_appliance
    ```

    Git Bash:

    ```bash
    CC_AZMCP_MODE=recorded uv run python -m cloud_crawler_appliance
    ```

    You should see one line that starts `{"ts":` and contains `"event":"startup"`, `"azmcp":"recorded"` and
    `"auth":false`. If the program ends at once with `startup_refused`, see [Troubleshooting](troubleshooting.md).

5. **Ask it how it is.** Open a second window and run the line for your shell.

    PowerShell:

    ```powershell
    Invoke-RestMethod http://127.0.0.1:8080/api/health | ConvertTo-Json -Depth 4
    ```

    Git Bash:

    ```bash
    curl -s http://127.0.0.1:8080/api/health
    ```

    You should see a document with `"ok": true`, `"id": "cloud-crawler"`, `"edition": "appliance"`,
    `"azureConnectivity": "recorded"`, `"auth": "off"` and `"production": false`. The last one is the program telling
    you it is not production software.

6. **Stop the program.** Click the first window and press Ctrl+C. You should get your prompt back. In PowerShell, also run
   `Remove-Item Env:CC_AZMCP_MODE`, because step 4 left that setting in the window.

## What next

- The tools other programs call are served at `http://127.0.0.1:8080/mcp`; [Product overview](product-overview.md) lists
  them.
- To use real Azure data or turn on sign-in, see [Configuration](configuration.md).
- To run the project's checks, see [Testing](testing.md).
- If a step failed, see [Troubleshooting](troubleshooting.md).
