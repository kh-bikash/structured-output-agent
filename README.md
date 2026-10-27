# Structured Output Agent

Validate model JSON with Pydantic, retry malformed responses with concrete validation feedback, and return attempt metrics.

## Quick start

Requires Python 3.11 or newer. From this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
pytest -q
```

For live model calls, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` and `OPENAI_BASE_URL` as shown in `.env.example`. The test suite uses stubs and needs no model key.

```python
from pydantic import BaseModel, Field
from structured_output_agent.engine import StructuredOutputAgent
from structured_output_agent.llm import OpenAICompatibleLLM

class Invoice(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

result = StructuredOutputAgent(OpenAICompatibleLLM.from_env(), Invoice).run("Extract: USD 42.50")
print(result.value, result.attempts, result.validation_failures)
```

## Architecture

Caller -> schema JSON in system prompt -> model -> Pydantic validation -> bounded repair prompt -> typed result or OutputValidationError.

See [ARCHITECTURE.md](ARCHITECTURE.md) for components, state, failure behavior, and operations.

## Deployment and safety

Schema checks constrain shape and values. The caller should still validate business facts against a trusted source. Invalid responses are truncated before being placed in retry prompts.

Install this as a library in an authenticated application or worker. Supply the LLM adapter through dependency injection. Keep secrets in environment variables, never in source control.

## Verification

`pytest -q` runs deterministic tests. GitHub Actions runs the same suite on pushes and pull requests.

## License

MIT. See [LICENSE](LICENSE).
