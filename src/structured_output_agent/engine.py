from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .llm import LLM

T = TypeVar("T", bound=BaseModel)


class OutputValidationError(Exception):
    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__(
            "Model output failed validation after retries: " + "; ".join(failures)
        )


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T
    attempts: int
    validation_failures: int
    elapsed_ms: float


@dataclass(frozen=True)
class ValidationEvent:
    attempt: int
    success: bool
    error_type: str | None
    elapsed_ms: float


def _json_body(raw: str) -> str:
    match = re.fullmatch(r"\s*```(?:json)?\s*([\s\S]*?)\s*```\s*", raw, re.IGNORECASE)
    return match.group(1) if match else raw


def validate_tool_response(raw: str, schema: type[T]) -> T:
    """Validate an untrusted tool's JSON response with the same schema boundary."""
    try:
        return schema.model_validate_json(_json_body(raw), strict=True)
    except (ValidationError, ValueError) as exc:
        raise OutputValidationError([str(exc)[:500]]) from exc


class StructuredOutputAgent(Generic[T]):
    def __init__(
        self,
        llm: LLM,
        schema: type[T],
        *,
        max_retries: int = 2,
        max_output_chars: int = 100_000,
        event_sink: Callable[[ValidationEvent], None] | None = None,
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        if max_output_chars < 100:
            raise ValueError("max_output_chars must be at least 100")
        self.llm, self.schema, self.max_retries = llm, schema, max_retries
        self.max_output_chars, self.event_sink = max_output_chars, event_sink

    def run(self, task: str) -> Result[T]:
        started = time.monotonic()
        schema = json.dumps(self.schema.model_json_schema(), separators=(",", ":"))
        messages = [
            {
                "role": "system",
                "content": "Return only one JSON object matching this schema: "
                + schema,
            },
            {"role": "user", "content": task},
        ]
        failures: list[str] = []
        for attempt in range(self.max_retries + 1):
            raw = self.llm.complete(messages)
            try:
                if len(raw) > self.max_output_chars:
                    raise ValueError("model output exceeds max_output_chars")
                value = self.schema.model_validate_json(_json_body(raw), strict=True)
                if self.event_sink:
                    self.event_sink(
                        ValidationEvent(
                            attempt + 1, True, None, (time.monotonic() - started) * 1000
                        )
                    )
                return Result(
                    value,
                    attempt + 1,
                    len(failures),
                    (time.monotonic() - started) * 1000,
                )
            except (ValidationError, ValueError) as exc:
                reason = str(exc)[:500]
                failures.append(reason)
                if self.event_sink:
                    self.event_sink(
                        ValidationEvent(
                            attempt + 1,
                            False,
                            type(exc).__name__,
                            (time.monotonic() - started) * 1000,
                        )
                    )
                messages.extend(
                    [
                        {"role": "assistant", "content": raw[:4000]},
                        {
                            "role": "user",
                            "content": "Validation failed: "
                            + reason
                            + ". Return corrected JSON only.",
                        },
                    ]
                )
        raise OutputValidationError(failures)
