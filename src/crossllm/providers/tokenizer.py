"""Explicit tokenizer boundary for protocol token accounting."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..contracts.canonical import sha256_hex


class TokenizationError(ValueError):
    """The selected tokenizer could not produce a valid token sequence."""


@dataclass(frozen=True, slots=True)
class TokenizerIdentity:
    encoding_id: str
    revision: str
    artifact_hash: str

    def __post_init__(self) -> None:
        if not self.encoding_id or not self.revision or not self.artifact_hash:
            raise ValueError("tokenizer identity requires encoding, revision and artifact hash")

    @property
    def identity_hash(self) -> str:
        return sha256_hex({
            "encoding_id": self.encoding_id,
            "revision": self.revision,
            "artifact_hash": self.artifact_hash,
        })

    def as_dict(self) -> dict[str, str]:
        return {
            "encoding_id": self.encoding_id,
            "revision": self.revision,
            "artifact_hash": self.artifact_hash,
            "identity_hash": self.identity_hash,
        }


@dataclass(frozen=True, slots=True)
class TokenMeasurement:
    tokenizer: TokenizerIdentity
    prompt_tokens: int | None
    generated_tokens: int | None
    missing_field_reasons: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "tokenizer": self.tokenizer.as_dict(),
            "prompt_tokens": self.prompt_tokens,
            "generated_tokens": self.generated_tokens,
            "missing_field_reasons": dict(self.missing_field_reasons),
        }


Encoder = Callable[[str], Sequence[int]]


class ExactTokenCounter:
    """Count text only with an explicitly supplied, identified encoder.

    No fallback byte/word approximation is provided because it would not be a
    model-native token count and could change cap or cost decisions.
    """

    def __init__(self, identity: TokenizerIdentity, encoder: Encoder) -> None:
        if not callable(encoder):
            raise ValueError("encoder must be callable")
        self.identity = identity
        self._encoder = encoder

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TokenizationError("text must be a string")
        try:
            tokens = self._encoder(text)
        except Exception as error:
            raise TokenizationError(f"encoder_failed:{error}") from error
        if isinstance(tokens, (str, bytes)):
            raise TokenizationError("encoder must return a sequence of token IDs")
        try:
            values = list(tokens)
        except TypeError as error:
            raise TokenizationError("encoder result is not iterable") from error
        if any(not isinstance(token, int) or isinstance(token, bool) or token < 0 for token in values):
            raise TokenizationError("encoder returned invalid token IDs")
        return len(values)

    def measure(self, prompt: str, generated: str | None) -> TokenMeasurement:
        missing: dict[str, str] = {}
        try:
            prompt_tokens = self.count(prompt)
        except TokenizationError as error:
            prompt_tokens = None
            missing["prompt_tokens"] = str(error)
        if generated is None:
            generated_tokens = None
            missing["generated_tokens"] = "generated_text_unavailable"
        else:
            try:
                generated_tokens = self.count(generated)
            except TokenizationError as error:
                generated_tokens = None
                missing["generated_tokens"] = str(error)
        return TokenMeasurement(self.identity, prompt_tokens, generated_tokens, missing)
