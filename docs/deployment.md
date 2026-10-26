# Deployment

How to run Cloud Crawler's container on a server in a trusted lab network, and what is not supported yet.

> **Not supported for production or non-lab use.** The program reports `"production": false`, and no workflow deploys it
> anywhere.

## What is not supported yet

- **Hardened sign-in.** Microsoft Entra sign-in exists but is off by default. The program still starts without it on a
  network address (it only writes a `warning` line with `"exposed":true`), and there is no role check on the tools. Making
  it refuse to start without sign-in, and an optional role check, are planned and tracked in
  [issue #8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8). They are not done.
- **A published image and a managed deployment.** You build the image yourself. There is no Azure Container Apps
  deployment, Bicep or Terraform ([`infrastructure/README.md`](../infrastructure/README.md) lists the plan).
- **A hosted Azure connection.** A server copy cannot collect live Azure data; it can only hold evidence handed to it.
- **A saved ledger, or more than one copy.** The ledger lives in the program's memory. Run exactly one copy, and expect a
  restart to empty it.
- **Sign-in tested against a real directory.** It has not been ([Known limitations](known-limitations.md)).

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

    You should be asked three times and see nothing else.

4. **Start the container.** Each `-e NAME` passes that setting's value from your window into the container.
   `127.0.0.1:` keeps the port private to the server, so only the encrypted front door in step 5 can reach it.

    ```text
    docker run -d --rm --name hcw-cloud-crawler -p 127.0.0.1:8080:8080 -e CC_AUTH_MODE -e CC_ENTRA_TENANT_ID -e CC_ENTRA_AUDIENCE -e CC_ALLOWED_HOSTS hcw-cloud-crawler-appliance:dev
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
