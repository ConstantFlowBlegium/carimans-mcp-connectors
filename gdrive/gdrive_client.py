import os
import re
import base64
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

load_dotenv()

DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"

MIME_TYPE_FILTERS = {
    "folder":       "mimeType = 'application/vnd.google-apps.folder'",
    "document":     "mimeType = 'application/vnd.google-apps.document'",
    "spreadsheet":  "mimeType = 'application/vnd.google-apps.spreadsheet'",
    "presentation": "mimeType = 'application/vnd.google-apps.presentation'",
    "pdf":          "mimeType = 'application/pdf'",
    "image":        "mimeType contains 'image/'",
}

GOOGLE_MIME_LABELS = {
    "application/vnd.google-apps.document":     "document",
    "application/vnd.google-apps.spreadsheet":  "spreadsheet",
    "application/vnd.google-apps.presentation": "presentation",
    "application/vnd.google-apps.folder":       "folder",
    "application/pdf":                          "pdf",
}

FILE_FIELDS = "id,name,mimeType,size,createdTime,modifiedTime,webViewLink,parents"


class GDriveClient:
    def __init__(self):
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN "
                "environment variables are required"
            )

        self.creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )

        self._token_lock = asyncio.Lock()
        self._parent_cache: dict[str, str] = {}
        self.http = httpx.AsyncClient(timeout=30.0)

    # ── Token management ────────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing synchronously in a thread if needed."""
        if not self.creds.valid:
            async with self._token_lock:
                # Re-check inside lock to avoid redundant refreshes
                if not self.creds.valid:
                    await asyncio.to_thread(self.creds.refresh, Request())
        return self.creds.token

    # ── Low-level HTTP helpers ───────────────────────────────────────────────

    async def _get(self, url: str, params: dict = None) -> dict:
        token = await self._ensure_token()
        try:
            response = await self.http.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Drive API returned {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach Drive API: {str(e)}"}

    async def _get_bytes(self, url: str, params: dict = None) -> tuple[bytes, str]:
        """Download raw bytes from Drive (for exports and media downloads)."""
        token = await self._ensure_token()
        response = await self.http.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "")

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _parent_name(self, parent_id: str) -> str:
        if not parent_id or parent_id == "root":
            return "My Drive"
        if parent_id in self._parent_cache:
            return self._parent_cache[parent_id]
        data = await self._get(f"{DRIVE_BASE_URL}/files/{parent_id}", {"fields": "name"})
        name = data.get("name", parent_id)
        self._parent_cache[parent_id] = name
        return name

    def _fmt(self, f: dict, parent_name: str = None) -> dict:
        mime = f.get("mimeType", "")
        return {
            "id":           f.get("id"),
            "name":         f.get("name"),
            "type":         GOOGLE_MIME_LABELS.get(mime, "file"),
            "mimeType":     mime,
            "size":         f.get("size"),
            "createdTime":  f.get("createdTime"),
            "modifiedTime": f.get("modifiedTime"),
            "webViewLink":  f.get("webViewLink"),
            "parents":      f.get("parents", []),
            "parentName":   parent_name,
        }

    def _type_filter(self, file_type: str) -> str:
        if not file_type or file_type == "any":
            return ""
        return MIME_TYPE_FILTERS.get(file_type, "")

    @staticmethod
    def _clean_query(q: str) -> str:
        return re.sub(r"['\"\\\n\r\t]", " ", q).strip()

    # ── Tool implementations ─────────────────────────────────────────────────

    async def list_files(
        self, folder_id: str = "root", limit: int = 20, file_type: str = None
    ) -> dict:
        query_parts = [f"'{folder_id}' in parents", "trashed = false"]
        tf = self._type_filter(file_type)
        if tf:
            query_parts.append(tf)

        data = await self._get(
            f"{DRIVE_BASE_URL}/files",
            {
                "q":        " and ".join(query_parts),
                "pageSize": min(limit, 1000),
                "fields":   f"files({FILE_FIELDS})",
                "orderBy":  "folder,name",
            },
        )
        if "error" in data:
            return data

        folder_label = await self._parent_name(folder_id)
        files = [self._fmt(f, folder_label) for f in data.get("files", [])]
        return {"folder": folder_label, "folder_id": folder_id, "files": files, "count": len(files)}

    async def search_files(
        self, query: str, limit: int = 10, file_type: str = None
    ) -> dict:
        clean = self._clean_query(query)
        results = await self._search_raw(clean, limit, file_type)

        # Retry with individual words if no hits
        if not results.get("files") and " " in clean:
            words = [w for w in clean.split() if len(w) > 2]
            for word in words:
                partial = await self._search_raw(word, limit, file_type)
                if partial.get("files"):
                    partial["note"] = f"No results for '{clean}' — showing results for '{word}'"
                    return partial

        return results

    async def _search_raw(self, query: str, limit: int, file_type: str = None) -> dict:
        escaped = query.replace("'", "\\'")
        query_parts = [
            f"(fullText contains '{escaped}' or name contains '{escaped}')",
            "trashed = false",
        ]
        tf = self._type_filter(file_type)
        if tf:
            query_parts.append(tf)

        data = await self._get(
            f"{DRIVE_BASE_URL}/files",
            {
                "q":        " and ".join(query_parts),
                "pageSize": min(limit, 100),
                "fields":   f"files({FILE_FIELDS})",
                "orderBy":  "modifiedTime desc",
            },
        )
        if "error" in data:
            return data

        # Fetch parent names in parallel
        raw_files = data.get("files", [])
        parent_ids = [f["parents"][0] for f in raw_files if f.get("parents")]
        unique_parents = list(set(parent_ids))
        parent_names = await asyncio.gather(*[self._parent_name(p) for p in unique_parents])
        parent_map = dict(zip(unique_parents, parent_names))

        files = []
        for f in raw_files:
            pid = f.get("parents", [None])[0]
            files.append(self._fmt(f, parent_map.get(pid)))

        return {"query": query, "files": files, "count": len(files)}

    async def get_file_metadata(self, file_id: str) -> dict:
        data = await self._get(
            f"{DRIVE_BASE_URL}/files/{file_id}",
            {
                "fields": (
                    "id,name,mimeType,size,owners,createdTime,modifiedTime,"
                    "webViewLink,parents,description,starred"
                )
            },
        )
        if "error" in data:
            return data

        result = self._fmt(data)
        result["owners"] = [o.get("emailAddress") for o in data.get("owners", [])]
        result["description"] = data.get("description")
        result["starred"] = data.get("starred", False)

        if data.get("parents"):
            result["parentName"] = await self._parent_name(data["parents"][0])

        return result

    async def read_file(self, file_id: str) -> dict:
        meta = await self.get_file_metadata(file_id)
        if "error" in meta:
            return meta

        mime = meta.get("mimeType", "")
        name = meta.get("name", file_id)

        # Google Docs → plain text export
        if mime == "application/vnd.google-apps.document":
            try:
                content, _ = await self._get_bytes(
                    f"{DRIVE_BASE_URL}/files/{file_id}/export",
                    {"mimeType": "text/plain"},
                )
                return {"file_id": file_id, "name": name, "type": "document",
                        "content": content.decode("utf-8", errors="replace")}
            except Exception as e:
                return {"error": f"Failed to export document: {e}"}

        # Google Sheets → CSV
        elif mime == "application/vnd.google-apps.spreadsheet":
            try:
                content, _ = await self._get_bytes(
                    f"{DRIVE_BASE_URL}/files/{file_id}/export",
                    {"mimeType": "text/csv"},
                )
                return {"file_id": file_id, "name": name, "type": "spreadsheet",
                        "content": content.decode("utf-8", errors="replace")}
            except Exception as e:
                return {"error": f"Failed to export spreadsheet: {e}"}

        # Google Slides → plain text export
        elif mime == "application/vnd.google-apps.presentation":
            try:
                content, _ = await self._get_bytes(
                    f"{DRIVE_BASE_URL}/files/{file_id}/export",
                    {"mimeType": "text/plain"},
                )
                return {"file_id": file_id, "name": name, "type": "presentation",
                        "content": content.decode("utf-8", errors="replace")}
            except Exception as e:
                return {"error": f"Failed to export presentation: {e}"}

        # PDF → base64
        elif mime == "application/pdf":
            try:
                content, _ = await self._get_bytes(
                    f"{DRIVE_BASE_URL}/files/{file_id}",
                    {"alt": "media"},
                )
                return {
                    "file_id":       file_id,
                    "name":          name,
                    "type":          "pdf",
                    "mime_type":     "application/pdf",
                    "content_base64": base64.b64encode(content).decode("ascii"),
                    "size_bytes":    len(content),
                }
            except Exception as e:
                return {"error": f"Failed to download PDF: {e}"}

        # Plain text / JSON / XML / CSV
        elif mime.startswith("text/") or mime in (
            "application/json", "application/xml", "application/csv"
        ):
            try:
                content, _ = await self._get_bytes(
                    f"{DRIVE_BASE_URL}/files/{file_id}",
                    {"alt": "media"},
                )
                return {"file_id": file_id, "name": name, "type": "text",
                        "content": content.decode("utf-8", errors="replace")}
            except Exception as e:
                return {"error": f"Failed to download file: {e}"}

        # Binary / unsupported
        else:
            return {
                "file_id":     file_id,
                "name":        name,
                "type":        "binary",
                "mime_type":   mime,
                "webViewLink": meta.get("webViewLink"),
                "note":        "Binary file — content cannot be read as text. Use webViewLink to open in browser.",
            }

    async def list_folder_contents(
        self,
        folder_name: str = None,
        folder_id: str = None,
        recursive: bool = False,
    ) -> dict:
        # Resolve folder by name if no ID given
        if not folder_id and folder_name:
            escaped = folder_name.replace("'", "\\'")
            search = await self._get(
                f"{DRIVE_BASE_URL}/files",
                {
                    "q":        (
                        f"name = '{escaped}' "
                        "and mimeType = 'application/vnd.google-apps.folder' "
                        "and trashed = false"
                    ),
                    "fields":   "files(id,name)",
                    "pageSize": 5,
                },
            )
            if "error" in search:
                return search
            matches = search.get("files", [])
            if not matches:
                return {"error": f"Folder '{folder_name}' not found in Drive"}
            folder_id = matches[0]["id"]
            folder_name = matches[0]["name"]

        folder_id = folder_id or "root"
        label = folder_name or (await self._parent_name(folder_id))
        return await self._recurse(folder_id, label, recursive, depth=0)

    async def _recurse(
        self, folder_id: str, folder_name: str, recursive: bool, depth: int
    ) -> dict:
        if depth > 5:
            return {"folder": folder_name, "note": "Max recursion depth (5) reached"}

        data = await self.list_files(folder_id, limit=200)
        if "error" in data:
            return data

        result: dict = {
            "folder":    folder_name,
            "folder_id": folder_id,
            "items":     data["files"],
            "count":     data["count"],
        }

        if recursive:
            sub_tasks = [
                self._recurse(f["id"], f["name"], recursive, depth + 1)
                for f in data["files"]
                if f.get("mimeType") == "application/vnd.google-apps.folder"
            ]
            if sub_tasks:
                result["subfolders"] = list(await asyncio.gather(*sub_tasks))

        return result

    async def get_recent_files(self, limit: int = 10, days: int = 7) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        data = await self._get(
            f"{DRIVE_BASE_URL}/files",
            {
                "q": (
                    f"modifiedTime > '{cutoff}' "
                    "and trashed = false "
                    "and mimeType != 'application/vnd.google-apps.folder'"
                ),
                "pageSize": min(limit, 100),
                "fields":   f"files({FILE_FIELDS})",
                "orderBy":  "modifiedTime desc",
            },
        )
        if "error" in data:
            return data

        raw_files = data.get("files", [])
        parent_ids = list({f["parents"][0] for f in raw_files if f.get("parents")})
        parent_names = await asyncio.gather(*[self._parent_name(p) for p in parent_ids])
        parent_map = dict(zip(parent_ids, parent_names))

        files = [
            self._fmt(f, parent_map.get((f.get("parents") or [None])[0]))
            for f in raw_files
        ]
        return {"days": days, "since": cutoff, "files": files, "count": len(files)}

    async def get_drive_stats(self) -> dict:
        # Fetch storage quota and type counts in parallel
        about_task = self._get(f"{DRIVE_BASE_URL}/about", {"fields": "storageQuota,user"})
        count_tasks = {
            label: self._count(q)
            for label, q in [
                ("documents",     "mimeType = 'application/vnd.google-apps.document'"),
                ("spreadsheets",  "mimeType = 'application/vnd.google-apps.spreadsheet'"),
                ("presentations", "mimeType = 'application/vnd.google-apps.presentation'"),
                ("pdfs",          "mimeType = 'application/pdf'"),
                ("images",        "mimeType contains 'image/'"),
                ("folders",       "mimeType = 'application/vnd.google-apps.folder'"),
                ("all_files",     "mimeType != 'application/vnd.google-apps.folder'"),
            ]
        }

        about, *count_results = await asyncio.gather(
            about_task, *count_tasks.values()
        )
        counts = dict(zip(count_tasks.keys(), count_results))

        quota = about.get("storageQuota", {}) if "error" not in about else {}
        used = int(quota.get("usage", 0))
        limit = int(quota.get("limit", 0)) if quota.get("limit") else None

        return {
            "user":    about.get("user", {}).get("emailAddress") if "error" not in about else None,
            "storage": {
                "used_bytes": used,
                "used_mb":    round(used / 1024 / 1024, 1),
                "limit_gb":   round(limit / 1024 / 1024 / 1024, 1) if limit else None,
            },
            "file_counts": counts,
            "note": "Counts capped at 1000 per type; values ending in '+' mean more exist.",
        }

    async def _count(self, mime_query: str) -> str:
        """Return file count (as string, possibly with '+' suffix if > 1000)."""
        data = await self._get(
            f"{DRIVE_BASE_URL}/files",
            {
                "q":        f"({mime_query}) and trashed = false",
                "pageSize": 1000,
                "fields":   "nextPageToken,files(id)",
            },
        )
        if "error" in data:
            return "?"
        n = len(data.get("files", []))
        return f"{n}+" if data.get("nextPageToken") else str(n)

    async def health_check(self) -> dict:
        try:
            # Force a token refresh to verify credentials are valid
            await asyncio.to_thread(self.creds.refresh, Request())
            data = await self._get(f"{DRIVE_BASE_URL}/about", {"fields": "user"})
            if "error" in data:
                return {"status": "degraded", "drive_api": data["error"]}
            return {
                "status":    "ok",
                "drive_api": "reachable",
                "user":      data.get("user", {}).get("emailAddress"),
            }
        except Exception as e:
            return {"status": "degraded", "drive_api": str(e)}

    async def close(self):
        await self.http.aclose()
