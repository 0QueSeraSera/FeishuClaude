"""Feishu bot adapter with long-connection support."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger("feishu_claude")

DEFAULT_API_BASE = "https://open.feishu.cn/open-apis"


@dataclass
class FeishuMessage:
    """Incoming message from Feishu."""

    chat_id: str
    sender_id: str
    content: str
    message_type: str = "text"
    chat_type: str = "p2p"  # p2p or group
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeishuConfig:
    """Feishu adapter configuration."""

    app_id: str
    app_secret: str
    verification_token: str | None = None
    allow_user_ids: set[str] = field(default_factory=set)
    allow_group_chats: bool = True
    connection_mode: str = "long_connection"
    dedup_cache_size: int = 1024

    @classmethod
    def from_settings(cls, settings: Any) -> FeishuConfig:
        """Create config from Settings object."""
        return cls(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            verification_token=settings.feishu_verification_token or None,
            allow_user_ids=settings.allowed_user_ids,
            allow_group_chats=settings.feishu_allow_group_chats,
            connection_mode=settings.feishu_connection_mode,
        )


class FeishuAdapter:
    """
    Feishu adapter supporting long-connection (WebSocket) mode.

    Handles:
    - Receiving messages via WebSocket
    - Sending messages via HTTP API
    - Message deduplication
    - User/group access control
    """

    def __init__(
        self,
        config: FeishuConfig,
        *,
        api_base: str = DEFAULT_API_BASE,
        http_timeout_sec: float = 10.0,
    ):
        self.config = config
        self.api_base = api_base.rstrip("/")
        self.http_timeout_sec = http_timeout_sec

        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()

        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._access_token_expire_monotonic = 0.0
        self._token_lock = asyncio.Lock()

        # Message deduplication
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._latest_message_id_by_chat: OrderedDict[str, str] = OrderedDict()

        # Message handler callback
        self._on_message: Callable[[FeishuMessage], None] | None = None

    def set_message_handler(self, handler: Callable[[FeishuMessage], None]) -> None:
        """Set callback for incoming messages."""
        self._on_message = handler

    def validate_config(self) -> list[str]:
        """Validate configuration. Returns list of errors."""
        errors: list[str] = []
        if not self.config.app_id:
            errors.append("FEISHU_APP_ID is required")
        if not self.config.app_secret:
            errors.append("FEISHU_APP_SECRET is required")
        if self.config.connection_mode == "webhook":
            errors.append(
                "FEISHU_CONNECTION_MODE=webhook is not implemented yet; "
                "use FEISHU_CONNECTION_MODE=long_connection"
            )
        elif self.config.connection_mode != "long_connection":
            errors.append(
                "FEISHU_CONNECTION_MODE must be long_connection (webhook not implemented)"
            )
        return errors

    async def start(self) -> None:
        """Start the adapter."""
        errors = self.validate_config()
        if errors:
            raise ValueError("; ".join(errors))

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._client = httpx.AsyncClient(timeout=self.http_timeout_sec)
        self._start_long_connection()

        logger.info(f"Feishu adapter started (mode: {self.config.connection_mode})")

    async def stop(self) -> None:
        """Stop the adapter."""
        self._running = False
        self._ws_stop.set()

        if self._ws_thread is not None:
            self._ws_thread.join(timeout=0.5)
            self._ws_thread = None

        self._ws_client = None
        self._loop = None

        if self._client is not None:
            await self._client.aclose()
            self._client = None

        logger.info("Feishu adapter stopped")

    async def send_message(self, chat_id: str, content: str) -> bool:
        """Send a text message to a Feishu chat.

        Args:
            chat_id: Target Feishu chat ID.
            content: Text content to send.

        Returns:
            True when any delivery path succeeds, otherwise False.
        """
        if self._client is None:
            logger.error("Client not initialized")
            return False

        try:
            token = await self._get_tenant_access_token()

            if await self._send_chat_message(chat_id, content, token):
                return True

            message_id = self._latest_message_id_by_chat.get(chat_id)
            if not message_id:
                logger.error(
                    "Feishu send failed and no message_id fallback found for chat_id=%s",
                    chat_id,
                )
                return False

            logger.warning(
                (
                    "Feishu chat send failed for chat_id=%s, "
                    "retrying with reply fallback message_id=%s"
                ),
                chat_id,
                message_id,
            )
            return await self._send_reply_message(message_id, content, token)

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def _send_chat_message(self, chat_id: str, content: str, token: str) -> bool:
        """Send a message using `chat_id` as receive target.

        Args:
            chat_id: Target Feishu chat ID.
            content: Text content to send.
            token: Tenant access token.

        Returns:
            True if Feishu returns a success code.
        """
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}, ensure_ascii=False),
        }
        url = f"{self.api_base}/im/v1/messages?receive_id_type=chat_id"
        return await self._post_message_request(
            url=url,
            payload=payload,
            token=token,
            target=f"chat:{chat_id}",
        )

    async def _send_reply_message(self, message_id: str, content: str, token: str) -> bool:
        """Reply to an inbound message by `message_id`.

        Args:
            message_id: Source message ID for reply routing.
            content: Text content to send.
            token: Tenant access token.

        Returns:
            True if Feishu returns a success code.
        """
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": content}, ensure_ascii=False),
        }
        url = f"{self.api_base}/im/v1/messages/{message_id}/reply"
        return await self._post_message_request(
            url=url,
            payload=payload,
            token=token,
            target=f"reply:{message_id}",
        )

    async def _post_message_request(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        token: str,
        target: str,
    ) -> bool:
        """Send one Feishu message HTTP request.

        Args:
            url: Request URL.
            payload: JSON payload body.
            token: Tenant access token.
            target: Log label for target route.

        Returns:
            True when Feishu code equals zero.
        """
        if self._client is None:
            raise RuntimeError("HTTP client not initialized")

        response = await self._client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            logger.error(
                "Feishu send failed target=%s code=%s msg=%s",
                target,
                data.get("code"),
                data.get("msg"),
            )
            return False

        return True

    def _start_long_connection(self) -> None:
        """Start WebSocket long-connection."""
        import_started = time.monotonic()
        logger.info("Initializing Feishu long-connection SDK...")
        try:
            import lark_oapi as lark
        except ImportError as e:
            raise ImportError(
                "lark-oapi is required for long_connection mode. "
                "Install with: pip install lark-oapi"
            ) from e
        logger.info(
            "Feishu long-connection SDK initialized in %.1fs",
            time.monotonic() - import_started,
        )

        builder = lark.EventDispatcherHandler.builder("", self.config.verification_token or "")
        register = getattr(builder, "register_p2_im_message_receive_v1", None)

        if not callable(register):
            raise RuntimeError("lark-oapi SDK does not support message receive event dispatch")

        event_handler = register(self._on_ws_message_sync).build()
        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        self._ws_stop.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
            name="feishu-ws",
        )
        self._ws_thread.start()
        logger.info("WebSocket long-connection started")

    def _run_ws_forever(self) -> None:
        """Run WebSocket client in background thread."""
        import asyncio

        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)

        try:
            # Patch lark-oapi's event loop
            import importlib

            ws_client_module = importlib.import_module("lark_oapi.ws.client")
            ws_client_module.loop = ws_loop
        except Exception:
            logger.warning("Failed to patch lark websocket event loop")

        try:
            while self._running and not self._ws_stop.is_set():
                try:
                    self._ws_client.start()
                except Exception as err:
                    if not self._running or self._ws_stop.is_set():
                        break
                    logger.warning(f"WebSocket connection dropped: {err}")
                    self._ws_stop.wait(timeout=3.0)
        finally:
            ws_loop.close()

    def _on_ws_message_sync(self, data: Any) -> None:
        """Handle WebSocket message (sync callback)."""
        if self._loop is None or not self._loop.is_running():
            return

        future = asyncio.run_coroutine_threadsafe(
            self._handle_ws_message(data), self._loop
        )
        future.add_done_callback(self._log_future_error)

    async def _handle_ws_message(self, data: Any) -> None:
        """Process incoming WebSocket message."""
        event = _obj_get(data, "event")
        message = _obj_get(event, "message")

        if message is None:
            return

        # Deduplicate
        message_id = _str_or_none(_obj_get(message, "message_id"))
        if message_id and self._seen_before(message_id):
            return

        # Skip bot messages
        sender = _obj_get(event, "sender")
        sender_type = (_str_or_none(_obj_get(sender, "sender_type")) or "").lower()
        if sender_type == "bot":
            return

        # Check user allowlist
        sender_ids = _extract_sender_ids(event)
        sender_id = sender_ids[0] if sender_ids else ""

        if self.config.allow_user_ids and not any(
            s in self.config.allow_user_ids for s in sender_ids
        ):
            logger.debug(f"Message from unauthorized user: {sender_id}")
            return

        # Check group chat permission
        chat_type = _str_or_none(_obj_get(message, "chat_type")) or "unknown"
        if chat_type != "p2p" and not self.config.allow_group_chats:
            logger.debug("Group chat messages not allowed")
            return

        # Extract chat ID and content
        chat_id = _str_or_none(_obj_get(message, "chat_id"))
        if not chat_id:
            return
        if message_id:
            self._remember_latest_message_id(chat_id, message_id)

        message_type = (_str_or_none(_obj_get(message, "message_type")) or "text").lower()
        content = _extract_message_text(message_type, _obj_get(message, "content"))

        if not content:
            return

        # Build message object
        feishu_msg = FeishuMessage(
            chat_id=chat_id,
            sender_id=sender_id or "unknown",
            content=content,
            message_type=message_type,
            chat_type=chat_type,
            message_id=message_id,
            metadata={
                "sender_ids": sender_ids,
            },
        )

        # Dispatch to handler
        if self._on_message:
            try:
                result = self._on_message(feishu_msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Message handler error: {e}")

    async def _get_tenant_access_token(self) -> str:
        """Get tenant access token, with caching."""
        now = time.monotonic()
        if self._access_token and now < self._access_token_expire_monotonic - 30:
            return self._access_token

        async with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._access_token_expire_monotonic - 30:
                return self._access_token

            if self._client is None:
                raise RuntimeError("HTTP client not initialized")

            response = await self._client.post(
                f"{self.api_base}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Failed to get tenant token: code={data.get('code')} msg={data.get('msg')}"
                )

            token = data.get("tenant_access_token")
            expire = int(data.get("expire", 7200))

            if not token:
                raise RuntimeError("Token response missing tenant_access_token")

            self._access_token = token
            self._access_token_expire_monotonic = time.monotonic() + max(expire, 60)

            return token

    def _seen_before(self, value: str) -> bool:
        """Check if message was seen before (deduplication)."""
        if not value:
            return False
        if value in self._seen_ids:
            return True
        self._seen_ids[value] = None
        while len(self._seen_ids) > self.config.dedup_cache_size:
            self._seen_ids.popitem(last=False)
        return False

    def _remember_latest_message_id(self, chat_id: str, message_id: str) -> None:
        """Track most recent inbound message ID for per-chat reply fallback.

        Args:
            chat_id: Feishu chat ID.
            message_id: Inbound message ID.
        """
        if not chat_id or not message_id:
            return
        if chat_id in self._latest_message_id_by_chat:
            del self._latest_message_id_by_chat[chat_id]
        self._latest_message_id_by_chat[chat_id] = message_id
        while len(self._latest_message_id_by_chat) > self.config.dedup_cache_size:
            self._latest_message_id_by_chat.popitem(last=False)

    def _log_future_error(self, future: Any) -> None:
        """Log errors from async futures."""
        try:
            future.result()
        except Exception as err:
            logger.error(f"WebSocket message handler error: {err}")


# Helper functions
def _str_or_none(value: Any) -> str | None:
    """Convert to string or None."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _obj_get(container: Any, key: str) -> Any:
    """Get value from dict or object."""
    if isinstance(container, dict):
        return container.get(key)
    return getattr(container, key, None)


