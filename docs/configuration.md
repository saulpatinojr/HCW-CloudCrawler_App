# Configuration

Cloud Crawler is configured with environment variables (named settings you set in the window before you start the
program). It does not read a `.env` file; [`.env.example`](../.env.example) only lists every name. A wrong value makes the
program stop at start-up and name the setting.

> **Never put a secret in a setting.** The program refuses to start if `AZURE_CLIENT_SECRET`,
> `AZURE_CLIENT_CERTIFICATE_PATH`, `AZURE_CLIENT_CERTIFICATE_PASSWORD`, `AZURE_USERNAME` or `AZURE_PASSWORD` is set.

## Set a setting

A setting lasts only for the window you set it in. See
[environment variables in PowerShell](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_environment_variables).

PowerShell:

```powershell
$env:PORT = "8090"
```

Git Bash:

```bash
export PORT=8090
```

You should see nothing. The next start listens on port 8090. To undo it, run `Remove-Item Env:PORT` (PowerShell) or
`unset PORT` (Git Bash).

## The settings

| Setting | Default | What it does |
| --- | --- | --- |
| `PORT` | `8080` | The port to listen on. |
| `CC_BIND_HOST` | `127.0.0.1` (the image sets `0.0.0.0`) | The address to listen on. `127.0.0.1` means this computer only. With sign-in off, any other address is refused at start-up unless the lab-only setting below is `true`. |
| `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK` | empty | **Lab only.** `true` lets the program start without sign-in on an address other than this computer's own. Refused when sign-in is on. The image never sets it. |
| `CC_ALLOWED_HOSTS` | empty | Host names callers use to reach `/mcp`, separated by spaces or commas. Any other name gets `421`. |
| `CC_AZMCP_MODE` | `off` | Where Azure data comes from: `off` (none), `recorded` (made-up recordings), `stdio` (real Azure MCP Server 3.0.0). |
| `CC_AZMCP_RECORDINGS` | `samples/azure-mcp` | The folder the `recorded` mode replays. |
| `CC_AUTH_MODE` | `off` | `off` or `entra` (Microsoft Entra sign-in). |
| `CC_ENTRA_TENANT_ID` | empty | Your directory (tenant) id. Needed with `entra`. |
| `CC_ENTRA_AUDIENCE` | empty | The accepted audience values, separated by spaces. Needed with `entra`. |
| `CC_AUTH_REQUIRED_ROLES` | empty | Optional, with `entra`. App role values, separated by spaces or commas. A token must carry at least one, or the answer is `403`. |
| `CC_ENTRA_HUMAN_SCOPE` | `access_as_user` | The scope a person's token needs for the human-only tools. |
| `CC_ENTRA_CLOCK_SKEW_SECONDS`, `CC_ENTRA_JWKS_CACHE_SECONDS` | `60`, `900` | Token time tolerance (0 to 300) and signing-key cache time (60 to 86400). |
| `CC_MAX_UPLOAD_BYTES`, `CC_MAX_ROWS` | `5242880`, `5000` | Largest request body and largest Resource Graph export accepted. |
| `CC_EVIDENCE_TTL_HOURS` | `24` | How long evidence counts as fresh. |

Entra settings (including `CC_AUTH_REQUIRED_ROLES`) with `CC_AUTH_MODE` left `off`, or `entra` without a tenant id or audience, stop the program at start-up. So does sign-in `off` on a non-loopback address without the lab-only setting.

## Use real Azure data

This mode starts Azure MCP Server 3.0.0 with your own Azure sign-in and only reads. It has not been run against a live
account in the project's tests ([Known limitations](known-limitations.md)). You need [Node.js](https://nodejs.org/en/download)
22 and the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli).

1. **Sign in.** See [Sign in with Azure CLI](https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli).

    ```text
    az login
    ```

    You should see your browser open, and then your subscriptions listed.

2. **Start the program.** `AZURE_TOKEN_CREDENTIALS` is the only `AZURE_*` setting passed on to Azure MCP Server.

    PowerShell:

    ```powershell
    $env:AZURE_TOKEN_CREDENTIALS = "AzureCliCredential"; $env:CC_AZMCP_MODE = "stdio"; uv run python -m cloud_crawler_appliance
    ```

    Git Bash:

    ```bash
    AZURE_TOKEN_CREDENTIALS=AzureCliCredential CC_AZMCP_MODE=stdio uv run python -m cloud_crawler_appliance
    ```

    You should see a `startup` line with `"azmcp":"stdio"`.

