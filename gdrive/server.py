import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.responses import JSONResponse
from gdrive_client import GDriveClient

load_dotenv()

client: GDriveClient = None  # set during lifespan


@asynccontextmanager
async def lifespan(app):
    global client
    client = GDriveClient()
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

mcp = FastMCP("Google Drive Assistant", lifespan=lifespan, auth=auth)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health_check(request: Request) -> JSONResponse:
    """Health-check endpoint — verifies Drive API connectivity and token refresh."""
    result = await client.health_check()
    status_code = 200 if result.get("status") == "ok" else 503
    return JSONResponse(result, status_code=status_code)


@mcp.tool()
async def list_files(
    folder_id: str = "root",
    limit: int = 20,
    file_type: str = None,
) -> dict:
    """List files and folders in a Drive folder.

    folder_id: Drive folder ID, or 'root' for My Drive top level (default: root)
    limit: max number of results (default: 20)
    file_type: optional filter — one of: folder, document, spreadsheet, presentation, pdf, image, any
    """
    return await client.list_files(folder_id=folder_id, limit=limit, file_type=file_type)


@mcp.tool()
async def search_files(
    query: str,
    limit: int = 10,
    file_type: str = None,
) -> dict:
    """Full-text search across all files in Drive.

    Searches both file contents and file names. If no results are found for the
    full query, automatically retries with individual words.

    query: search term (required)
    limit: max number of results (default: 10)
    file_type: optional filter — one of: folder, document, spreadsheet, presentation, pdf, image, any
    """
    return await client.search_files(query=query, limit=limit, file_type=file_type)


@mcp.tool()
async def get_file_metadata(file_id: str) -> dict:
    """Get details about a specific file: name, type, size, owner, dates, webViewLink, parent folder.

    file_id: the Drive file ID (required)
    """
    return await client.get_file_metadata(file_id=file_id)


@mcp.tool()
async def read_file(file_id: str) -> dict:
    """Read the content of a file from Drive.

    Handles:
    - Google Docs → plain text
    - Google Sheets → CSV
    - Google Slides → plain text
    - PDFs → base64-encoded content
    - Plain text / JSON / CSV → content directly
    - Other binary files → metadata only with a note

    file_id: the Drive file ID (required)
    """
    return await client.read_file(file_id=file_id)


@mcp.tool()
async def list_folder_contents(
    folder_name: str = None,
    folder_id: str = None,
    recursive: bool = False,
) -> dict:
    """List everything inside a specific folder, by name or ID.

    folder_name: folder name to look up (optional)
    folder_id: Drive folder ID (optional; takes precedence over folder_name)
    recursive: if true, also descend into subfolders (default: false)

    Provide either folder_name or folder_id. If both are omitted, lists My Drive root.
    """
    return await client.list_folder_contents(
        folder_name=folder_name, folder_id=folder_id, recursive=recursive
    )


@mcp.tool()
async def get_recent_files(limit: int = 10, days: int = 7) -> dict:
    """Get recently modified files in Drive.

    limit: max number of results (default: 10)
    days: how many days back to look (default: 7)

    Returns files sorted by most recently modified, excluding folders.
    """
    return await client.get_recent_files(limit=limit, days=days)


@mcp.tool()
async def get_drive_stats() -> dict:
    """Get a summary of the Drive: storage used, file counts by type.

    Useful for orientation — call this first to understand what's in the Drive.
    """
    return await client.get_drive_stats()


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
