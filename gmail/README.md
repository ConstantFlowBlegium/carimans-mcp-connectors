# Gmail MCP Server

MCP server giving Claude access to the `factuurcarimans@gmail.com` Gmail account.

## Setup

### 1. Environment variables

Copy `.env.example` to `.env` and fill in the values:

```
GOOGLE_CLIENT_ID        # OAuth client ID (shared with GDrive)
GOOGLE_CLIENT_SECRET    # OAuth client secret (shared with GDrive)
GOOGLE_REFRESH_TOKEN    # Refresh token covering Gmail + Drive scopes
MCP_BEARER_TOKEN        # Token Claude Desktop sends to authenticate
TARGET_EMAIL            # factuurcarimans@gmail.com
```

### 2. Run locally

```bash
pip install -r requirements.txt
python server.py
```

Server starts on `http://localhost:8000`. Health check: `GET /health`.

### 3. Deploy to Railway

- Connect this `/gmail` directory as a Railway service
- Set the five environment variables in Railway's variable panel
- Railway will build with the Dockerfile and deploy automatically
- Update `railway_url` in `/registry/mcp-registry.json` after deploy

## Available tools

| Tool | Description |
|------|-------------|
| `list_emails` | List emails from a label (INBOX by default) |
| `get_email` | Get full content of a specific email |
| `search_emails` | Search using Gmail syntax (`from:`, `subject:`, `after:`, etc.) |
| `get_thread` | Get all emails in a conversation thread |
| `send_email` | Send an email, optionally as a reply to a thread |
| `list_labels` | List all Gmail labels with message counts |
| `get_email_stats` | Mailbox overview: totals and unread counts per label |
| `mark_as_read` | Mark one or more emails as read |
| `move_email` | Apply a label to an email, optionally removing from INBOX |
