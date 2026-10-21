# Infrastructure

| Path | What |
| --- | --- |
| `docker/Dockerfile` | The appliance image: hash-pinned runtime set, engine and application as source trees, uid 10001, pip removed, health check on `/api/health`. |
| `docker/versions.env` | The base image tag and digest every `FROM` must match. |

Not yet in this slice, and planned by the website proposal (section 18): the
derived Azure MCP Server image with its baked-in flags, the `azd` and Bicep
deployment to Azure Container Apps, the Terraform root, and the app
registrations for the on-behalf-of flow. Nothing in this folder names a
tenant, subscription, region, resource group or DNS name.
