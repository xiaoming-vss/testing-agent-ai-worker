"""Functional detailed case batching helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION,
    append_stage_instruction,
    build_skill_message,
)

from .validation import generate_validated, normalize_json


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


def _build_functional_detailed_case_body(
    *,
    requirement_analysis_json: str,
    case_names_json: str,
    source_text: str = "",
) -> str:
    """为 detailed cases skill 构造固定输入骨架。"""

    return "\n\n".join(
        [
            "【原始需求】",
            source_text.strip(),
            "【需求分析/测试点 JSON】",
            requirement_analysis_json.strip(),
            "【测试用例名称 JSON】",
            case_names_json.strip(),
        ]
    )


def _build_functional_detailed_case_instruction(extra_instruction: str) -> str:
    """为 detailed cases 追加 JSON-only 约束。"""

    return append_stage_instruction(
        extra_instruction, FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION
    )


def _normalize_json_text(raw_json_text: str) -> str:
    """移除模型可能返回的 markdown fence，保留纯 JSON 文本。"""

    return normalize_json(raw_json_text)


def _build_model_batches(case_names_json: str) -> list[dict[str, Any]]:
    """按 `categories[].model` 拆分 detailed cases 分片。"""

    normalized_case_names = _normalize_json_text(case_names_json)
    parsed_case_names = json.loads(normalized_case_names)
    if not isinstance(parsed_case_names, dict):
        raise ValueError("测试用例名称 JSON 顶层必须是对象")

    categories = parsed_case_names.get("categories", [])
    if not isinstance(categories, list):
        raise ValueError("测试用例名称 JSON 的 categories 必须是数组")

    if not categories:
        return [{"model_name": "空用例名称分组", "payload": {"categories": []}}]

    batches: list[dict[str, Any]] = []
    for index, category in enumerate(categories, 1):
        if not isinstance(category, dict):
            raise ValueError(f"测试用例名称 JSON 的 categories[{index}] 必须是对象")
        batches.append(
            {
                "model_name": str(category.get("model") or f"未命名模块{index}"),
                "payload": {"categories": [category]},
            }
        )
    return batches


def _extract_cases(raw_result: str, model_name: str) -> list[Any]:
    """从单个 detailed cases 分片结果中提取 `cases` 数组。"""

    parsed_result = json.loads(_normalize_json_text(raw_result))
    if not isinstance(parsed_result, dict):
        raise ValueError(f"详细测试用例分片结果顶层必须是对象: model={model_name}")

    cases = parsed_result.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"详细测试用例分片结果 cases 必须是数组: model={model_name}")
    return cases


async def run_functional_detailed_case_batches(
    *,
    requirement_analysis_json: str,
    case_names_json: str,
    session_key: str,
    skill_name: str,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    on_progress: Callable[[str, str, int, int], None] | None = None,
    from_config: Callable[..., Any] | None = None,
    current_cases_json: str = "",
    revision_instruction: str = "",
    source_text: str = "",
) -> str:
    """执行 detailed cases 的分片生成并合并结果。"""

    factory = from_config or _default_from_config
    merged_cases: list[Any] = []
    batches = _build_model_batches(case_names_json)
    current_cases = []
    if revision_instruction:
        current_cases = _extract_cases(current_cases_json, "当前候选结果")
        # Edited candidates may contain modules absent from the original test points.
        known_modules = {batch["model_name"] for batch in batches}
        for case in current_cases:
            module = (
                str(case.get("case_module") or case.get("module") or "未分组").strip() or "未分组"
            )
            if module not in known_modules:
                batches.append(
                    {
                        "model_name": module,
                        "payload": {"categories": [{"model": module, "data": []}]},
                    }
                )
                known_modules.add(module)

    async with factory(config_path=config_path, workspace=workspace) as bot:
        for index, batch in enumerate(batches, 1):
            body = _build_functional_detailed_case_body(
                source_text=source_text,
                requirement_analysis_json=requirement_analysis_json,
                case_names_json=json.dumps(batch["payload"], ensure_ascii=False),
            )
            if revision_instruction:
                module_cases = [
                    case
                    for case in current_cases
                    if (
                        str(case.get("case_module") or case.get("module") or "未分组").strip()
                        or "未分组"
                    )
                    == batch["model_name"]
                ]
                body += (
                    "\n\n【当前模块候选用例】\n"
                    + json.dumps({"cases": module_cases}, ensure_ascii=False)
                    + "\n\n【本轮优化要求】\n"
                    + revision_instruction
                    + "\n请保留未涉及修改的用例，输出当前模块优化后的完整用例集合。"
                )
            detailed_cases_result = await generate_validated(
                stage="detailed_cases",
                module=batch["model_name"],
                batch=index,
                previous_cases=merged_cases,
                generate=lambda prompt: bot.run(prompt, session_key=session_key),
                inputs=build_skill_message(
                    skill_name=skill_name,
                    body_text=body,
                    extra_instruction=_build_functional_detailed_case_instruction(
                        extra_instruction
                    ),
                ),
            )
            merged_cases.extend(_extract_cases(detailed_cases_result, batch["model_name"]))
            if on_progress is not None:
                on_progress(
                    "",
                    batch["model_name"],
                    index,
                    len(batches),
                )

    return json.dumps({"cases": merged_cases}, ensure_ascii=False)
