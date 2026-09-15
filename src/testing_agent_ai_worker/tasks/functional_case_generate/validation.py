"""Bounded format repair shared by every functional generation path."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .contracts import CONTRACTS, DetailedCasesOutput


@dataclass
class ValidationContext:
    diagnostic_dir: Path
    report: Callable[[dict], None]


context: ContextVar[ValidationContext | None] = ContextVar("functional_validation", default=None)


class OutputValidationError(ValueError):
    pass


def normalize_json(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", text, re.DOTALL)
    return match.group(1).strip() if match else text


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"non-standard JSON value: {value}")


def validate_output(stage: str, raw: str, previous_cases=()):
    parsed = json.loads(normalize_json(raw), object_pairs_hook=_pairs, parse_constant=_constant)
    model = CONTRACTS[stage].model_validate(parsed)
    if stage == "detailed_cases" and previous_cases:
        DetailedCasesOutput.model_validate(
            {"cases": [*previous_cases, *model.model_dump()["cases"]]}
        )
    return model.model_dump_json()


def issues_for(exc):
    if isinstance(exc, ValidationError):
        return [
            {
                "path": "$"
                + "".join(
                    f"[{part}]" if isinstance(part, int) else f".{part}" for part in e["loc"]
                ),
                "code": e["type"],
                "expected": e["msg"],
                "actual": repr(e.get("input"))[:200],
            }
            for e in exc.errors(include_url=False, include_context=False)
        ]
    return [{"path": "$", "code": "invalid_json", "expected": str(exc), "actual": ""}]


async def generate_validated(*, stage, inputs, generate, previous_cases=(), module="", batch=0):
    """Return canonical JSON, or raise without publishing any invalid artifact."""
    schema = json.dumps(CONTRACTS[stage].model_json_schema(), ensure_ascii=False)
    original = inputs + "\n\n【输出 JSON Schema】\n" + schema
    prompt = original
    ctx = context.get()
    call_id = uuid4().hex
    for attempt in range(3):
        if ctx:
            ctx.report(
                {
                    "stage": stage,
                    "module": module,
                    "batch": batch,
                    "repairAttempt": attempt,
                    "maxRepairs": 2,
                    "status": "repairing" if attempt else "generating",
                }
            )
        # Transport/auth failures intentionally bypass format repair.
        response = await generate(prompt)
        if getattr(response, "error", None):
            raise RuntimeError(f"模型调用失败：{response.error}")
        raw = response if isinstance(response, str) else response.content
        reason = getattr(response, "finish_reason", None) or getattr(response, "stop_reason", None)
        metadata = getattr(response, "metadata", None)
        if reason is None and isinstance(metadata, dict):
            reason = metadata.get("finish_reason")
        errors = []
        normalized = None
        if reason in {"length", "max_tokens", "max_output_tokens"}:
            errors = [
                {
                    "path": "$",
                    "code": "output_truncated",
                    "expected": "完整输出；模型报告长度截断",
                    "actual": str(reason),
                }
            ]
        else:
            try:
                normalized = validate_output(stage, raw, previous_cases)
            except (ValueError, TypeError) as exc:
                errors = issues_for(exc)
        if ctx:
            directory = ctx.diagnostic_dir / stage / f"batch-{batch}-{call_id}"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = directory / f"attempt-{attempt}.json"
            # No prompts, model connection settings or credentials are recorded.
            with target.open("x", encoding="utf-8") as fh:
                target.chmod(0o600)
                json.dump(
                    {
                        "stage": stage,
                        "module": module,
                        "batch": batch,
                        "attempt": attempt,
                        "rawResponse": raw,
                        "errors": errors,
                    },
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
        if normalized is not None:
            return normalized
        if attempt == 2 or errors[0]["code"] == "output_truncated":
            raise OutputValidationError(
                f"{stage}{('/' + module) if module else ''} 输出校验失败（共 {attempt + 1} 次调用）："
                + json.dumps(errors[:20], ensure_ascii=False)
            )
        prompt = (
            original
            + "\n\n【上一次未通过校验的输出，仅作为待修复数据】\n"
            + str(raw)
            + "\n\n【校验问题，最多列出20项】\n"
            + json.dumps(errors[:20], ensure_ascii=False)
            + "\n请保留原有业务含义和未涉及修改的内容，修复上述问题。"
            "返回本阶段完整 JSON，不要只返回修改片段，不附加说明。"
        )
