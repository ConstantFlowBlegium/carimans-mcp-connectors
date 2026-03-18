import os
import re
import base64
import asyncio
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

load_dotenv()

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/{email}"
BODY_TRUNCATE_LIMIT = 8000


class GmailClient:
    def __init__(self):
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
        self.target_email = os.getenv("TARGET_EMAIL", "me")

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
        self._label_cache: dict[str, str] = {}  # name -> id
        self.http = httpx.AsyncClient(timeout=30.0)

    @property
    def _base(self) -> str:
        return GMAIL_BASE_URL.format(email=self.target_email)

    # ── Token management ────────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing synchronously in a thread if needed."""
        if not self.creds.valid:
            async with self._token_lock:
                if not self.creds.valid:
                    await asyncio.to_thread(self.creds.refresh, Request())
        return self.creds.token

    # ── Low-level HTTP helpers ───────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None) -> dict:
        token = await self._ensure_token()
        try:
            response = await self.http.get(
                f"{self._base}/{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Gmail API returned {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach Gmail API: {str(e)}"}

    async def _post(self, path: str, json: dict = None, params: dict = None) -> dict:
        token = await self._ensure_token()
        try:
            response = await self.http.post(
                f"{self._base}/{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json or {},
                params=params or {},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Gmail API returned {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"Could not reach Gmail API: {str(e)}"}

    # ── Label helpers ────────────────────────────────────────────────────────

    async def _get_labels(self) -> dict:
        """Fetch and cache label name -> id mapping."""
        if self._label_cache:
            return self._label_cache
        data = await self._get("labels")
        if "error" in data:
            return {}
        for lbl in data.get("labels", []):
            self._label_cache[lbl["name"].upper()] = lbl["id"]
            self._label_cache[lbl["id"]] = lbl["id"]  # id resolves to itself
        return self._label_cache

    async def _resolve_label_id(self, label: str) -> str:
        """Return Gmail label ID for a given label name or ID."""
        cache = await self._get_labels()
        # Try exact match first (system labels like INBOX are uppercase)
        upper = label.upper()
        if upper in cache:
            return cache[upper]
        # Try original case
        if label in cache:
            return cache[label]
        # Assume it's already an ID
        return label

    # ── Body extraction ──────────────────────────────────────────────────────

    @staticmethod
    def _decode_b64(data: str) -> str:
        """Decode base64url-encoded string to text."""
        padded = data.replace("-", "+").replace("_", "/")
        padded += "=" * (4 - len(padded) % 4)
        try:
            return base64.b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        """Strip HTML tags and decode common entities."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_body(self, payload: dict) -> tuple[str, list[dict]]:
        """
        Recursively extract plain-text body and attachment metadata from a Gmail message payload.
        Returns (body_text, attachments).
        """
        plain_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[dict] = []

        self._walk_parts(payload, plain_parts, html_parts, attachments)

        if plain_parts:
            body = "\n".join(plain_parts)
        elif html_parts:
            body = self._strip_html("\n".join(html_parts))
        else:
            body = ""

        if len(body) > BODY_TRUNCATE_LIMIT:
            body = body[:BODY_TRUNCATE_LIMIT] + f"\n\n[... truncated — {len(body)} chars total]"

        return body, attachments

    def _walk_parts(
        self,
        part: dict,
        plain: list,
        html: list,
        attachments: list,
    ) -> None:
        mime = part.get("mimeType", "")
        body_data = part.get("body", {})
        filename = part.get("filename", "")

        # Attachment (has filename and/or attachmentId)
        if filename or body_data.get("attachmentId"):
            attachments.append({
                "filename": filename or "(unnamed)",
                "mimeType": mime,
                "size": body_data.get("size", 0),
            })
            return

        if mime == "text/plain":
            raw = body_data.get("data", "")
            if raw:
                plain.append(self._decode_b64(raw))

        elif mime == "text/html":
            raw = body_data.get("data", "")
            if raw:
                html.append(self._decode_b64(raw))

        elif mime.startswith("multipart/"):
            for sub in part.get("parts", []):
                self._walk_parts(sub, plain, html, attachments)

    # ── Message formatting ───────────────────────────────────────────────────

    @staticmethod
    def _header(headers: list[dict], name: str) -> str:
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    def _fmt_message_summary(self, msg: dict) -> dict:
        headers = msg.get("payload", {}).get("headers", [])
        return {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "subject": self._header(headers, "subject") or "(no subject)",
            "from": self._header(headers, "from"),
            "date": self._header(headers, "date"),
            "snippet": msg.get("snippet", ""),
            "labels": msg.get("labelIds", []),
            "webLink": f"https://mail.google.com/mail/u/0/#inbox/{msg.get('id')}",
        }

    def _fmt_message_full(self, msg: dict) -> dict:
        headers = msg.get("payload", {}).get("headers", [])
        body, attachments = self._extract_body(msg.get("payload", {}))
        return {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "subject": self._header(headers, "subject") or "(no subject)",
            "from": self._header(headers, "from"),
            "to": self._header(headers, "to"),
            "cc": self._header(headers, "cc"),
            "bcc": self._header(headers, "bcc"),
            "date": self._header(headers, "date"),
            "labels": msg.get("labelIds", []),
            "body": body,
            "attachments": attachments,
            "webLink": f"https://mail.google.com/mail/u/0/#inbox/{msg.get('id')}",
        }

    # ── Tool implementations ─────────────────────────────────────────────────

    async def list_emails(
        self,
        label: str = "INBOX",
        limit: int = 10,
        unread_only: bool = False,
        include_spam_trash: bool = False,
    ) -> dict:
        label_id = await self._resolve_label_id(label)
        params: dict = {
            "labelIds": label_id,
            "maxResults": min(limit, 500),
            "includeSpamTrash": include_spam_trash,
        }
        if unread_only:
            params["q"] = "is:unread"

        data = await self._get("messages", params)
        if "error" in data:
            return data

        messages = data.get("messages", [])
        if not messages:
            return {"label": label, "emails": [], "count": 0}

        # Fetch message details in parallel (summary format)
        tasks = [self._get(f"messages/{m['id']}", {"format": "metadata",
                  "metadataHeaders": "subject,from,date"}) for m in messages]
        details = await asyncio.gather(*tasks)

        emails = [self._fmt_message_summary(d) for d in details if "error" not in d]
        return {"label": label, "emails": emails, "count": len(emails)}

    async def get_email(self, email_id: str) -> dict:
        data = await self._get(f"messages/{email_id}", {"format": "full"})
        if "error" in data:
            return data
        return self._fmt_message_full(data)

    async def search_emails(self, query: str, limit: int = 10) -> dict:
        params = {
            "q": query,
            "maxResults": min(limit, 500),
        }
        data = await self._get("messages", params)
        if "error" in data:
            return data

        messages = data.get("messages", [])
        if not messages:
            return {"query": query, "emails": [], "count": 0}

        tasks = [self._get(f"messages/{m['id']}", {"format": "metadata",
                  "metadataHeaders": "subject,from,date"}) for m in messages]
        details = await asyncio.gather(*tasks)

        emails = [self._fmt_message_summary(d) for d in details if "error" not in d]
        return {"query": query, "emails": emails, "count": len(emails)}

    async def get_thread(self, thread_id: str) -> dict:
        data = await self._get(f"threads/{thread_id}", {"format": "full"})
        if "error" in data:
            return data

        messages = [self._fmt_message_full(m) for m in data.get("messages", [])]
        return {
            "thread_id": thread_id,
            "message_count": len(messages),
            "messages": messages,
        }

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = None,
        bcc: str = None,
        reply_to_thread_id: str = None,
    ) -> dict:
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to
        msg["From"] = self.target_email
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        payload: dict = {"raw": raw}
        if reply_to_thread_id:
            payload["threadId"] = reply_to_thread_id

        result = await self._post("messages/send", json=payload)
        if "error" in result:
            return result
        return {
            "sent": True,
            "id": result.get("id"),
            "threadId": result.get("threadId"),
        }

    async def list_labels(self) -> dict:
        data = await self._get("labels")
        if "error" in data:
            return data

        labels = []
        for lbl in data.get("labels", []):
            labels.append({
                "id": lbl.get("id"),
                "name": lbl.get("name"),
                "type": lbl.get("type"),
                "messagesTotal": lbl.get("messagesTotal"),
                "messagesUnread": lbl.get("messagesUnread"),
            })

        system = [l for l in labels if l["type"] == "system"]
        user = [l for l in labels if l["type"] == "user"]
        return {"system_labels": system, "user_labels": user, "total": len(labels)}

    async def get_email_stats(self) -> dict:
        # Fetch profile + all labels in parallel
        profile_task = self._get("profile")
        labels_task = self._get("labels")
        profile, labels_data = await asyncio.gather(profile_task, labels_task)

        if "error" in profile:
            return profile

        stats = {
            "email": self.target_email,
            "total_messages": profile.get("messagesTotal", 0),
            "total_threads": profile.get("threadsTotal", 0),
            "unread_per_label": {},
        }

        if "error" not in labels_data:
            for lbl in labels_data.get("labels", []):
                unread = lbl.get("messagesUnread", 0)
                if unread and unread > 0:
                    stats["unread_per_label"][lbl["name"]] = unread

        return stats

    async def mark_as_read(self, email_ids: list[str]) -> dict:
        tasks = [
            self._post(f"messages/{eid}/modify", json={"removeLabelIds": ["UNREAD"]})
            for eid in email_ids
        ]
        results = await asyncio.gather(*tasks)
        errors = [r for r in results if "error" in r]
        return {
            "marked_read": len(email_ids) - len(errors),
            "errors": errors if errors else None,
        }

    async def move_email(
        self,
        email_id: str,
        add_label: str,
        remove_inbox: bool = False,
    ) -> dict:
        add_label_id = await self._resolve_label_id(add_label)
        payload: dict = {"addLabelIds": [add_label_id]}
        if remove_inbox:
            payload["removeLabelIds"] = ["INBOX"]

        result = await self._post(f"messages/{email_id}/modify", json=payload)
        if "error" in result:
            return result
        return {
            "moved": True,
            "id": email_id,
            "labels": result.get("labelIds", []),
        }

    async def health_check(self) -> dict:
        try:
            await asyncio.to_thread(self.creds.refresh, Request())
            data = await self._get("profile")
            if "error" in data:
                return {"status": "degraded", "gmail_api": data["error"]}
            return {
                "status": "ok",
                "gmail_api": "reachable",
                "email": data.get("emailAddress"),
                "total_messages": data.get("messagesTotal"),
            }
        except Exception as e:
            return {"status": "degraded", "gmail_api": str(e)}

    async def close(self):
        await self.http.aclose()
