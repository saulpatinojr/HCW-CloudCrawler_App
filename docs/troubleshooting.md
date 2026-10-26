# Troubleshooting

Find what you see, then follow the numbered steps. If your problem is not here, open an issue on the repository and leave
out secrets, tokens and tenant or subscription ids.

The commands work in PowerShell 7 and Git Bash except where two are shown.

## The program stops at once, with `startup_refused`

The program checks its settings before it starts and prints the reason on one line. Exit code `3` means it refused.

1. **Read the reason after `"reason":`.** You should see either a variable name starting `AZURE_` or a name starting `CC_`.

2. **If it names an `AZURE_` variable,** remove it. This is a safety check: the program never runs with a stored Azure
   secret. Use `az login` or a managed identity instead.

    PowerShell:

    ```powershell
    Remove-Item Env:AZURE_CLIENT_SECRET
    ```

    Git Bash:

    ```bash
    unset AZURE_CLIENT_SECRET
    ```

    Replace the name if the reason names another variable. You should see nothing; start the program again.

3. **If it names a `CC_` setting,** correct that value using the table in [Configuration](configuration.md). The usual
   causes are `CC_AUTH_MODE=entra` without `CC_ENTRA_TENANT_ID` or `CC_ENTRA_AUDIENCE`, and a `CC_ENTRA_*` setting left in the
   window while sign-in is `off`. You should see the `startup` line on the next start.

## The program says `error while attempting to bind on address`

Another program is already using the port (8080 unless you changed it).

1. **See who is using it.**

    PowerShell:

    ```powershell
    Get-NetTCPConnection -LocalPort 8080 -State Listen
    ```

    Git Bash:

    ```bash
    netstat -ano | grep ":8080"
    ```

    You should see one line whose last column is the id of the program using the port.

2. **Use another port,** unless that program is a copy of Cloud Crawler you meant to stop. Follow
   [Configuration](configuration.md), "Set a setting", with the number `8090`, then use `8090` in the health command.
   You should see the `startup` line on the next start.

## The health command cannot connect

1. **Check that the program is running.** From source, the first window must still be busy. For the container, run the
   command below. You should see one line for `hcw-cloud-crawler` with a status starting `Up`.

    ```text
    docker ps --filter name=hcw-cloud-crawler
    ```

2. **If the line is missing, read why it stopped.** A container started with `--rm` is removed when it stops, so start it
   again ([Deployment](deployment.md) step 4) and run `docker logs hcw-cloud-crawler`. You should see a `startup` line or a
   `startup_refused` line (see above).

3. **Check the address and port.** The health command uses `127.0.0.1:8080`; if you changed `PORT`, use that number.

## Docker commands cannot reach Docker

1. **Start Docker Desktop** ([install](https://docs.docker.com/desktop/setup/install/windows-install/)) and wait until it
   says it is running.

2. **Check it answers.**

    ```text
    docker version
    ```

    You should see a `Server` block as well as a `Client` block.

## A request is refused

| You see | Why | What to do |
| --- | --- | --- |
| `400` from `/mcp` | The request is not a valid MCP request. | Send a proper MCP request from an MCP client. |
| `421` `Invalid Host header` | The host name in the request is not in `CC_ALLOWED_HOSTS` (only loopback names are accepted by default). | Set `CC_ALLOWED_HOSTS` to the name callers use and restart ([Configuration](configuration.md)). |
| `403` `Invalid Origin header` | A web page on another site called `/mcp`. | Call it from a program or a server, not from a browser page. |
| `401` | Sign-in is on and the token is missing, expired, for another audience or directory, or not signed by your directory. | Get a new token for `api://<client id>/access_as_user`. The log line gives one reason word, never the token. |
| `503` | Sign-in is on and the directory's signing keys could not be fetched. | Check the server can reach the internet; retry. Requests are never let through meanwhile. |
| `forbidden: this tool needs a signed-in person` | The token belongs to a service, not a person. | Use a token a person signed in to get. |
| `forbidden: actorId does not match` | The `actorId` you sent differs from the token's. | Leave `actorId` out. |
| `invalid_request: actorId is required` | Sign-in is off and a human-only tool needs `actorId`. | Send `actorId`, or turn sign-in on. |
| `404 not_found` from `/api/...` | Only `GET /api/health` exists under `/api`. | Use the health address. |

## The answers look wrong

| You see | Why | What to do |
| --- | --- | --- |
| An empty ledger after a restart | Nothing is saved to disk. | Expected; hand the evidence in again. |
| Many `unknown` verdicts | The evidence is missing, older than `CC_EVIDENCE_TTL_HOURS`, or lacks the property the check reads. A single virtual machine always gives `unknown` for zone redundancy. | Hand in fresh evidence; the verdict names the missing property. |
| No `collection_run_azure` tool | No Azure source is set. | Set `CC_AZMCP_MODE` to `recorded` or `stdio`. |
| `stdio` mode fails to start | Node.js 22 is missing, you are offline, or you are not signed in. | Install Node.js 22, run `az login`, and follow [Configuration](configuration.md), "Use real Azure data". |
| `"production": false` | It always says this. | Nothing to fix. |

## A check fails

| You see | Why | What to do |
| --- | --- | --- |
| `check-lockfiles.sh` says the export drifted | `pyproject.toml` changed without new lock files. | Run `make lock`, or `uv lock` then the `uv export` line in the `Makefile`, and commit both files. |
| `build-pages.py` exits 1 | A link points at nothing, or a page in `docs/` is not listed in `DOC_PAGES` in the script. | Read the first `error:` line; it names the file and the link. |
| A test about `.trivyignore.yaml` fails | An accepted-risk entry is past its expiry date. | Renew or remove it (README, "Image scan and accepted risk"). |
