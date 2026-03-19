import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.responses import JSONResponse
from gmail_client import GmailClient

# In-memory draft store: {draft_id: {"payload": {...}, "expires_at": datetime}}
_drafts: dict = {}

load_dotenv()

client: GmailClient = None  # set during lifespan


@asynccontextmanager
async def lifespan(app):
    global client
    client = GmailClient()
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

mcp = FastMCP("Gmail Assistant", lifespan=lifespan, auth=auth)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health_check(request: Request) -> JSONResponse:
    """Health-check — verifies Gmail API connectivity and token refresh."""
    result = await client.health_check()
    status_code = 200 if result.get("status") == "ok" else 503
    return JSONResponse(result, status_code=status_code)


@mcp.tool()
async def list_emails(
    label: str = "INBOX",
    limit: int = 10,
    unread_only: bool = False,
    include_spam_trash: bool = False,
) -> dict:
    """List emails from a Gmail label/folder.

    label: label name or ID to list from (default: INBOX). Common labels: INBOX, SENT, DRAFTS, SPAM, TRASH, STARRED.
    limit: max number of emails to return (default: 10)
    unread_only: if true, return only unread emails (default: false)
    include_spam_trash: if true, include spam and trash (default: false)

    Returns: id, subject, from, date, snippet, labels, threadId, webLink for each email.
    """
    return await client.list_emails(
        label=label,
        limit=limit,
        unread_only=unread_only,
        include_spam_trash=include_spam_trash,
    )


@mcp.tool()
async def get_email(email_id: str) -> dict:
    """Get the full content of a specific email.

    email_id: Gmail message ID (required)

    Returns: all headers (from, to, cc, bcc, subject, date), body as plain text,
    list of attachments (filename + size, not content), and webLink.
    HTML emails are automatically converted to readable plain text.
    """
    return await client.get_email(email_id=email_id)


@mcp.tool()
async def search_emails(query: str, limit: int = 10) -> dict:
    """Search emails using Gmail's powerful search syntax.

    query: Gmail search query (required). Examples:
      - Plain keywords:        invoice payment
      - From sender:           from:supplier@example.com
      - To recipient:          to:me
      - Subject:               subject:invoice
      - Has attachment:        has:attachment
      - Date range:            after:2024/01/01 before:2024/12/31
      - Label:                 label:important
      - Unread:                is:unread
      - Starred:               is:starred
      - Combine:               from:bank subject:statement after:2024/01/01
    limit: max number of results (default: 10)

    Returns same fields as list_emails.
    """
    return await client.search_emails(query=query, limit=limit)


@mcp.tool()
async def get_thread(thread_id: str) -> dict:
    """Get all emails in a conversation thread in chronological order.

    thread_id: Gmail thread ID (required). Find it via list_emails or search_emails.

    Returns all messages in the thread, each with full content (headers, body, attachments).
    Useful for reading the full context of a conversation.
    """
    return await client.get_thread(thread_id=thread_id)


@mcp.tool()
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = None,
    bcc: str = None,
    reply_to_thread_id: str = None,
) -> dict:
    """Prepares an email draft and returns a preview. Does NOT send the email. You MUST show the preview to the user and receive clear, explicit confirmation before calling confirm_send_email. Ambiguous responses like 'okay', 'sure', 'continue', or silence do NOT count as confirmation.

    to: recipient address (required)
    subject: email subject (required)
    body: plain text body (required)
    cc: CC address(es), comma-separated (optional)
    bcc: BCC address(es), comma-separated (optional)
    reply_to_thread_id: if provided, adds this email to an existing thread (optional)

    Returns: draft preview with draft_id. Does NOT send.
    """
    draft_id = uuid.uuid4().hex[:8]
    _drafts[draft_id] = {
        "payload": {
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
            "bcc": bcc,
            "reply_to_thread_id": reply_to_thread_id,
        },
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }
    return {
        "draft_id": draft_id,
        "status": "draft_ready",
        "preview": {
            "to": to,
            "subject": subject,
            "body_preview": body[:300] + ("..." if len(body) > 300 else ""),
            "cc": cc,
            "bcc": bcc,
        },
        "instruction": "Show this preview to the user and ask for explicit confirmation before calling confirm_send_email. Do not call confirm_send_email unless the user clearly and unambiguously says to send.",
    }


@mcp.tool()
async def confirm_send_email(draft_id: str, from_mailbox: str) -> dict:
    """Actually sends a previously prepared email draft. Only call this after showing the user the draft preview and receiving explicit confirmation to send. Requires the draft_id from send_email.

    draft_id: the draft ID returned by send_email (required)
    from_mailbox: the Gmail address to send from — must be in the configured MAILBOXES list (required)
    """
    draft = _drafts.pop(draft_id, None)
    if draft is None or datetime.utcnow() > draft["expires_at"]:
        if draft_id in _drafts:
            _drafts.pop(draft_id, None)
        return {"error": "Draft expired or not found. Please call send_email again to create a new draft."}
    p = draft["payload"]
    return await client.send_email(
        to=p["to"],
        subject=p["subject"],
        body=p["body"],
        cc=p["cc"],
        bcc=p["bcc"],
        reply_to_thread_id=p["reply_to_thread_id"],
    )


@mcp.tool()
async def list_labels() -> dict:
    """List all Gmail labels (folders).

    Returns system labels (INBOX, SENT, DRAFTS, etc.) and user-created labels,
    each with id, name, type, and message counts (total + unread).
    """
    return await client.list_labels()


@mcp.tool()
async def get_email_stats() -> dict:
    """Get a quick overview of the Gmail mailbox.

    Returns: total message count, total thread count, and unread counts per label.
    Useful for orientation — call this first to understand the state of the inbox.
    """
    return await client.get_email_stats()


@mcp.tool()
async def mark_as_read(email_ids: list[str]) -> dict:
    """Mark one or more emails as read.

    email_ids: list of Gmail message IDs to mark as read (required)

    Returns: count of successfully marked emails and any errors.
    """
    return await client.mark_as_read(email_ids=email_ids)


@mcp.tool()
async def move_email(
    email_id: str,
    add_label: str,
    remove_inbox: bool = False,
) -> dict:
    """Apply a label to an email and optionally remove it from INBOX.

    email_id: Gmail message ID (required)
    add_label: label name or ID to apply (required). Use list_labels to see available labels.
    remove_inbox: if true, also removes the INBOX label (effectively "archives" the email) (default: false)

    Returns: updated label list for the email.
    """
    return await client.move_email(
        email_id=email_id,
        add_label=add_label,
        remove_inbox=remove_inbox,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
