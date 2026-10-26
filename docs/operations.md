# Operations

The day-to-day tasks for whoever looks after a running Cloud Crawler container: check it, read its log, restart it, update
it and stop it.

> **Not for production.** The program reports `"production": false`. Read "What is not supported yet" at the end.

The commands assume the container from [Deployment](deployment.md), named `hcw-cloud-crawler`, and work the same in
PowerShell 7 and Git Bash. If you run from source, the program's window is the log and Ctrl+C stops it.

## Check that it is up

1. **Ask for the health document.** Use the command for your shell from [Quick start](quick-start.md) step 5, with the
   address you use for the program. You should see `"ok": true`. Read these fields:

    | Field | Healthy value |
    | --- | --- |
    | `production` | `false`, always |
    | `auth` | `entra` on a server; `off` is for a lab or your own machine only |
    | `azureConnectivity` | `not-configured` on a server (`recorded` and `stdio-developer-credential` are for development) |
    | `ledger` | counts of decisions, evidence, open contradictions and open proposals |

    If the command cannot connect, the program is not running: see [Troubleshooting](troubleshooting.md).

## Read the log

1. **Print the log.**

    ```text
    docker logs hcw-cloud-crawler
    ```

    You should see one JSON object per line, such as `{"ts":...,"event":"startup",...}`. Lines hold counts and short words,
    never evidence, tokens or names. Act on these events:

    | Event | What it means | What to do |
    | --- | --- | --- |
    | `startup_refused` | The program would not start, for example because sign-in is off on a network address. | [Troubleshooting](troubleshooting.md) |
    | `warning` with `"exposed":true` | It started without sign-in on a network address because `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` is set (lab only). | Turn sign-in on and remove that setting ([Configuration](configuration.md)). |
    | `request_error` with `"status":403` | A valid token lacks the app role in `CC_AUTH_REQUIRED_ROLES`; `reason` is `role`. | Assign the role to that person or service in Entra. |
    | `request_error` with `"status":401` | A caller's token was refused; `reason` is one word such as `missing`, `expired` or `signature`. | `signature` means the token was not signed by your directory; many of them mean someone is trying tokens that are not yours. |
    | `request_error` with `"status":503` | The directory's signing keys could not be fetched. | Check the server can reach the internet. |

## Restart it

1. **Restart the container.** This empties the ledger, because nothing is saved. Export what you need first.

    ```text
    docker restart hcw-cloud-crawler
    ```

    You should see `hcw-cloud-crawler`. The log then shows a `shutdown` line and a new `startup` line. Run the health command
    again: the `ledger` counts are back to `0`.

## Update the program

1. **Keep the running version under a second name**, so you can roll back.

    ```text
    docker tag hcw-cloud-crawler-appliance:dev hcw-cloud-crawler-appliance:previous
    ```

    You should see nothing.

2. **Get the new code and build the image.** In the repository folder:

    ```text
    git pull --ff-only
    ```

    ```text
    docker build -f infrastructure/docker/Dockerfile -t hcw-cloud-crawler-appliance:dev .
    ```

    You should see `Already up to date.` or a list of changed files, then a build that ends without an error.

3. **Stop the old container and start the new one.** Run `docker stop hcw-cloud-crawler`, then repeat
   [Deployment](deployment.md) step 4. You should see the health document with the new `version`.

4. **To roll back,** run `docker stop hcw-cloud-crawler`, then the same `docker run` command from Deployment step 4 with
   `hcw-cloud-crawler-appliance:previous` at the end. You should see the older `version` in the health document.

## What the project checks for you

Every Monday, and when the image's files change, a workflow scans the image with
[Trivy](https://trivy.dev/docs/latest/guide/) (`.github/workflows/image-scan.yml`). It fails on a fixable HIGH or CRITICAL
finding. Dependabot opens weekly update pull requests, and each pull request runs CodeQL, a dependency review, a secret
scan and `pip-audit`. Nothing watches your running server.

## What is not supported yet

- **Backups.** Nothing is saved to disk, so there is nothing to back up and a restart loses the ledger.
- **Metrics and alerts.** There is no metrics endpoint and no built-in alerting; watch the log and the health document
  yourself.
- **Sign-in proven against a real directory.** Every test token is made locally; the README's sandbox runbook,
  [Checking sign-in against a real tenant](../README.md#checking-sign-in-against-a-real-tenant), has not been run yet.
  [Issue #8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8) stays open until it is.
- **Fine-grained access.** The role check is one gate for the whole service, and there is no list of allowed client
  applications ([Known limitations](known-limitations.md)).
- **More than one copy.** Each copy would hold its own, different ledger.
