import os
from dotenv import load_dotenv
import httpx

load_dotenv()

class RobawsClient:
    def __init__(self):
        self.base_url = os.getenv("ROBAWS_BASE_URL", "https://app.robaws.com/api/v2")
        self.api_key = os.getenv("ROBAWS_API_KEY")
        self.api_secret = os.getenv("ROBAWS_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise ValueError("ROBAWS_API_KEY and ROBAWS_API_SECRET environment variables are required")
        self.client = httpx.AsyncClient(auth=(self.api_key, self.api_secret), headers={"Accept": "application/json"}, timeout=30.0)

    async def get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = await self.client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Robaws API returned {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach Robaws API: {str(e)}"}

    async def get_binary(self, url: str) -> httpx.Response:
        """Fetch raw binary content from a full URL using the same auth."""
        response = await self.client.get(url, headers={"Accept": "*/*"})
        response.raise_for_status()
        return response

    async def close(self):
        await self.client.aclose()