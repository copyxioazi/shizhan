"""审批系统适配层。

唯一允许调用 ``/mock-upstream/*`` 的组件；未来可替换为真实审批系统客户端。
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.errors import UpstreamError
from app.status import ErrorCode


class UpstreamClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or settings.upstream_base_url).rstrip("/")
        self.timeout = timeout
        self._client: Any | None = None

    def _get_client(self):
        if self._client is None:
            # 延迟导入，避免仅启动框架时必须安装 httpx。
            import httpx

            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                trust_env=False,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, **kwargs):
        import httpx

        client = self._get_client()
        try:
            response = client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise UpstreamError(
                "上游审批系统不可用",
                code=ErrorCode.UPSTREAM_UNAVAILABLE.value,
                reason=str(exc),
            ) from exc
        return response

    def _data(self, response) -> Any:
        if response.status_code >= 400:
            code = f"HTTP_{response.status_code}"
            message = "上游审批系统返回错误"
            details: dict[str, Any] = {}
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    code = error.get("code") or code
                    message = error.get("message") or message
                    details = error.get("details") or {}
                elif payload.get("code"):
                    code = payload["code"]
                    message = payload.get("message") or message
            # 4xx 是业务语义明确的失败，原样透出；5xx 统一视为上游不可用。
            mapped_status = (
                response.status_code if 400 <= response.status_code < 500 else None
            )
            raise UpstreamError(
                message,
                code=code,
                status_code=mapped_status,
                upstream_status=response.status_code,
                **details,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "上游审批系统返回非 JSON 响应",
                code="UPSTREAM_BAD_RESPONSE",
                upstream_status=response.status_code,
            ) from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") or {}
            raise UpstreamError(
                error.get("message") or "上游审批系统返回失败",
                code=error.get("code") or "UPSTREAM_ERROR",
                upstream_status=response.status_code,
                **(error.get("details") or {}),
            )
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def list_pending(self, limit: int) -> list[dict]:
        response = self._request(
            "GET", "/mock-upstream/approvals/pending", params={"limit": limit}
        )
        return self._data(response)

    def get_approval(self, instance_id: str) -> dict:
        response = self._request("GET", f"/mock-upstream/approvals/{instance_id}")
        return self._data(response)

    def download_attachment(
        self, instance_id: str, attachment_id: int
    ) -> tuple[bytes, str | None, str | None]:
        response = self._request(
            "GET",
            f"/mock-upstream/approvals/{instance_id}/attachments/{attachment_id}/file",
            timeout=30.0,
        )
        if response.status_code >= 400:
            self._data(response)  # 统一抛出 UpstreamError
        return (
            response.content,
            response.headers.get("X-Checksum-SHA256"),
            response.headers.get("Content-Type"),
        )

    def add_comment(
        self, instance_id: str, content: str, idempotency_key: str
    ) -> dict:
        response = self._request(
            "POST",
            f"/mock-upstream/approvals/{instance_id}/comments",
            json={"content": content, "idempotency_key": idempotency_key},
        )
        return self._data(response)

    def list_comments(self, instance_id: str) -> list[dict]:
        response = self._request(
            "GET", f"/mock-upstream/approvals/{instance_id}/comments"
        )
        return self._data(response)


_client: UpstreamClient | None = None


def get_upstream_client() -> UpstreamClient:
    global _client
    if _client is None:
        _client = UpstreamClient()
    return _client


def set_upstream_client(client: UpstreamClient | None) -> None:
    """测试或集成时可替换适配层实例。"""
    global _client
    if _client is not None and _client is not client:
        _client.close()
    _client = client
