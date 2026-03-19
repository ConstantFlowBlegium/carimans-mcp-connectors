import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.responses import JSONResponse
from outlook_client import OutlookClient

# In-memory draft store: {draft_id: {"payload": {...}, "expires_at": datetime}}
_drafts: dict = {}

load_dotenv()

@asynccontextmanager
async def lifespan(app):
    global client
    client = OutlookClient()
    yield
    await client.close()

mcp_bearer_token = os.getenv("MCP_BEARER_TOKEN")
auth = None
if mcp_bearer_token:
    auth = StaticTokenVerifier(
        tokens={
            mcp_bearer_token: {
                "client_id": "claude-desktop",
                "scopes": ["tools:call"],
            }
        }
    )

mcp = FastMCP("Outlook Assistant", lifespan=lifespan, auth=auth)

@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health_check(request: Request) -> JSONResponse:
    """Health-check endpoint for Railway (and other health probes)."""
    result = await client.health_check()
    status_code = 200 if result.get("status") == "ok" else 503
    return JSONResponse(result, status_code=status_code)

@mcp.tool()
async def list_emails(
    mailbox: str = None, folder: str = "inbox", limit: int = 10, unread_only: bool = False
) -> dict:
    """List recent emails. If mailbox is omitted, queries all configured mailboxes."""
    return await client.list_messages(mailbox=mailbox, folder=folder, limit=limit, unread_only=unread_only)

@mcp.tool()
async def get_email(email_id: str, mailbox: str) -> dict:
    """Get the full content of a specific email by its ID."""
    return await client.get_message(email_id=email_id, mailbox=mailbox)

@mcp.tool()
async def search_emails(query: str, mailbox: str = None, limit: int = 10) -> dict:
    """Search emails by keyword. If mailbox is omitted, searches all configured mailboxes."""
    return await client.search_messages(query=query, mailbox=mailbox, limit=limit)

@mcp.tool()
async def send_email(from_mailbox: str, to: str, subject: str, body: str, cc: str = None) -> dict:
    """Prepares an email draft and returns a preview. Does NOT send the email. You MUST show the preview to the user and receive clear, explicit confirmation before calling confirm_send_email. Ambiguous responses like 'okay', 'sure', 'continue', or silence do NOT count as confirmation."""
    draft_id = uuid.uuid4().hex[:8]
    _drafts[draft_id] = {
        "payload": {
            "from_mailbox": from_mailbox,
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
        },
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }
    return {
        "draft_id": draft_id,
        "status": "draft_ready",
        "preview": {
            "from": from_mailbox,
            "to": to,
            "subject": subject,
            "body_preview": body[:300] + ("..." if len(body) > 300 else ""),
            "cc": cc,
        },
        "instruction": "Show this preview to the user and ask for explicit confirmation before calling confirm_send_email. Do not call confirm_send_email unless the user clearly and unambiguously says to send.",
    }


@mcp.tool()
async def confirm_send_email(draft_id: str, mailbox: str) -> dict:
    """Actually sends a previously prepared email draft. Only call this after showing the user the draft preview and receiving explicit confirmation to send. Requires the draft_id from send_email."""
    draft = _drafts.pop(draft_id, None)
    if draft is None or datetime.utcnow() > draft["expires_at"]:
        if draft_id in _drafts:
            _drafts.pop(draft_id, None)
        return {"error": "Draft expired or not found. Please call send_email again to create a new draft."}
    p = draft["payload"]
    return await client.send_message(
        from_mailbox=p["from_mailbox"],
        to=p["to"],
        subject=p["subject"],
        body=p["body"],
        cc=p["cc"],
    )

@mcp.tool()
async def list_folders(mailbox: str = None) -> dict:
    """List all mail folders for a mailbox. Defaults to the first configured mailbox."""
    return await client.list_folders(mailbox=mailbox)

@mcp.tool()
async def move_email(email_id: str, folder_name: str, mailbox: str) -> dict:
    """Move an email to a different folder by folder name."""
    return await client.move_message(email_id=email_id, folder_name=folder_name, mailbox=mailbox)

@mcp.tool()
async def get_email_stats(mailbox: str = None) -> dict:
    """Get unread email counts per folder. If mailbox is omitted, returns stats for all mailboxes."""
    return await client.get_stats(mailbox=mailbox)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
