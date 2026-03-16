# Carimans MCP Connectors

Monorepo for all Carimans MCP servers — connecting Claude to internal business systems.

## Services

| Service | Directory | Status | Description |
|---------|-----------|--------|-------------|
| **Robaws** | [`robaws/`](robaws/) | Live | Construction data — projects, invoices, clients, suppliers |
| **Outlook** | [`outlook/`](outlook/) | Coming soon | Victor's email at victor@carimans.com |

## Repository Structure

```
carimans-mcp-connectors/
├── robaws/              # Robaws MCP server (deployed on Railway)
│   ├── server.py
│   ├── robaws_client.py
│   ├── test_api.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── railway.toml
│   └── .env.example
├── outlook/             # Outlook MCP server (coming soon)
├── shared/              # Shared utilities across servers
│   └── __init__.py
├── registry/            # Central registry of all MCP servers
│   └── mcp-registry.json
└── README.md
```

## Registry

See [`registry/mcp-registry.json`](registry/mcp-registry.json) for the central list of all MCP servers, their Railway URLs, and Claude Desktop config keys.

## Robaws MCP Server

For setup, deployment, and usage instructions see the files in [`robaws/`](robaws/).

- **Railway URL:** `https://robaws-mcp-production.up.railway.app`
- **Transport:** Streamable HTTP
- **Auth:** Bearer token via `MCP_AUTH_TOKEN` env var

### Claude Desktop Config

```json
{
  "mcpServers": {
    "robaws": {
      "type": "http",
      "url": "https://robaws-mcp-production.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer <your-MCP_AUTH_TOKEN>"
      }
    }
  }
}
```
