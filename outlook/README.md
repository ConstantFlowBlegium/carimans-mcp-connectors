# Outlook MCP Server

MCP server giving Claude access to Microsoft 365 mailboxes via the Graph API.

## Setup

### 1. Azure App Registration

1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations
2. Create a new registration (any name, e.g. "Carimans Outlook MCP")
3. Under **API permissions**, add **Microsoft Graph → Application permissions**:
   - `Mail.ReadWrite`
   - `Mail.Send`
4. Grant admin consent for the tenant
5. Under **Certificates & secrets**, create a new client secret
6. Note the **Application (client) ID**, **Directory (tenant) ID**, and the **secret value**

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in real values:

```
AZURE_TENANT_ID=your-azure-tenant-id
AZURE_CLIENT_ID=your-azure-app-client-id
AZURE_CLIENT_SECRET=your-azure-app-client-secret
MCP_BEARER_TOKEN=your-chosen-secret-token-here
MAILBOXES=["victor@carimans.com","info@carimans.com"]
PORT=8000
```

The `MAILBOXES` variable is a JSON array. Add or remove mailboxes here — no code changes needed.

### 3. Railway Deployment

Same pattern as the Robaws server:
1. Create a new Railway service pointing to this repo
2. Set the root directory to `/outlook`
3. Add all environment variables from step 2
4. Generate a public domain

### 4. Claude Desktop Config

```json
{
  "mcpServers": {
    "outlook-mcp": {
      "type": "http",
      "url": "https://<your-railway-domain>/mcp",
      "headers": {
        "Authorization": "Bearer <your-MCP_BEARER_TOKEN>"
      }
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `list_emails` | List recent emails (optionally filter by mailbox, folder, unread) |
| `get_email` | Get full content of a specific email |
| `search_emails` | Search emails by keyword across mailboxes |
| `send_email` | Send an email from a specific mailbox |
| `list_folders` | List all mail folders |
| `move_email` | Move an email to a different folder |
| `get_email_stats` | Unread counts per folder per mailbox |

All tools accept an optional `mailbox` parameter. If omitted, they query all mailboxes in the `MAILBOXES` list.
