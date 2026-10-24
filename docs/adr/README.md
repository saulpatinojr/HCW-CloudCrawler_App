# Architecture decision records

One file per decision, numbered in order: `NNNN-short-title.md`, starting at
`0001`. Copy `template.md`. A decision that replaces an earlier one sets the
earlier record's status to **Superseded by NNNN** rather than editing its
content.

Propose a decision with the **Architecture decision record** issue form; once
accepted, record it here and link the issue.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-pin-azure-mcp-server-3-0-0.md) | Azure MCP Server is pinned to 3.0.0 and consumed as a separate process | Accepted |
| [0002](0002-engine-moves-downstream-unchanged.md) | The engine is seeded here and moves downstream to the AddOn unchanged | Accepted |
| [0003](0003-the-addon-never-calls-azure.md) | Only the App edition and the website call Azure MCP; the AddOn never calls Azure | Accepted |

Next number: 0004.
