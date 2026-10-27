from pydantic import BaseModel, Field
import pytest

from structured_output_agent.engine import OutputValidationError, StructuredOutputAgent


class Invoice(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(pattern="^[A-Z]{3}$")


class Stub:
    def __init__(self, answers):
        self.answers = iter(answers)

    def complete(self, messages, *, model=None):
        return next(self.answers)


def test_repairs_invalid_json():
    result = StructuredOutputAgent(Stub(['{"amount": -2}', '{"amount": 12, "currency": "USD"}']), Invoice).run("Extract invoice")
    assert result.value.amount == 12
    assert (result.attempts, result.validation_failures) == (2, 1)


def test_exhausts_bounded_retries():
    with pytest.raises(OutputValidationError) as error:
        StructuredOutputAgent(Stub(["{}", "{}"]), Invoice, max_retries=1).run("Extract")
    assert len(error.value.failures) == 2
