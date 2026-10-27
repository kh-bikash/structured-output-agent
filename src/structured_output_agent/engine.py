from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .llm import LLM

T = TypeVar("T", bound=BaseModel)


class OutputValidationError(Exception):
    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__("Model output failed validation after retries: " + "; ".join(failures))


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T
    attempts: int
    validation_failures: int
    elapsed_ms: float


class StructuredOutputAgent(Generic[T]):
    def __init__(self, llm: LLM, schema: type[T], *, max_retries: int = 2):
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self.llm, self.schema, self.max_retries = llm, schema, max_retries

    def run(self, task: str) -> Result[T]:
        started = time.monotonic()
        schema = json.dumps(self.schema.model_json_schema(), separators=(",", ":"))
        messages = [
            {"role": "system", "content": "Return only one JSON object matching this schema: " + schema},
            {"role": "user", "content": task},
        ]
        failures: list[str] = []
        for attempt in range(self.max_retries + 1):
            raw = self.llm.complete(messages)
            try:
                value = self.schema.model_validate_json(raw)
                return Result(value, attempt + 1, len(failures), (time.monotonic() - started) * 1000)
            except (ValidationError, ValueError) as exc:
                reason = str(exc)[:500]
                failures.append(reason)
                messages.extend([
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": "Validation failed: " + reason + ". Return corrected JSON only."},
                ])
        raise OutputValidationError(failures)
