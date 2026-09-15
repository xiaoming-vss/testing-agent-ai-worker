"""Shared nanobot prompt helpers."""

JSON_ONLY_INSTRUCTION = "请直接返回 JSON 内容，不要返回 Markdown 代码块、解释文字或其他说明。"
FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION = (
    "请直接返回符合 analyze-functional-requirements skill 要求的测试点分析 JSON，"
    "不要返回详细测试用例、cases/testCases、meta/config 包装结构，"
    "输出必须是且只能是一个可由 JSON.parse 直接解析的合法 JSON 对象："
    "第一个字符必须是 {，最后一个字符必须是 }；"
    "不得在对象前后输出空行、解释、标题、注释、Markdown 代码块或第二个 JSON 对象。"
)
FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION = (
    "请直接返回符合 generate-solution-test-points skill 要求的测试用例名称 JSON，"
    "不要返回详细测试步骤、cases/testCases、meta/config 包装结构，"
    "不要返回 Markdown 代码块、解释文字或其他说明。"
)
FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION = (
    "请直接返回包含 cases 数组的详细测试用例 JSON。"
    "输出必须是且只能是一个可由 JSON.parse 直接解析的合法 JSON 对象："
    "第一个字符必须是 {，最后一个字符必须是 }；"
    "不得在对象前后输出空行、解释、标题、注释、Markdown 代码块或第二个 JSON 对象。"
)
API_EXTRACTOR_JSON_ONLY_INSTRUCTION = (
    "请直接返回符合 openapi-test-config-extractor skill 要求的接口配置 JSON，"
    "不要返回测试用例、meta/config/testCases 结构，"
    "不要返回 Markdown 代码块、解释文字或其他说明。"
)
API_GENERATOR_YAML_ONLY_INSTRUCTION = (
    "请直接返回符合 api-cases-yaml-generator skill 要求的 YAML 内容，"
    "不要返回 JSON、meta/config/testCases 结构，"
    "不要返回 Markdown 代码块、解释文字或其他说明。"
)


def append_stage_instruction(extra_instruction: str, stage_instruction: str) -> str:
    """按 API 链路约定拼接平台附加约束和阶段输出约束。"""

    if extra_instruction.strip():
        return "\n\n".join([extra_instruction.strip(), stage_instruction])
    return stage_instruction


def build_skill_message(*, skill_name: str, body_text: str, extra_instruction: str) -> str:
    """按“显式 skill 名称 + 正文 + 附加约束”的约定拼 prompt。"""

    parts = [
        f"请先加载本地 skill：{skill_name}，并严格遵循该 SKILL.md 的全部规则。",
        body_text.strip(),
    ]
    if extra_instruction.strip():
        parts.append(extra_instruction.strip())
    return "\n\n".join(part for part in parts if part)
