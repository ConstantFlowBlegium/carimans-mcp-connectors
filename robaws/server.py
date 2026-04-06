import os
import io
import base64
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.responses import JSONResponse
import httpx
import pdfplumber
from robaws_client import RobawsClient

load_dotenv()

@asynccontextmanager
async def lifespan(app):
    global client
    client = RobawsClient()
    yield
    await client.close()

mcp_auth_token = os.getenv("MCP_AUTH_TOKEN")
auth = None
if mcp_auth_token:
    auth = StaticTokenVerifier(
        tokens={
            mcp_auth_token: {
                "client_id": "claude-desktop",
                "scopes": ["tools:call"],
            }
        }
    )

mcp = FastMCP("Robaws Assistant", lifespan=lifespan, auth=auth)

@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health_check(request: Request) -> JSONResponse:
    """Health-check endpoint for Railway (and other health probes)."""
    return JSONResponse({"status": "ok"})

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
async def get_purchase_invoices(size: int = 25, page: int = 0, logic_id: str = None) -> dict:
    """Fetch purchase invoices from Robaws. Optionally filter by logic_id (human-readable invoice ID like I260439) to find a specific invoice without manual pagination. Use get_document_content with the document_id to read the full PDF content for invoice verification and fine print analysis."""
    if logic_id:
        for p in range(10):
            result = await client.get("purchase-invoices", {"size": 25, "page": p})
            if "error" in result:
                return result
            items = result.get("content", result.get("data", []))
            for item in items:
                if item.get("logicId") == logic_id or item.get("logic_id") == logic_id or item.get("reference") == logic_id:
                    return item
            if result.get("last", True) or not items:
                break
        return {"error": f"Invoice with logic_id '{logic_id}' not found within first 10 pages"}
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
async def get_invoices(size: int = 25, page: int = 0, logic_id: str = None) -> dict:
    """Fetch sales invoices from Robaws. Optionally filter by logic_id (human-readable invoice ID) to find a specific invoice without manual pagination. Use get_document_content with the document_id to read the full PDF content for invoice verification and fine print analysis."""
    if logic_id:
        for p in range(10):
            result = await client.get("invoices", {"size": 25, "page": p})
            if "error" in result:
                return result
            items = result.get("content", result.get("data", []))
            for item in items:
                if item.get("logicId") == logic_id or item.get("logic_id") == logic_id or item.get("reference") == logic_id:
                    return item
            if result.get("last", True) or not items:
                break
        return {"error": f"Invoice with logic_id '{logic_id}' not found within first 10 pages"}
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
async def get_document_content(document_id: int) -> dict:
    """Fetch any Robaws document by its ID and return its readable content. Works for any document type: purchase invoice PDFs, sales invoice PDFs, project attachments, contracts, delivery notes, etc. For PDFs, extracts text automatically (with OCR fallback for scanned documents). For other file types, returns base64-encoded content."""
    try:
        metadata = await client.get(f"documents/{document_id}")
        if "error" in metadata:
            return metadata

        filename = metadata.get("fileName", metadata.get("filename", f"document_{document_id}"))
        content_type = metadata.get("contentType", metadata.get("content_type", "application/octet-stream"))
        file_size = metadata.get("fileSize", metadata.get("file_size", 0))

        doc_url = f"https://app.robaws.com/documents/{document_id}?inline=true"
        try:
            response = await client.get_binary(doc_url)
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch document content: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach document URL: {str(e)}"}

        raw_bytes = response.content
        is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")

        if is_pdf:
            # Stage 1: pdfplumber
            text_content = ""
            page_count = 0
            try:
                with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                    page_count = len(pdf.pages)
                    pages_text = []
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pages_text.append(page_text)
                    text_content = "\n\n".join(pages_text)
            except Exception:
                text_content = ""

            if text_content.strip():
                return {
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": file_size,
                    "text_content": text_content,
                    "page_count": page_count,
                    "extraction_method": "pdfplumber",
                    "document_id": document_id,
                }

            # Stage 2: Mindee OCR fallback
            mindee_api_key = os.getenv("MINDEE_API_KEY")
            if mindee_api_key:
                try:
                    async with httpx.AsyncClient() as mindee_client:
                        mindee_response = await mindee_client.post(
                            "https://api.mindee.net/v1/products/mindee/invoices/v4/predict",
                            headers={"Authorization": f"Token {mindee_api_key}"},
                            files={"document": (filename, raw_bytes, "application/pdf")},
                            timeout=60.0,
                        )
                        mindee_response.raise_for_status()
                        mindee_data = mindee_response.json()

                    prediction = mindee_data.get("document", {}).get("inference", {}).get("prediction", {})
                    extracted_lines = []

                    supplier_name = prediction.get("supplier_name", {}).get("value")
                    if supplier_name:
                        extracted_lines.append(f"Supplier: {supplier_name}")

                    invoice_number = prediction.get("invoice_number", {}).get("value")
                    if invoice_number:
                        extracted_lines.append(f"Invoice Number: {invoice_number}")

                    invoice_date = prediction.get("date", {}).get("value")
                    if invoice_date:
                        extracted_lines.append(f"Date: {invoice_date}")

                    due_date = prediction.get("due_date", {}).get("value")
                    if due_date:
                        extracted_lines.append(f"Due Date: {due_date}")

                    total_net = prediction.get("total_net", {}).get("value")
                    if total_net is not None:
                        extracted_lines.append(f"Total Net: {total_net}")

                    total_amount = prediction.get("total_amount", {}).get("value")
                    if total_amount is not None:
                        extracted_lines.append(f"Total Amount: {total_amount}")

                    total_tax = prediction.get("total_tax", {}).get("value")
                    if total_tax is not None:
                        extracted_lines.append(f"Total Tax: {total_tax}")

                    currency = prediction.get("locale", {}).get("currency")
                    if currency:
                        extracted_lines.append(f"Currency: {currency}")

                    payment_details = prediction.get("supplier_payment_details", [])
                    for pd in payment_details:
                        iban = pd.get("iban")
                        if iban:
                            extracted_lines.append(f"IBAN: {iban}")

                    line_items = prediction.get("line_items", [])
                    if line_items:
                        extracted_lines.append("\nLine Items:")
                        for i, item in enumerate(line_items, 1):
                            desc = item.get("description", "N/A")
                            qty = item.get("quantity")
                            unit_price = item.get("unit_price")
                            total = item.get("total_amount")
                            line = f"  {i}. {desc}"
                            if qty is not None:
                                line += f" | Qty: {qty}"
                            if unit_price is not None:
                                line += f" | Unit: {unit_price}"
                            if total is not None:
                                line += f" | Total: {total}"
                            extracted_lines.append(line)

                    if extracted_lines:
                        return {
                            "filename": filename,
                            "content_type": content_type,
                            "size_bytes": file_size,
                            "text_content": "\n".join(extracted_lines),
                            "page_count": page_count,
                            "extraction_method": "mindee_ocr",
                            "document_id": document_id,
                        }
                except Exception:
                    pass

            # Stage 3: base64 fallback
            return {
                "filename": filename,
                "content_type": content_type,
                "size_bytes": file_size,
                "base64_content": base64.b64encode(raw_bytes).decode("utf-8"),
                "page_count": page_count,
                "extraction_method": "base64_fallback",
                "document_id": document_id,
            }

        # Non-PDF files: return base64
        return {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": file_size,
            "base64_content": base64.b64encode(raw_bytes).decode("utf-8"),
            "extraction_method": "base64",
            "document_id": document_id,
        }

    except Exception as e:
        return {"error": f"Failed to process document {document_id}: {str(e)}"}

