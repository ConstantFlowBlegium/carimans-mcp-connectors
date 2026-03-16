import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.responses import JSONResponse
from outlook_client import OutlookClient

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
    """Send an email from a specific mailbox. The from_mailbox must be in the allowed MAILBOXES list."""
    return await client.send_message(from_mailbox=from_mailbox, to=to, subject=subject, body=body, cc=cc)

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
