import os
import asyncio
import json
from dotenv import load_dotenv
import httpx
import msal

load_dotenv()

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    def __init__(self):
        self.tenant_id = os.getenv("AZURE_TENANT_ID")
        self.client_id = os.getenv("AZURE_CLIENT_ID")
        self.client_secret = os.getenv("AZURE_CLIENT_SECRET")
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise ValueError(
                "AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET "
                "environment variables are required"
            )

        mailboxes_raw = os.getenv("MAILBOXES", "[]")
        self.mailboxes = json.loads(mailboxes_raw)
        if not self.mailboxes:
            raise ValueError("MAILBOXES environment variable must be a non-empty JSON array")

        self._msal_app = None
        self.client = httpx.AsyncClient(headers={"Accept": "application/json"})

    def _get_msal_app(self) -> msal.ConfidentialClientApplication:
        if self._msal_app is None:
            self._msal_app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret,
            )
        return self._msal_app

    async def _get_token(self) -> str:
        app = self._get_msal_app()
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
        raise RuntimeError(
            f"Failed to acquire Graph token: {result.get('error_description', result.get('error', 'unknown'))}"
        )

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self.client.request(method, url, headers=headers, **kwargs)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                await asyncio.sleep(retry_after)
                response = await self.client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            if response.status_code == 204:
                return {"status": "success"}
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Graph API returned {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach Graph API: {str(e)}"}

    async def _get(self, path: str, params: dict = None) -> dict:
        return await self._request("GET", f"{GRAPH_BASE_URL}{path}", params=params)

    async def _post(self, path: str, json_body: dict) -> dict:
        return await self._request("POST", f"{GRAPH_BASE_URL}{path}", json=json_body)

    def _resolve_mailboxes(self, mailbox: str = None) -> list[str]:
        if mailbox:
            return [mailbox]
        return list(self.mailboxes)

    # --- Mail operations ---

    async def list_messages(
        self, mailbox: str = None, folder: str = "inbox", limit: int = 10, unread_only: bool = False
    ) -> dict:
        mailboxes = self._resolve_mailboxes(mailbox)

        async def fetch(mb: str):
            params = {
                "$top": limit,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
            }
            if unread_only:
                params["$filter"] = "isRead eq false"
            data = await self._get(f"/users/{mb}/mailFolders/{folder}/messages", params)
            if "error" in data:
                return {"mailbox": mb, "error": data["error"]}
            messages = data.get("value", [])
            for msg in messages:
                msg["mailbox"] = mb
            return {"mailbox": mb, "messages": messages}

        results = await asyncio.gather(*[fetch(mb) for mb in mailboxes])
        if len(mailboxes) == 1:
            return results[0]

        all_messages = []
        errors = []
        for r in results:
            if "error" in r:
                errors.append(r)
            else:
                all_messages.extend(r.get("messages", []))
        all_messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
        result = {"messages": all_messages[:limit]}
        if errors:
            result["errors"] = errors
        return result

    async def get_message(self, email_id: str, mailbox: str) -> dict:
        return await self._get(
            f"/users/{mailbox}/messages/{email_id}",
            params={"$select": "id,subject,from,toRecipients,ccRecipients,body,receivedDateTime,isRead,hasAttachments"},
        )

    async def search_messages(self, query: str, mailbox: str = None, limit: int = 10) -> dict:
        mailboxes = self._resolve_mailboxes(mailbox)

        async def search(mb: str):
            params = {
                "$search": f'"{query}"',
                "$top": limit,
                "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
            }
            data = await self._get(f"/users/{mb}/messages", params)
            if "error" in data:
                return {"mailbox": mb, "error": data["error"]}
            messages = data.get("value", [])
            for msg in messages:
                msg["mailbox"] = mb
            return {"mailbox": mb, "messages": messages}

        results = await asyncio.gather(*[search(mb) for mb in mailboxes])
        if len(mailboxes) == 1:
            return results[0]

        all_messages = []
        errors = []
        for r in results:
            if "error" in r:
                errors.append(r)
            else:
                all_messages.extend(r.get("messages", []))
        all_messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
        result = {"messages": all_messages[:limit]}
        if errors:
            result["errors"] = errors
        return result

    async def send_message(
        self, from_mailbox: str, to: str, subject: str, body: str, cc: str = None
    ) -> dict:
        if from_mailbox not in self.mailboxes:
            return {"error": f"Mailbox '{from_mailbox}' is not in the allowed MAILBOXES list"}

        to_recipients = [{"emailAddress": {"address": addr.strip()}} for addr in to.split(",")]
        message = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": to_recipients,
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr.strip()}} for addr in cc.split(",")
            ]
        return await self._post(f"/users/{from_mailbox}/sendMail", {"message": message})

    async def list_folders(self, mailbox: str = None) -> dict:
        mb = mailbox or self.mailboxes[0]
        return await self._get(
            f"/users/{mb}/mailFolders",
            params={"$select": "id,displayName,totalItemCount,unreadItemCount"},
        )

    async def move_message(self, email_id: str, folder_name: str, mailbox: str) -> dict:
        folders = await self.list_folders(mailbox)
        if "error" in folders:
            return folders
        folder_list = folders.get("value", [])
        target = next((f for f in folder_list if f["displayName"].lower() == folder_name.lower()), None)
        if not target:
            available = [f["displayName"] for f in folder_list]
            return {"error": f"Folder '{folder_name}' not found. Available: {available}"}
        return await self._post(
            f"/users/{mailbox}/messages/{email_id}/move",
            {"destinationId": target["id"]},
        )

    async def get_stats(self, mailbox: str = None) -> dict:
        mailboxes = self._resolve_mailboxes(mailbox)

        async def stats_for(mb: str):
            folders = await self.list_folders(mb)
            if "error" in folders:
                return {"mailbox": mb, "error": folders["error"]}
            folder_stats = [
                {
                    "folder": f["displayName"],
                    "total": f.get("totalItemCount", 0),
                    "unread": f.get("unreadItemCount", 0),
                }
                for f in folders.get("value", [])
            ]
            return {"mailbox": mb, "folders": folder_stats}

        results = await asyncio.gather(*[stats_for(mb) for mb in mailboxes])
        if len(mailboxes) == 1:
            return results[0]
        return {"stats": list(results)}

    async def health_check(self) -> dict:
        try:
            token = await self._get_token()
            response = await self.client.get(
                f"{GRAPH_BASE_URL}/users/{self.mailboxes[0]}/mailFolders/inbox",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id"},
            )
            response.raise_for_status()
            return {"status": "ok", "graph_api": "reachable"}
        except Exception as e:
            return {"status": "degraded", "graph_api": str(e)}

    async def close(self):
        await self.client.aclose()
