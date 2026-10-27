# Architecture

## Goal

Validate model JSON with Pydantic, retry malformed responses with concrete validation feedback, and return attempt metrics.

## Request path

Caller -> schema JSON in system prompt -> model -> Pydantic validation -> bounded repair prompt -> typed result or OutputValidationError.

## Components

- `src/structured_output_agent/engine.py`: policy and state transitions for this project.
- `src/structured_output_agent/llm.py`: injected model protocol and HTTPS OpenAI-compatible adapter with timeouts and retry for transient transport failures.
- `tests/test_engine.py`: deterministic behavior and failure tests.
- `.github/workflows/ci.yml`: install and test gate.


## State and failure behavior

Schema checks constrain shape and values. The caller should still validate business facts against a trusted source. Invalid responses are truncated before being placed in retry prompts.

The LLM adapter times out after 30 seconds and retries transient HTTP failures twice. Model output is untrusted input and is parsed or validated at the project boundary.

## Operations checklist

1. Set secrets through a secret manager and rotate them regularly.
2. Put the service or integrating application behind TLS and authentication.
3. This library is stateless. Persist validation events in the host application's telemetry store if auditability is required.
4. Run `pytest -q` in CI before deployment.
5. Define workload specific evaluation cases, latency objectives, and rollback criteria before serving real users.

## Contract and control flow

`StructuredOutputAgent[T]` accepts a Pydantic model type and an injected `LLM`. The schema is sent to the model, then each reply is checked with strict Pydantic JSON validation. A complete JSON code fence is accepted; arbitrary surrounding prose is rejected. `max_retries` bounds repair calls, and `max_output_chars` prevents oversized model output from consuming unbounded validation resources. `validate_tool_response` applies the same boundary to JSON returned by tools.

| Outcome | Result |
|---|---|
| Valid JSON matching the schema | Typed `Result[T]` with attempt count and elapsed time |
| Parse or schema failure with retries left | Send a bounded validation error back to the model |
| Exhausted retries | Raise `OutputValidationError` with per-attempt reasons |

An optional `event_sink` receives success/failure, attempt number, error class, and elapsed time without raw user content. Use that event for dashboards. Do not assume schema validity proves the extracted facts are true.

## Product interfaces and trust boundary

The installed console command and local browser call the same product operation in `src/*/__main__.py`; the browser does not replace the engine's validation or state transitions. `src/*/web.py` serves HTML and a JSON action endpoint with a one-megabyte request limit and a per-process CSRF token. It binds to loopback by default. A non-loopback bind requires `AGENT_WEB_TOKEN` of at least 16 characters, checked on every action request. The page never embeds the access token; an operator enters it in the browser. Treat the browser as an operator interface and place TLS plus identity-aware access control in front of any public endpoint. The non-root container is described in `DEPLOYMENT.md`.
