# Google Drive MCP Server

FastMCP server giving Claude read-only access to `factuurcarimans@gmail.com`'s Google Drive.

## Tools

| Tool | Description |
|---|---|
| `list_files` | List files in a folder (default: My Drive root) |
| `search_files` | Full-text + name search across all files; auto-retries with individual words |
| `get_file_metadata` | File details: name, type, size, owner, dates, webViewLink, parent |
| `read_file` | Read file contents (Docs→text, Sheets→CSV, Slides→text, PDF→base64, text→direct) |
| `list_folder_contents` | List a folder by name or ID, optionally recursive |
| `get_recent_files` | Recently modified files, filtered by N days |
| `get_drive_stats` | Storage used + file counts by type |

## Environment variables

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
MCP_BEARER_TOKEN=
```

## Setup

### 1. Create OAuth credentials in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (or use an existing one)
3. Enable the **Google Drive API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
5. Application type: **Desktop app**
6. Download the JSON — note the `client_id` and `client_secret`
7. Under **OAuth consent screen**, add `factuurcarimans@gmail.com` as a test user

### 2. Generate a refresh token (one-time)

Install dependencies locally:

```bash
pip install google-auth-oauthlib
```

Run this script once from your machine:

```python
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",   # the file you downloaded from Cloud Console
    scopes=SCOPES,
)
creds = flow.run_local_server(port=0)

print("GOOGLE_REFRESH_TOKEN =", creds.refresh_token)
print("GOOGLE_CLIENT_ID     =", creds.client_id)
print("GOOGLE_CLIENT_SECRET =", creds.client_secret)
```

Sign in as `factuurcarimans@gmail.com` when the browser opens. Copy the printed values into your Railway environment variables.

> The refresh token is long-lived. The server refreshes the access token automatically in memory — nothing is written to disk.

### 3. Set environment variables in Railway

| Variable | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | From step 1 |
| `GOOGLE_CLIENT_SECRET` | From step 1 |
| `GOOGLE_REFRESH_TOKEN` | From step 2 |
| `MCP_BEARER_TOKEN` | Any strong random string — also set in Claude config as `GDRIVE_MCP_TOKEN` |

### 4. Deploy to Railway

```bash
railway up
```

After deploy, update `registry/mcp-registry.json` with the assigned Railway URL.

## Health check

```
GET /health
```

Returns `{"status": "ok", "user": "factuurcarimans@gmail.com"}` if credentials are valid and Drive API is reachable. Returns HTTP 503 if degraded.