3. **Check it.** Run the health command from [Quick start](quick-start.md) step 5. You should see
   `"azureConnectivity": "stdio-developer-credential"`.

## Turn on sign-in

With sign-in on, every route except `GET /api/health` needs a Microsoft Entra access token. Do these steps in order.

1. **Register the app.** Open the [Microsoft Entra admin center](https://entra.microsoft.com), then Identity,
   Applications, App registrations, New registration. Name it `HCW Cloud Crawler API`, choose "Accounts in this
   organizational directory only", leave Redirect URI empty and select Register
   ([Microsoft's steps](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)). You should
   see the Overview page with "Application (client) ID" and "Directory (tenant) ID". Keep this page open.

2. **Expose a scope.** Open Expose an API. Next to "Application ID URI" select Add and accept the suggested value. Then
   add a scope named `access_as_user`, "Admins and users" can consent, display name `Act as the signed-in user`, state
   Enabled ([Microsoft's steps](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-expose-web-apis)).
   You should see the scope listed.

3. **Allow only chosen people.** Open Enterprise applications, select `HCW Cloud Crawler API`, Properties, set
   "Assignment required?" to Yes and save, then add the people under Users and groups
   ([Microsoft's steps](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal)).
   Without this, anyone in your directory can get a token. You should see only the people you added.

4. **Put encrypted web traffic (TLS) in front of the program** when anyone other than you will use it
   ([Deployment](deployment.md)). The program itself speaks plain HTTP.

5. **Set the sign-in settings.** Each command asks you to paste a value from the Overview and Expose an API pages. For the
   audience, paste the Application ID URI, a space, then the client id.

    PowerShell:

    ```powershell
    $env:CC_AUTH_MODE = "entra"; $env:CC_ENTRA_TENANT_ID = Read-Host "Directory (tenant) ID"; $env:CC_ENTRA_AUDIENCE = Read-Host "Application ID URI, a space, then the client ID"
    ```

    Git Bash:

    ```bash
    export CC_AUTH_MODE=entra; read -r -p "Directory (tenant) ID: " CC_ENTRA_TENANT_ID; read -r -p "Application ID URI, a space, then the client ID: " CC_ENTRA_AUDIENCE; export CC_ENTRA_TENANT_ID CC_ENTRA_AUDIENCE
    ```

    You should be asked twice and see nothing else.

6. **Optional: also require an app role.** Skip this unless you want only holders of a role to get in. First create the role
   and assign it to your people, as the README describes under "Optional app role" in
   [What you do in Microsoft Entra, once](../README.md#what-you-do-in-microsoft-entra-once). The role value must differ
   from `access_as_user`. Then set the value.

    PowerShell:

    ```powershell
    $env:CC_AUTH_REQUIRED_ROLES = Read-Host "App role value"
    ```

    Git Bash:

    ```bash
    read -r -p "App role value: " CC_AUTH_REQUIRED_ROLES; export CC_AUTH_REQUIRED_ROLES
    ```

    You should be asked once. A valid token without the role will get `403`.

7. **Start the program.**

    ```text
    uv run python -m cloud_crawler_appliance
    ```

    You should see a `startup` line with `"auth":true`.

8. **Check that it refuses callers without a token.** In a second window, run the health command from
   [Quick start](quick-start.md) step 5: it should show `"auth": "entra"`. Then ask `/mcp` without a token.

    PowerShell:

    ```powershell
    curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8080/mcp
    ```

    Git Bash:

    ```bash
    curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/mcp
    ```

    You should see `401`. Programs that call the tools must request tokens for the scope `api://<client id>/access_as_user`,
    using your client id.

Sign-in has never been tried against a real directory. The README has a short sandbox runbook for that,
[Checking sign-in against a real tenant](../README.md#checking-sign-in-against-a-real-tenant); it has not been run yet
([Known limitations](known-limitations.md)). The design is
[ADR 0004](adr/0004-entra-token-validation-on-api-and-mcp.md).
