"""Ollama-compatible transport with deterministic archive/fake boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import base64
import json
import os
import time
from collections.abc import Callable, Mapping
from math import isfinite
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..contracts.canonical import canonical_json, sha256_bytes


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 2
    backoff_seconds: tuple[float, ...] = (2.0, 10.0)

    def __post_init__(self) -> None:
        if self.max_retries < 0 or any(delay < 0 for delay in self.backoff_seconds):
            raise ValueError("retry policy values must be non-negative")
        if self.max_retries and len(self.backoff_seconds) < self.max_retries:
            raise ValueError("backoff_seconds must cover every retry")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    prompt: str
    settings: dict[str, object]

    def body(self) -> bytes:
        return canonical_json(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": self.prompt}],
                "stream": False,
                "options": self.settings,
            }
        )

    @property
    def request_hash(self) -> str:
        return sha256_bytes(self.body())


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    request_hash: str
    response_hash: str | None
    http_status: int | None
    response_text: str | None
    response_model: str | None
    finish_reason: str | None
    usage: dict[str, int | None]
    attempts: int
    partial: bool
    error: str | None = None
    error_detail: str | None = None
    request_body: bytes | None = None
    response_body: bytes | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    elapsed_seconds: float | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.response_text is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "http_status": self.http_status,
            "response_text": self.response_text,
            "response_model": self.response_model,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "attempts": self.attempts,
            "partial": self.partial,
            "error": self.error,
            "error_detail": self.error_detail,
            "request_body_b64": _encode_bytes(self.request_body),
            "response_body_b64": _encode_bytes(self.response_body),
            "response_headers": dict(sorted(self.response_headers.items())),
            "elapsed_seconds": self.elapsed_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ProviderResponse":
        """Load both current archives and archives written before raw capture."""
        required = (
            "request_hash", "response_hash", "http_status", "response_text",
            "response_model", "finish_reason", "usage", "attempts", "partial",
        )
        if any(key not in payload for key in required):
            raise ValueError("provider archive response is missing required fields")
        usage = payload["usage"]
        if not isinstance(usage, dict):
            raise ValueError("provider archive usage must be an object")
        if any(
            not isinstance(key, str)
            or value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            )
            for key, value in usage.items()
        ):
            raise ValueError("provider archive usage must contain non-negative integers or null")
        headers = payload.get("response_headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        ):
            raise ValueError("provider archive response_headers must be a string map")
        attempts = payload["attempts"]
        partial = payload["partial"]
        request_hash = payload["request_hash"]
        if not isinstance(request_hash, str) or not request_hash:
            raise ValueError("provider archive request_hash must be a non-empty string")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            raise ValueError("provider archive attempts must be a non-negative integer")
        if not isinstance(partial, bool):
            raise ValueError("provider archive partial must be boolean")
        elapsed = payload.get("elapsed_seconds")
        if elapsed is not None and (
            not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
            or not isfinite(float(elapsed)) or elapsed < 0
        ):
            raise ValueError("provider archive elapsed_seconds must be finite and non-negative")
        request_body = _decode_bytes(payload.get("request_body_b64"))
        response_body = _decode_bytes(payload.get("response_body_b64"))
        response_hash = payload["response_hash"] if isinstance(payload["response_hash"], str) else None
        if request_body is not None and sha256_bytes(request_body) != request_hash:
            raise ValueError("provider archive request body hash mismatch")
        if response_body is not None:
            if response_hash is None or sha256_bytes(response_body) != response_hash:
                raise ValueError("provider archive response body hash mismatch")
        return cls(
            request_hash=request_hash,
            response_hash=response_hash,
            http_status=payload["http_status"] if isinstance(payload["http_status"], int) else None,
            response_text=payload["response_text"] if isinstance(payload["response_text"], str) else None,
            response_model=payload["response_model"] if isinstance(payload["response_model"], str) else None,
            finish_reason=payload["finish_reason"] if isinstance(payload["finish_reason"], str) else None,
            usage=usage,
            attempts=attempts,
            partial=partial,
            error=payload["error"] if isinstance(payload.get("error"), str) else None,
            error_detail=payload["error_detail"] if isinstance(payload.get("error_detail"), str) else None,
            request_body=request_body,
            response_body=response_body,
            response_headers=dict(headers),
            elapsed_seconds=float(elapsed) if elapsed is not None else None,
        )


Sender = Callable[[str, bytes, float], TransportResponse]

OLLAMA_CLOUD_CHAT_ENDPOINT = "https://ollama.com/api/chat"


class OllamaClient:
    """One-candidate transport; retries happen only for transport/server errors."""

    def __init__(
        self,
        endpoint: str = OLLAMA_CLOUD_CHAT_ENDPOINT,
        *,
        request_timeout_seconds: float = 180.0,
        retry_policy: RetryPolicy | None = None,
        sender: Sender | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        api_key: str | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self.endpoint = endpoint
        self.request_timeout_seconds = request_timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy()
        self._sender = sender or self._http_sender
        self._sleeper = sleeper
        self._api_key = api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY")
        if sender is None and endpoint != OLLAMA_CLOUD_CHAT_ENDPOINT:
            raise ValueError(
                "Ollama Cloud transport requires the canonical endpoint "
                f"{OLLAMA_CLOUD_CHAT_ENDPOINT}"
            )
        if sender is None and not self._api_key:
            raise ValueError("OLLAMA_API_KEY is required for Ollama Cloud requests")

    def propose(
        self,
        request: ProviderRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
        campaign_deadline_seconds: float | None = None,
    ) -> ProviderResponse:
        if not request.model or not isinstance(request.prompt, str):
            raise ValueError("provider request requires model and prompt")
        if campaign_deadline_seconds is not None and campaign_deadline_seconds <= 0:
            raise ValueError("campaign_deadline_seconds must be positive")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("cancelled must be callable")
        body = request.body()
        attempts = 0
        last_status: int | None = None
        last_detail: str | None = None
        last_response: TransportResponse | None = None
        started = time.monotonic()
        for retry_index in range(self.retry_policy.max_retries + 1):
            control_reason = self._control_reason(
                started,
                cancelled=cancelled,
                campaign_deadline_seconds=campaign_deadline_seconds,
            )
            if control_reason is not None:
                return self._failure(
                    request,
                    attempts,
                    control_reason,
                    control_reason,
                    response=last_response,
                    elapsed_seconds=time.monotonic() - started,
                )
            attempts += 1
            timeout = self.request_timeout_seconds
            if campaign_deadline_seconds is not None:
                remaining = campaign_deadline_seconds - (time.monotonic() - started)
                timeout = min(timeout, max(0.001, remaining))
            try:
                response = self._sender(self.endpoint, body, timeout)
            except (TimeoutError, URLError, OSError) as error:
                last_detail = str(error)
                if retry_index < self.retry_policy.max_retries:
                    control_reason = self._controlled_sleep(
                        self.retry_policy.backoff_seconds[retry_index],
                        started,
                        cancelled=cancelled,
                        campaign_deadline_seconds=campaign_deadline_seconds,
                    )
                    if control_reason is not None:
                        return self._failure(
                            request,
                            attempts,
                            control_reason,
                            control_reason,
                            response=last_response,
                            elapsed_seconds=time.monotonic() - started,
                        )
                    continue
                return self._failure(
                    request,
                    attempts,
                    "transport_failure",
                    last_detail,
                    response=last_response,
                    elapsed_seconds=time.monotonic() - started,
                )
            last_status = response.status_code
            last_response = response
            if self._retryable(response.status_code) and retry_index < self.retry_policy.max_retries:
                last_detail = f"HTTP {response.status_code}"
                control_reason = self._controlled_sleep(
                    self.retry_policy.backoff_seconds[retry_index],
                    started,
                    cancelled=cancelled,
                    campaign_deadline_seconds=campaign_deadline_seconds,
                )
                if control_reason is not None:
                    return self._failure(
                        request,
                        attempts,
                        control_reason,
                        control_reason,
                        response=last_response,
                        elapsed_seconds=time.monotonic() - started,
                    )
                continue
            if response.status_code < 200 or response.status_code >= 300:
                return self._failure(
                    request,
                    attempts,
                    "http_failure",
                    f"HTTP {response.status_code}",
                    response=response,
                    elapsed_seconds=time.monotonic() - started,
                )
            return self._decode(request, response, attempts, time.monotonic() - started)
        return self._failure(
            request,
            attempts,
            "transport_failure",
            last_detail or str(last_status),
            response=last_response,
            elapsed_seconds=time.monotonic() - started,
        )

    @staticmethod
    def _control_reason(
        started: float,
        *,
        cancelled: Callable[[], bool] | None,
        campaign_deadline_seconds: float | None,
    ) -> str | None:
        if cancelled is not None:
            try:
                if cancelled():
                    return "cancelled"
            except Exception as error:
                return f"cancellation_error:{error}"
        if (
            campaign_deadline_seconds is not None
            and time.monotonic() - started >= campaign_deadline_seconds
        ):
            return "campaign_deadline"
        return None

    def _controlled_sleep(
        self,
        delay_seconds: float,
        started: float,
        *,
        cancelled: Callable[[], bool] | None,
        campaign_deadline_seconds: float | None,
    ) -> str | None:
        """Back off while retaining campaign cancellation/deadline control."""
        if cancelled is None and campaign_deadline_seconds is None:
            self._sleeper(delay_seconds)
            return None
        remaining = delay_seconds
        while remaining > 0:
            reason = self._control_reason(
                started,
                cancelled=cancelled,
                campaign_deadline_seconds=campaign_deadline_seconds,
            )
            if reason is not None:
                return reason
            sleep_for = min(remaining, 0.05)
            if campaign_deadline_seconds is not None:
                deadline_remaining = campaign_deadline_seconds - (time.monotonic() - started)
                if deadline_remaining <= 0:
                    return "campaign_deadline"
                sleep_for = min(sleep_for, deadline_remaining)
            self._sleeper(sleep_for)
            remaining -= sleep_for
        return self._control_reason(
            started,
            cancelled=cancelled,
            campaign_deadline_seconds=campaign_deadline_seconds,
        )

    @staticmethod
    def _retryable(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599

    def _decode(
        self,
        request: ProviderRequest,
        response: TransportResponse,
        attempts: int,
        elapsed_seconds: float,
    ) -> ProviderResponse:
        response_hash = sha256_bytes(response.body)
        captured = {
            "request_body": request.body(),
            "response_body": response.body,
            "response_headers": dict(response.headers),
            "elapsed_seconds": max(0.0, elapsed_seconds),
        }
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return ProviderResponse(
                request.request_hash, response_hash, response.status_code, None, None, None,
                {"prompt_tokens": None, "generated_tokens": None}, attempts, False,
                "malformed_json", str(error),
                **captured,
            )
        if not isinstance(payload, dict):
            return ProviderResponse(
                request.request_hash, response_hash, response.status_code, None, None, None,
                {"prompt_tokens": None, "generated_tokens": None}, attempts, False,
                "malformed_payload", "response JSON must be an object",
                **captured,
            )
        message = payload.get("message")
        text = message.get("content") if isinstance(message, dict) else payload.get("response")
        if not isinstance(text, str):
            return ProviderResponse(
                request.request_hash, response_hash, response.status_code, None, None, None,
                {"prompt_tokens": None, "generated_tokens": None}, attempts, False,
                "missing_content", "response has no string message.content or response",
                **captured,
            )
        usage = {
            "prompt_tokens": _optional_int(payload.get("prompt_eval_count")),
            "generated_tokens": _optional_int(payload.get("eval_count")),
        }
        finish_reason = payload.get("done_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            finish_reason = None
        return ProviderResponse(
            request.request_hash,
            response_hash,
            response.status_code,
            text,
            payload.get("model") if isinstance(payload.get("model"), str) else None,
            finish_reason,
            usage,
            attempts,
            payload.get("done") is False,
            **captured,
        )

    @staticmethod
    def _failure(
        request: ProviderRequest,
        attempts: int,
        error: str,
        detail: str | None,
        *,
        response: TransportResponse | None = None,
        elapsed_seconds: float | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            request.request_hash,
            sha256_bytes(response.body) if response is not None else None,
            response.status_code if response is not None else None,
            None,
            None,
            None,
            {"prompt_tokens": None, "generated_tokens": None},
            attempts,
            False,
            error,
            detail,
            request.body(),
            response.body if response is not None else None,
            dict(response.headers) if response is not None else {},
            max(0.0, elapsed_seconds) if elapsed_seconds is not None else None,
        )

    def _http_sender(self, endpoint: str, body: bytes, timeout: float) -> TransportResponse:
        if endpoint != OLLAMA_CLOUD_CHAT_ENDPOINT:
            raise ValueError(
                "Ollama Cloud transport requires the canonical endpoint "
                f"{OLLAMA_CLOUD_CHAT_ENDPOINT}"
            )
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return TransportResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            return TransportResponse(error.code, dict(error.headers.items()), error.read())


class ArchiveReplay:
    """Read/write response archives keyed by canonical request hash."""

    def __init__(self, responses: Mapping[str, ProviderResponse] | None = None) -> None:
        self.responses = dict(responses or {})

    def record(self, request: ProviderRequest, response: ProviderResponse) -> None:
        if response.request_hash != request.request_hash:
            raise ValueError("archive request hash mismatch")
        self.responses[request.request_hash] = response

    def replay(self, request: ProviderRequest) -> ProviderResponse:
        response = self.responses.get(request.request_hash)
        if response is None:
            return ProviderResponse(
                request.request_hash, None, None, None, None, None,
                {"prompt_tokens": None, "generated_tokens": None}, 0, False,
                "archive_miss", "request hash is not in the archive",
            )
        return replace(response, attempts=1)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        payload = json.dumps(
            {key: value.as_dict() for key, value in sorted(self.responses.items())},
            sort_keys=True,
            indent=2,
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path: Path) -> "ArchiveReplay":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("provider archive must be an object")
        responses: dict[str, ProviderResponse] = {}
        for key, row in payload.items():
            if not isinstance(row, dict):
                raise ValueError("provider archive entries must be objects")
            response = ProviderResponse.from_dict(row)
            if response.request_hash != key:
                raise ValueError(f"provider archive key mismatch: {key}")
            responses[key] = response
        return cls(responses)


class FakeProviderServer:
    """Queue-based fake sender for transport and retry tests."""

    def __init__(self, responses: list[TransportResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[bytes] = []

    def send(self, _endpoint: str, body: bytes, _timeout: float) -> TransportResponse:
        self.requests.append(body)
        if not self.responses:
            raise RuntimeError("fake server has no response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _encode_bytes(value: bytes | None) -> str | None:
    return base64.b64encode(value).decode("ascii") if value is not None else None


def _decode_bytes(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("provider archive byte fields must be base64 strings")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("provider archive byte field is not valid base64") from error
