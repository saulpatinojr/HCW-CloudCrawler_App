# Installation

Install Cloud Crawler either from the source code or as a container image (a packaged copy of the program that runs
the same everywhere) that you build yourself.

> **Trusted lab network only.** Sign-in is off by default. On your own machine that is fine. The container image refuses
> to start without sign-in unless you add a lab-only setting (step 6 below). The program reports `"production": false`.

## Choose a route

| Route | Use it when | You need |
| --- | --- | --- |
| From source | You want to try it or change it. | [Git](https://git-scm.com/install/windows) and [uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Container image | You want it to run the way a server would. | Git and [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) |

Two tools are needed only for real Azure data ([Configuration](configuration.md)): [Node.js](https://nodejs.org/en/download)
22 and the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli). No ready-made image is published
anywhere, so you always build it yourself.

## Route 1: from source

Follow the [Quick start](quick-start.md), steps 1 to 4.

## Route 2: container image

The steps are the same in PowerShell 7 and Git Bash, except the last command of step 4.

1. **Start Docker Desktop and check it answers.**

    ```text
    docker version
    ```

    You should see a `Client` block and a `Server` block. If there is no `Server` block, Docker Desktop is not running yet.

2. **Get the code** by following [Quick start](quick-start.md) steps 1 and 2, then stay in the folder.

3. **Build the image.** A build can take a few minutes. Read what the command does in the
   [docker build reference](https://docs.docker.com/reference/cli/docker/image/build/).

    ```text
    docker build -f infrastructure/docker/Dockerfile -t hcw-cloud-crawler-appliance:dev .
    ```

    You should see the build finish without an error. Then run `docker image ls hcw-cloud-crawler-appliance`: it should
    list one line with the tag `dev`.

4. **Check the safety refusal.** The word `dummy` is not a real secret; it only makes the program refuse to start, which
   proves the check works.

    ```text
    docker run --rm -e AZURE_CLIENT_SECRET=dummy hcw-cloud-crawler-appliance:dev
    ```

    You should see one `startup_refused` line naming `AZURE_CLIENT_SECRET`. Then read the exit code: it should be `3`.

    PowerShell:

    ```powershell
    $LASTEXITCODE
    ```

    Git Bash:

    ```bash
    echo $?
    ```

5. **Check the sign-in refusal.** The image listens on every address inside the container. With sign-in off, the program
   refuses to run like that.

    ```text
    docker run --rm hcw-cloud-crawler-appliance:dev
    ```

    You should see one `startup_refused` line that ends `or (lab only) set CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true`, and
    exit code `3` again.

6. **Run the image for a lab.** The `-e CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` setting says you accept running without
   sign-in; use it on your own machine only. `-d` runs the container in the background and `127.0.0.1:` publishes the
   port to your computer only (see the [docker run reference](https://docs.docker.com/reference/cli/docker/container/run/)).
   For a server other people use, turn sign-in on instead ([Deployment](deployment.md)).

    ```text
    docker run -d --rm --name hcw-cloud-crawler -p 127.0.0.1:8080:8080 -e CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true hcw-cloud-crawler-appliance:dev
    ```

    You should see one long container id.

7. **Check it.** Run the health command from [Quick start](quick-start.md) step 5. You should see `"ok": true`,
   `"auth": "off"`, `"azureConnectivity": "not-configured"` and `"production": false`.

8. **Read its log, then stop it.**

    ```text
    docker logs hcw-cloud-crawler
    ```

    ```text
    docker stop hcw-cloud-crawler
    ```

    You should see a `warning` line with `"exposed":true` (expected: you used the lab-only setting) and a `startup` line.
    The second command prints the container name.

## Not installed yet

A saved ledger: stopping the program empties it. See [Known limitations](known-limitations.md).