@mcp.tool()
async def get_offer_line_items(offer_id: int, include: list[str] = None) -> dict:
    """Fetch line items for a specific offer. Each line item contains quantity, price, discount, description, article info, and VAT details. Use the 'include' parameter to embed related objects (e.g. article, material, vatTariff)."""
    params = {}
    if include:
        params["include"] = include
    return await client.get(f"offers/{offer_id}/line-items", params)

@mcp.tool()
async def get_purchase_invoice_line_items(purchase_invoice_id: int, include: list[str] = None) -> dict:
    """Fetch line items for a specific purchase invoice. Each line item contains quantity, price, discount, description, project/article references, and date range. Use the 'include' parameter to embed related objects (e.g. material, article, project, vatTariff)."""
    params = {}
    if include:
        params["include"] = include
    return await client.get(f"purchase-invoices/{purchase_invoice_id}/line-items", params)

@mcp.tool()
async def get_purchase_supply_order_line_items(purchase_supply_order_id: int, include: list[str] = None) -> dict:
    """Fetch line items for a specific purchase supply order. Each line item contains quantity, price, discount, received amount, and supplier/article references. Use the 'include' parameter to embed related objects (e.g. post, articleSupplier, article, material, activity, order, project, vatTariff)."""
    params = {}
    if include:
        params["include"] = include
    return await client.get(f"purchase-supply-orders/{purchase_supply_order_id}/line-items", params)

@mcp.tool()
async def get_work_order_line_items(work_order_id: int, include: list[str] = None) -> dict:
    """Fetch line items for a specific work order. Each line item contains quantity, price, cost price, discount, description, and article/post references. Use the 'include' parameter to embed related objects (e.g. article, post)."""
    params = {}
    if include:
        params["include"] = include
    return await client.get(f"work-orders/{work_order_id}/line-items", params)

@mcp.tool()
async def get_work_order_material_entries(work_order_id: int, include: list[str] = None) -> dict:
    """Fetch material entries for a specific work order. Each entry contains material/article references, amounts (billable and cost), sale price, and remarks. Use the 'include' parameter to embed related objects (e.g. material, article)."""
    params = {}
    if include:
        params["include"] = include
    return await client.get(f"work-orders/{work_order_id}/material-entries", params)

@mcp.tool()
async def search_robaws(endpoint: str, params: dict = None) -> dict:
    """Generic tool to query any Robaws endpoint with custom parameters."""
    return await client.get(endpoint, params or {})

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))