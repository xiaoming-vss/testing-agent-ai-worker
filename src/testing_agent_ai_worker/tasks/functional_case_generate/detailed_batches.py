"""Functional detailed case batching helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    JSON_ONLY_INSTRUCTION,
    append_stage_instruction,
    build_skill_message,
)


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


def _build_functional_detailed_case_body(
    *,
    requirement_analysis_json: str,
    case_names_json: str,
) -> str:
    """为 detailed cases skill 构造固定输入骨架。"""

    return "\n\n".join(
        [
            "【需求分析/测试点 JSON】",
            requirement_analysis_json.strip(),
            "【测试用例名称 JSON】",
            case_names_json.strip(),
        ]
    )


def _build_functional_detailed_case_instruction(extra_instruction: str) -> str:
    """为 detailed cases 追加 JSON-only 约束。"""

    return append_stage_instruction(extra_instruction, JSON_ONLY_INSTRUCTION)


def _normalize_json_text(raw_json_text: str) -> str:
    """移除模型可能返回的 markdown fence，保留纯 JSON 文本。"""

    normalized = raw_json_text.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    return normalized


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
) -> str:
    """执行 detailed cases 的分片生成并合并结果。"""

    factory = from_config or _default_from_config
    merged_cases: list[Any] = []
    batches = _build_model_batches(case_names_json)

    async with factory(config_path=config_path, workspace=workspace) as bot:
        for index, batch in enumerate(batches, 1):
            detailed_cases_result = await bot.run(
                build_skill_message(
                    skill_name=skill_name,
                    body_text=_build_functional_detailed_case_body(
                        requirement_analysis_json=requirement_analysis_json,
                        case_names_json=json.dumps(batch["payload"], ensure_ascii=False),
                    ),
                    extra_instruction=_build_functional_detailed_case_instruction(extra_instruction),
                ),
                session_key=session_key,
            )
            merged_cases.extend(_extract_cases(detailed_cases_result.content, batch["model_name"]))
            if on_progress is not None:
                on_progress(
                    json.dumps({"cases": merged_cases}, ensure_ascii=False),
                    batch["model_name"],
                    index,
                    len(batches),
                )

    return json.dumps({"cases": merged_cases}, ensure_ascii=False)
