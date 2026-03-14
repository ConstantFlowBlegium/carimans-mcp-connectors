import os
from fastmcp import FastMCP
from robaws_client import RobawsClient

mcp = FastMCP("Robaws Assistant")

client = None

@mcp.lifespan
async def lifespan():
    global client
    client = RobawsClient()
    yield
    await client.close()

@mcp.tool()
async def get_work_orders(size: int = 25, page: int = 0, status: str = None, date_from: str = None, date_to: str = None, client_id: str = None) -> dict:
    """Fetch work orders from Robaws. Optionally filter by status, date range, or client."""
    params = {"size": size, "page": page}
    if status:
        params["status"] = status
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    if client_id:
        params["client_id"] = client_id
    return await client.get("work-orders", params)

@mcp.tool()
async def get_clients(size: int = 25, page: int = 0, search_term: str = None) -> dict:
    """Fetch clients from Robaws. Optionally filter by search term."""
    params = {"size": size, "page": page}
    if search_term:
        params["search"] = search_term  # Assuming 'search' is the param
    return await client.get("clients", params)

@mcp.tool()
async def get_purchase_orders(size: int = 25, page: int = 0) -> dict:
    """Fetch purchase orders from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("purchase-supply-orders", params)

@mcp.tool()
async def get_purchase_invoices(size: int = 25, page: int = 0) -> dict:
    """Fetch purchase invoices from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("purchase-invoices", params)

@mcp.tool()
async def get_suppliers(size: int = 25, page: int = 0) -> dict:
    """Fetch suppliers from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("suppliers", params)

@mcp.tool()
async def get_stock_locations(size: int = 25, page: int = 0) -> dict:
    """Fetch stock locations from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("stock-locations", params)

@mcp.tool()
async def get_projects(size: int = 25, page: int = 0, status: str = None, phase: str = None) -> dict:
    """Fetch projects from Robaws. Optionally filter by status or phase."""
    params = {"size": size, "page": page}
    if status:
        params["status"] = status
    if phase:
        params["phase"] = phase
    return await client.get("projects", params)

@mcp.tool()
async def get_offers(size: int = 25, page: int = 0) -> dict:
    """Fetch offers from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("offers", params)

@mcp.tool()
async def get_invoices(size: int = 25, page: int = 0) -> dict:
    """Fetch sales invoices from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("invoices", params)

@mcp.tool()
async def get_employees(size: int = 25, page: int = 0) -> dict:
    """Fetch employees from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("employees", params)

@mcp.tool()
async def get_planning(size: int = 25, page: int = 0, date: str = None) -> dict:
    """Fetch planning items from Robaws. Optionally filter by date."""
    params = {"size": size, "page": page}
    if date:
        params["date"] = date
    return await client.get("planning", params)

@mcp.tool()
async def get_articles(size: int = 25, page: int = 0) -> dict:
    """Fetch articles/products from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("articles", params)

@mcp.tool()
async def get_tasks(size: int = 25, page: int = 0) -> dict:
    """Fetch tasks from Robaws."""
    params = {"size": size, "page": page}
    return await client.get("tasks", params)

@mcp.tool()
async def search_robaws(endpoint: str, params: dict = {}) -> dict:
    """Generic tool to query any Robaws endpoint with custom parameters."""
    return await client.get(endpoint, params)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))