def _extract_sender_ids(event: Any) -> list[str]:
    """Extract sender IDs from event."""
    sender = _obj_get(event, "sender")
    sender_id = _obj_get(sender, "sender_id")
    candidates: list[str] = []

    for key in ("open_id", "union_id", "user_id"):
        value = _str_or_none(_obj_get(sender_id, key))
        if value:
            candidates.append(value)

    return list(dict.fromkeys(candidates))


def _extract_message_text(message_type: str, raw_content: Any) -> str:
    """Extract text content from message."""
    if isinstance(raw_content, str):
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            content = {"text": raw_content}
    elif isinstance(raw_content, dict):
        content = raw_content
    else:
        content = {}

    if message_type == "text":
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""

    if message_type == "post":
        return _extract_post_text(content)

    if message_type in {"image", "audio", "media", "file", "sticker"}:
        return f"[{message_type}]"

    return ""


def _extract_post_text(content: dict) -> str:
    """Extract text from rich post message."""
    def extract_block(data: dict) -> list[list[dict]]:
        if isinstance(data.get("content"), list):
            return [row for row in data["content"] if isinstance(row, list)]
        return []

    if "content" in content:
        rows = extract_block(content)
    else:
        post = content.get("post", {})
        if isinstance(post, dict):
            source = next((v for v in post.values() if isinstance(v, dict)), {})
        else:
            source = next((v for v in content.values() if isinstance(v, dict)), {})
        rows = extract_block(source) if isinstance(source, dict) else []

    parts: list[str] = []
    for row in rows:
        for item in row:
            if not isinstance(item, dict):
                continue
            tag = _str_or_none(item.get("tag")) or ""
            if tag in {"text", "a"}:
                text = _str_or_none(item.get("text"))
                if text:
                    parts.append(text)
            elif tag == "at":
                name = _str_or_none(item.get("user_name")) or "user"
                parts.append(f"@{name}")

    return " ".join(parts).strip()
