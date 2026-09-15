import io
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskStatus
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.tasks.ui_case_generate.executor import (
    UiCaseNanobotExecutor,
    _validate_ui_cases_yaml,
)
from testing_agent_ai_worker.tasks.ui_case_generate.source_archive import (
    PlatformSourceArchiveDownloader,
)

VALID_YAML = """- name: 登录成功
  enabled: true
  stepsJson:
    - orderNo: 1
      stepName: 打开登录页
      keyword: open
      operationValue: /login
      continueOnFailure: false
      enabled: true
    - orderNo: 2
      stepName: 点击登录
      keyword: click
      locatorType: role
      locatorValue: button
      continueOnFailure: false
      enabled: true
  orderNo: 1
"""


ALL_KEYWORDS_YAML = """- name: 所有关键字字段规则
  enabled: true
  stepsJson:
    - {orderNo: 1, stepName: 打开页面, keyword: open, operationValue: /login, continueOnFailure: false, enabled: true}
    - {orderNo: 2, stepName: 刷新页面, keyword: reload, continueOnFailure: false, enabled: true}
    - {orderNo: 3, stepName: 点击元素, keyword: click, locatorType: css, locatorValue: button, continueOnFailure: false, enabled: true}
    - {orderNo: 4, stepName: 双击元素, keyword: dblclick, locatorType: xpath, locatorValue: //button, continueOnFailure: false, enabled: true}
    - {orderNo: 5, stepName: 输入内容, keyword: input, locatorType: placeholder, locatorValue: 用户名, operationValue: tester, continueOnFailure: false, enabled: true}
    - {orderNo: 6, stepName: 清空内容, keyword: clear, locatorType: label, locatorValue: 用户名, continueOnFailure: false, enabled: true}
    - {orderNo: 7, stepName: 按下回车, keyword: press, locatorType: test_id, locatorValue: username, operationValue: Enter, continueOnFailure: false, enabled: true}
    - {orderNo: 8, stepName: 等待文本, keyword: wait_text, locatorType: testid, locatorValue: result, operationValue: 成功, continueOnFailure: false, enabled: true}
    - {orderNo: 9, stepName: 断言文本, keyword: assert_text, locatorType: text, locatorValue: 成功, operationValue: 成功, comparator: contains, continueOnFailure: false, enabled: true}
    - {orderNo: 10, stepName: 断言可见, keyword: assert_visible, locatorType: role, locatorValue: button, operationValue: '3000', continueOnFailure: false, enabled: true}
    - {orderNo: 11, stepName: 断言地址, keyword: assert_url, operationValue: /projects, comparator: eq, continueOnFailure: false, enabled: true}
    - {orderNo: 12, stepName: 截图, keyword: screenshot, continueOnFailure: false, enabled: true}
    - {orderNo: 13, stepName: 固定等待, keyword: sleep, operationValue: '1000', continueOnFailure: false, enabled: true}
  orderNo: 1
"""


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class UiCaseExecutorTests(unittest.TestCase):
    def _task(self, *, source_archive_download_url: str = "/source.zip") -> Task:
        return Task(
            task_id="ui-task-1",
            run_id="run-1",
            generate_task_id="generate-1",
            task_type="ui_case_generate",
            project_id="project-1",
            sprint_id="sprint-1",
            requirement_id="requirement-1",
            payload=TaskPayload(
                openapi_content="",
                source_archive_download_url=source_archive_download_url,
                source_content="不得传入技能",
                extra_instruction="覆盖登录流程",
            ),
        )

    def test_execute_downloads_extracts_and_returns_skill_yaml(self) -> None:
        captured: dict[str, object] = {}
        progress: list[TaskProgress] = []

        class Client:
            def get_bytes(self, url: str) -> bytes:
                self.url = url
                return _zip_bytes({"src/Login.tsx": "export const Login = () => null"})

        def fake_skill_runner(**kwargs):
            captured.update(kwargs)
            return VALID_YAML

        temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        executor = UiCaseNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root=temp_dir),
            source_downloader=PlatformSourceArchiveDownloader(Client()),
            skill_runner=fake_skill_runner,
        )
        result = executor.execute(self._task(), datetime.now().astimezone(), progress.append)

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual(VALID_YAML, result.output_yaml)
        self.assertEqual("generate-ui-test-case", captured["skill_name"])
        self.assertIn("sourceRoot", result.intermediate_json_text)
        self.assertIn("登录流程", captured["input_text"])
        self.assertIn("始终返回非空 YAML list", captured["input_text"])
        self.assertNotIn(
            "步骤必须包含 orderNo、stepName、keyword、operationValue", captured["input_text"]
        )
        self.assertNotIn("不得传入技能", captured["input_text"])
        self.assertEqual(1, len(progress))
        self.assertEqual("ui_case_generating", progress[0].current_stage)

    def test_execute_fails_when_archive_is_missing(self) -> None:
        class Downloader:
            def download_and_extract(self, **kwargs):
                raise ValueError("ui_case_generate 缺少 sourceArchiveDownloadUrl")

        executor = UiCaseNanobotExecutor(
            nanobot_config=NanobotConfig(),
            source_downloader=Downloader(),
            skill_runner=lambda **kwargs: VALID_YAML,
        )
        result = executor.execute(
            self._task(source_archive_download_url=""), datetime.now().astimezone(), lambda _: None
        )
        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("sourceArchiveDownloadUrl", result.error_message or "")

    def test_execute_fails_when_skill_output_is_not_a_complete_yaml_case(self) -> None:
        class Downloader:
            def download_and_extract(self, **kwargs):
                return Path("D:/tmp/source")

        executor = UiCaseNanobotExecutor(
            nanobot_config=NanobotConfig(),
            source_downloader=Downloader(),
            skill_runner=lambda **kwargs: "- name: incomplete",
        )
        result = executor.execute(self._task(), datetime.now().astimezone(), lambda _: None)
        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("缺少必填字段", result.error_message or "")

    def test_validator_rejects_single_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "顶层必须是非空 YAML list"):
            _validate_ui_cases_yaml(VALID_YAML.removeprefix("- ").replace("\n  ", "\n"))

    def test_validator_accepts_multiple_cases_with_empty_steps_and_incrementing_order(self) -> None:
        output = """- name: 登录成功
  enabled: true
  stepsJson: []
  orderNo: 1
- name: 用户名为空登录失败
  enabled: true
  stepsJson: []
  orderNo: 2
"""
        self.assertEqual(2, _validate_ui_cases_yaml(output))

    def test_validator_accepts_all_supported_keyword_contracts(self) -> None:
        self.assertEqual(1, _validate_ui_cases_yaml(ALL_KEYWORDS_YAML))

    def test_validator_rejects_invalid_case_and_step_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "跨用例连续递增"):
            _validate_ui_cases_yaml(VALID_YAML.rsplit("orderNo: 1", 1)[0] + "orderNo: 2\n")
        with self.assertRaisesRegex(ValueError, "从 1 开始连续递增"):
            _validate_ui_cases_yaml(VALID_YAML.replace("- orderNo: 1", "- orderNo: 2", 1))

    def test_validator_rejects_unsupported_keyword_and_locator_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "keyword 不受支持"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace("keyword: reload", "keyword: wait_visible")
            )
        with self.assertRaisesRegex(ValueError, "locatorType 不受支持"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace("locatorType: css", "locatorType: id", 1)
            )

    def test_validator_enforces_locator_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "locatorType 不受支持或缺失"):
            _validate_ui_cases_yaml(ALL_KEYWORDS_YAML.replace("locatorType: css, ", "", 1))
        with self.assertRaisesRegex(ValueError, "不应包含 locatorType/locatorValue"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace(
                    "keyword: reload, ",
                    "keyword: reload, locatorType: css, locatorValue: body, ",
                    1,
                )
            )

    def test_validator_enforces_operation_value_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须包含 operationValue"):
            _validate_ui_cases_yaml(ALL_KEYWORDS_YAML.replace("operationValue: /login, ", "", 1))
        with self.assertRaisesRegex(ValueError, "不应包含 operationValue"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace(
                    "keyword: clear, ", "keyword: clear, operationValue: value, ", 1
                )
            )

    def test_validator_enforces_comparator_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "comparator 必须是 eq 或 contains"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace("comparator: contains", "comparator: ne")
            )
        with self.assertRaisesRegex(ValueError, "不应包含 comparator"):
            _validate_ui_cases_yaml(
                ALL_KEYWORDS_YAML.replace("keyword: click, ", "keyword: click, comparator: eq, ", 1)
            )

    def test_validator_requires_step_default_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "缺少必填字段"):
            _validate_ui_cases_yaml(VALID_YAML.replace("      continueOnFailure: false\n", "", 1))
        with self.assertRaisesRegex(ValueError, "缺少必填字段"):
            _validate_ui_cases_yaml(VALID_YAML.replace("      enabled: true\n", "", 1))

    def test_downloader_rejects_path_traversal(self) -> None:
        class Client:
            def get_bytes(self, url: str) -> bytes:
                return _zip_bytes({"../escape.ts": "export {}"})

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsafe path"):
                PlatformSourceArchiveDownloader(Client()).download_and_extract(
                    source_archive_download_url="/source.zip",
                    task=self._task(),
                    workspace=Path(temp_dir),
                )


if __name__ == "__main__":
    unittest.main()
