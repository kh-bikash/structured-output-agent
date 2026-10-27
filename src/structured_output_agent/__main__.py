"""Extract or validate typed JSON from the command line or browser."""

from __future__ import annotations

import argparse
import json
import re

from pydantic import ConfigDict, create_model

from .engine import StructuredOutputAgent, validate_tool_response
from .llm import OpenAICompatibleLLM
from .web import serve

WEB_ACTIONS = {
    "extract": [
        ("task", "Text or extraction instruction", "textarea", True),
        ("fields", "Fields, one per line (name:type)", "textarea", True),
    ],
    "validate": [
        ("fields", "Fields, one per line (name:type)", "textarea", True),
        ("raw", "JSON to validate", "textarea", True),
    ],
}
TYPES = {"str": str, "int": int, "float": float, "bool": bool}


def _schema(specs: list[str]):
    fields = {}
    for spec in specs:
        name, separator, kind = spec.strip().partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("fields must use name:type syntax")
        if kind not in TYPES or name in fields:
            raise ValueError("unknown field type or duplicate field: " + spec)
        fields[name] = (TYPES[kind], ...)
    if not fields:
        raise ValueError("at least one field is required")
    return create_model("Extraction", __config__=ConfigDict(extra="forbid"), **fields)


def execute(action: str, values: dict) -> object:
    raw_fields = values["fields"]
    specs = (
        raw_fields
        if isinstance(raw_fields, list)
        else [item for item in raw_fields.splitlines() if item.strip()]
    )
    schema = _schema(specs)
    if action == "validate":
        value = validate_tool_response(values["raw"], schema)
        return {"valid": True, "value": value.model_dump()}
    if action == "extract":
        result = StructuredOutputAgent(OpenAICompatibleLLM.from_env(), schema).run(
            values["task"]
        )
        return {"value": result.value.model_dump(), "attempts": result.attempts}
    raise ValueError("unknown action")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Typed LLM output and JSON validation")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="Extract typed fields with a model")
    extract.add_argument("task")
    extract.add_argument("--field", dest="fields", action="append", required=True)
    validate = commands.add_parser("validate", help="Validate JSON without a model")
    validate.add_argument("raw")
    validate.add_argument("--field", dest="fields", action="append", required=True)
    browser = commands.add_parser("serve", help="Start local browser interface")
    browser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve("Structured Output Agent", WEB_ACTIONS, execute, port=args.port)
    else:
        print(json.dumps(execute(args.command, vars(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
