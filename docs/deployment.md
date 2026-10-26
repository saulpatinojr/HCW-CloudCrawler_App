# Deployment

How to run Cloud Crawler's container on a server in a trusted lab network, and what is not supported yet.

> **Not supported for production.** The program reports `"production": false`, and no workflow deploys it anywhere. Use
> this page for a lab or a trial.

## What the program refuses

With sign-in off, the program exits with code 3 on any address except this computer's own, unless
`CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` is set on purpose (lab only). The container image listens on every address,
so a bare `docker run` now fails; lab use needs that `-e` setting ([Installation](installation.md), Route 2, step 6).
The steps below turn sign-in on instead, which needs no such setting. An optional role check, `CC_AUTH_REQUIRED_ROLES`,
answers `403` to a valid token that lacks the role. Both came with
[pull request #52](https://github.com/saulpatinojr/HCW-CloudCrawler_App/pull/52) for
[issue #8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8).

## What is not supported yet

- **Sign-in proven against a real directory.** Every test token is made locally. The README has a sandbox runbook,
  [Checking sign-in against a real tenant](../README.md#checking-sign-in-against-a-real-tenant); it has not been run yet.
  Issue #8 stays open until it is.
- **Fine-grained access.** The role check is one gate for the whole service, and there is no list of allowed client
  applications ([Known limitations](known-limitations.md)).
- **A published image and a managed deployment.** You build the image yourself. There is no Azure Container Apps
  deployment, Bicep or Terraform ([`infrastructure/README.md`](../infrastructure/README.md) lists the plan).
- **A hosted Azure connection.** A server copy cannot collect live Azure data; it can only hold evidence handed to it.
- **A saved ledger, or more than one copy.** The ledger lives in the program's memory. Run exactly one copy, and expect a
  restart to empty it.

## Run it on a lab server

You need Docker on the server ([Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) on
Windows) and a Microsoft Entra directory you administer. The steps work in PowerShell 7 and Git Bash except where shown.

1. **Build the image on the server.** Follow [Installation](installation.md), Route 2, steps 1 to 3. You should see
   `docker image ls hcw-cloud-crawler-appliance` list the tag `dev`.

2. **Register the app in Entra.** Follow [Configuration](configuration.md), "Turn on sign-in", steps 1 to 3. You should
   have a tenant id, an Application ID URI, a client id and an assignment list.

3. **Set the settings in your window.** Each command asks you to paste values; the last asks for the host name callers
   will type, such as the server's DNS name.

    PowerShell:

    ```powershell
    $env:CC_AUTH_MODE = "entra"; $env:CC_ENTRA_TENANT_ID = Read-Host "Directory (tenant) ID"; $env:CC_ENTRA_AUDIENCE = Read-Host "Application ID URI, a space, then the client ID"; $env:CC_ALLOWED_HOSTS = Read-Host "Host name callers will use"
    ```

    Git Bash:

    ```bash
    export CC_AUTH_MODE=entra; read -r -p "Directory (tenant) ID: " CC_ENTRA_TENANT_ID; read -r -p "Application ID URI, a space, then the client ID: " CC_ENTRA_AUDIENCE; read -r -p "Host name callers will use: " CC_ALLOWED_HOSTS; export CC_ENTRA_TENANT_ID CC_ENTRA_AUDIENCE CC_ALLOWED_HOSTS
    ```

    You should be asked three times and see nothing else. To also require an app role, follow
    [Configuration](configuration.md), "Turn on sign-in", step 6, in the same window.

4. **Start the container.** Each `-e NAME` passes that setting's value from your window into the container; a setting you did not set (such as
   `CC_AUTH_REQUIRED_ROLES`) is simply left out.
   `127.0.0.1:` keeps the port private to the server, so only the encrypted front door in step 5 can reach it.

    ```text
    docker run -d --rm --name hcw-cloud-crawler -p 127.0.0.1:8080:8080 -e CC_AUTH_MODE -e CC_ENTRA_TENANT_ID -e CC_ENTRA_AUDIENCE -e CC_ALLOWED_HOSTS -e CC_AUTH_REQUIRED_ROLES hcw-cloud-crawler-appliance:dev
    ```

    You should see one long container id.

5. **Put encrypted web traffic (HTTPS) in front.** The program speaks plain HTTP. Use your reverse proxy or your
   platform's ingress to serve HTTPS for the host name from step 3 and forward to `127.0.0.1:8080` on the server. You
   should be able to open `https://` plus that host name plus `/api/health` in a browser and see the health document.

6. **Check that sign-in is on.** Run the health command from [Quick start](quick-start.md) step 5 and the 401 check from
   [Configuration](configuration.md), "Turn on sign-in", step 7. You should see `"auth": "entra"`, `"production": false`
   and `401`.

## Roll back

Keep the previous image under a second tag before you build a new one; [Operations](operations.md), "Update the
program", shows how. There is nothing to migrate, but the ledger is lost on any restart.

See also [Operations](operations.md) and [Security overview](security.md).
