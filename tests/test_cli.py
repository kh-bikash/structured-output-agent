import json

from structured_output_agent.__main__ import main


def test_cli_validates_typed_json_without_model(capsys):
    assert (
        main(
            [
                "validate",
                '{"title":"Bug","priority":2}',
                "--field",
                "title:str",
                "--field",
                "priority:int",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "valid": True,
        "value": {"title": "Bug", "priority": 2},
    }


def test_cli_extracts_typed_fields_with_model_adapter(monkeypatch, capsys):
    class FakeLLM:
        def complete(self, messages, *, model=None):
            return '{"title":"Incident","priority":1}'

    monkeypatch.setattr(
        "structured_output_agent.__main__.OpenAICompatibleLLM.from_env",
        lambda: FakeLLM(),
    )
    assert (
        main(
            [
                "extract",
                "Extract incident information",
                "--field",
                "title:str",
                "--field",
                "priority:int",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["value"]["title"] == "Incident"
