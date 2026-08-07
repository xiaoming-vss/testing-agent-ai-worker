# AI 测试任务 Worker

本上下文负责接收平台派发的 AI 测试任务，并生成可回传平台的测试产物。

## 任务输入

**源码归档**：
`ui_case_generate` 任务携带的 ZIP 格式前端源码文件，通过 `sourceArchiveDownloadUrl` 获取；其解压后的根目录是 UI 用例生成技能的源码输入。
_避免使用_：源码文件、下载包

**UI 测试用例**：
由 `ui_case_generate` 生成的可执行 UI 自动化用例；任务产物是 YAML 顶层列表，每一项均包含 `name`、`enabled`、`stepsJson` 和 `orderNo`。
_避免使用_：UI 用例 JSON、测试步骤列表
