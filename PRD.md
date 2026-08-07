# Nanobot Testing Worker PRD

## 1. 文档信息

- 文档名称：Nanobot Testing Worker 产品需求文档
- 文档版本：v1.1
- 更新日期：2026-08-07
- 文档类型：混合版 PRD（产品需求 + 技术实现概览）

---

## 2. 项目背景

现有测试任务平台已经具备任务发布、任务认领、任务快照、阶段审核和结果回传能力，但原有 AI 测试生成能力主要依赖 OpenAI 提示词编排，技能复用、会话复用和阶段化恢复能力不足。

本项目的目标是在平台已约定的内部任务协议范围内，构建一个基于 `nanobot` 的本地 worker 节点，用轮询方式从平台领取任务，并通过显式 skill 串联完成测试用例与测试报告生成。

该 worker 不对外提供 Web API，而是作为工作节点长期运行，持续执行平台下发的 AI 测试生成任务。

---

## 3. 产品目标

### 3.1 总体目标

构建一个稳定的、可恢复的、可扩展的 AI 测试生成 worker，使其能够：

- 按平台协议领取任务并回传结果
- 使用 nanobot skill 代替传统提示词链路
- 支持 API 测试用例生成
- 支持功能测试用例生成
- 支持需求分析任务
- 支持 UI 自动化测试用例生成
- 支持测试报告生成
- 支持阶段性进度上报
- 支持功能测试与需求分析任务的 checkpoint 卡点恢复

### 3.2 本期目标

当前版本重点实现以下能力：

- `api_case_generate` 的完整执行链路
- `functional_case_generate` 且 `source_type=text/word` 的完整执行链路
- `requirement_analysis` 且 `documentType=text/word` 的三步 skill 执行链路
- `ui_case_generate` 的源码归档下载、校验和 UI 用例生成链路
- `test_report_generate` 的日报指标到测试报告生成链路
- `functional_case_generate` 与 `requirement_analysis` 的 checkpoint 阶段恢复
- detailed cases 的分片生成与累计回传

### 3.3 非目标

当前版本暂不覆盖：

- `functional_case_generate` 的 `source_type=docx`
- 动态 workspace / session_key 映射策略的细粒度治理
- worker 自身的任务持久化数据库
- 多租户隔离控制台
- 已约定字段之外的平台协议扩展

---

## 4. 目标用户

### 4.1 直接用户

- 平台侧任务调度系统
- 测试平台研发人员
- 测试 AI 编排研发人员

### 4.2 间接用户

- 测试工程师
- 需求分析与质量保障团队
- 需要消费 AI 生成测试用例结果的业务团队

---

## 5. 使用场景

### 5.1 API 测试用例生成

平台创建 `api_case_generate` 任务后，worker 认领任务，拉取任务快照与 LLM 凭证，通过 nanobot 执行：

1. `openapi-test-config-extractor`
2. `api-cases-yaml-generator`

最终将中间配置 JSON 和结果 YAML 回传平台。

### 5.2 功能测试用例生成

平台创建 `functional_case_generate` 任务后，worker 认领任务，基于文本需求内容执行：

1. `solution-test-point-analyzer`
2. `test-case-name-extractor`
3. `detailed-test-case-generator`

最终将中间分析结果和详细测试用例 JSON 回传平台。

### 5.3 需求分析

平台创建 `requirement_analysis` 任务后，worker 认领任务。`run.documentDownloadUrl` 是 worker 内部需求文件下载地址，worker 会带 `X-Worker-Token` 下载并保留到当前任务 workspace，再把本地文件路径交给三步 nanobot skill 链。worker 不调用面向前端用户的 `/v1/requirements/{requirementId}/download`。

当前三步生产 skill 名称为：

1. `extract-docx-enhanced-text`
2. `prd-requirement-writing-skill`
3. `prd-feature-understanding-skill`

worker 会在第一步完成后上报 `analyzing` progress，并在第三步完成后将分析结果通过 `resultYaml` 回传平台。

### 5.4 UI 自动化测试用例生成

平台创建 `ui_case_generate` 任务后，worker 通过 `sourceArchiveDownloadUrl` 下载 ZIP 格式源码归档，安全解压到任务 workspace，并调用 `generate-ui-test-case`。输出必须是非空 YAML 顶层列表。

### 5.5 测试报告生成

平台创建 `test_report_generate` 任务后，worker 将 `dailyMetrics` 交给 `advanced-test-report-generator`，并通过 `resultYaml` 回传报告文本。

### 5.6 阶段审核与恢复

当平台开启 checkpoint 模式时，功能测试任务不会一次跑到底，而是按阶段停在：

- `requirement_analysis`
- `case_names`
- `detailed_cases`

前 2 个阶段会进入 `waiting_review`，等待平台人工审核后再继续。`requirement_analysis` 始终直接使用任务的文本需求内容；`configJson` 只保存审核后的阶段产物。

需求分析任务也支持 `extracting_text`、`writing_requirement`、`feature_understanding` 三阶段审核与恢复。

---

## 6. 核心能力范围

### 6.1 平台协议兼容

worker 与平台继续保持三段式任务获取流程兼容：

1. `claim`
2. `snapshot`
3. `llm-credentials`

同时支持以下生命周期回调：

- `started`
- `heartbeat`
- `progress`
- `completed`

### 6.2 Nanobot 编排方式

worker 在任务执行前会根据 `projectId` 从平台同步项目 skill 包到当前 nanobot
workspace 的 `skills/` 目录，供 nanobot 按 workspace skill 规则加载。同步时基于平台返回的
`hash`、`size`、`version` 判断本地包是否已是最新，避免重复下载。

任务执行时仍采用显式 skill 名称拼接方式调用 nanobot：

- `使用 <skill-name>`
- 拼接输入正文
- 按需拼接用户附加约束

这样可以保持技能定义与 worker 逻辑解耦，并让不同项目在各自 workspace 内使用自己的 skill 版本。

### 6.3 任务执行模式

- API 任务：两段链路，一次性执行完成
- 功能任务：三段链路，可一次性执行，也可 checkpoint 分阶段恢复
- 需求分析任务：三段链路，可一次性执行，也可 checkpoint 分阶段恢复
- UI 用例任务：下载源码归档后单步生成
- 测试报告任务：基于 `dailyMetrics` 单步生成

---

## 7. 功能需求

### 7.1 任务轮询与认领

worker 必须支持：

- 按固定轮询间隔持续 claim 任务
- claim 为空时继续等待下一轮
- claim 成功后获取 snapshot
- 如存在 `llm_connection_id`，继续获取凭证

### 7.2 API 用例生成

输入：

- `task_type=api_case_generate`
- `source_content/openapi_content`

处理：

- 调用 `openapi-test-config-extractor`
- extractor 结果作为下一步输入
- 调用 `api-cases-yaml-generator`

输出：

- `progress.configJson`：extractor 结果
- `completed.configJson`：最终中间配置
- `completed.resultYaml`：YAML 结果

### 7.3 功能测试用例生成

输入：

- `task_type=functional_case_generate`
- `source_type=text`
- `source_content`

处理：

- 调用 `solution-test-point-analyzer`
- 调用 `test-case-name-extractor`
- 按 `caseNames.categories[].model` 分片调用 `detailed-test-case-generator`

输出：

- `configJson`：需求分析、用例名称
- `resultYaml`：详细测试用例 JSON

### 7.4 需求分析

输入：

- `task_type=requirement_analysis`
- `documentType=text/word`
- `source_content`：不作为原始需求正文读取
- `documentDownloadUrl`：worker 内部需求文件下载地址
- `instruction`
- `configJson`

处理：

- 下载 `documentDownloadUrl` 指向的文件
- 保存到当前任务 workspace 的 `inputs/{taskId}/` 目录
- 将本地文件路径作为第一步 skill 输入
- 调用需求分析第一步 skill
- 第一步结果作为第二步输入
- 调用需求分析第二步 skill
- 第二步结果作为第三步输入
- 调用需求分析第三步 skill

输出：

- `progress.currentStage=analyzing`
- `progress.stageStatus=running`
- `progress.configJson`：原始配置与第一步结果
- `completed.configJson`：原始配置、第一步结果与第二步结果
- `completed.resultYaml`：第三步分析结果

当前三步生产 skill 名称为：

1. `extract-docx-enhanced-text`
2. `prd-requirement-writing-skill`
3. `prd-feature-understanding-skill`

### 7.5 detailed cases 分片生成

为避免最终详细测试用例一次性生成过大，worker 需要：

- 基于 `caseNames.categories[].model` 拆分分片
- 每个 model 单独调用一次 `detailed-test-case-generator`
- 将每次返回的 `cases` 合并进累计结果
- 每完成一片回传一次 `detailed_cases` progress

### 7.6 detailed cases JSON-only 约束

在最后调用 `detailed-test-case-generator` 时，worker 必须显式加入额外约束：

- 直接返回 JSON 内容
- 不返回 Markdown 代码块
- 不返回解释性文字

目标是降低模型输出被装饰文本污染的风险，保证结果更容易被平台解析。

### 7.7 Checkpoint 卡点恢复

当 `checkpointEnabled=true` 时：

- `requirement_analysis`
  - 直接使用任务的文本需求内容
  - 生成 `requirementAnalysis`
  - 写回 `waiting_review`
- `case_names`
  - 从 `configJson.requirementAnalysis` 恢复
  - 生成 `caseNames`
  - 写回 `waiting_review`
- `detailed_cases`
  - 从 `configJson.requirementAnalysis` 和 `configJson.caseNames` 恢复
  - 进行分片生成
  - 分片过程中写回 `running`
  - 全部完成后提交 completed

需求分析任务的 checkpoint 阶段为：

- `extracting_text`：提取增强文本并进入审核
- `writing_requirement`：基于审核后的增强文本生成需求流程梳理稿
- `feature_understanding`：基于前两阶段审核结果生成最终需求理解记录

### 7.8 UI 自动化测试用例生成

输入：

- `task_type=ui_case_generate`
- `sourceArchiveDownloadUrl`：ZIP 格式前端源码归档下载地址

处理：

- 使用 worker token 下载归档
- 拒绝路径穿越并解压到当前任务 workspace
- 调用 `generate-ui-test-case`
- 校验用例、步骤顺序以及 keyword 对应的字段规则

输出：

- `progress.currentStage=ui_case_generating`
- `completed.resultYaml`：非空 YAML 顶层列表

### 7.9 测试报告生成

输入：

- `task_type=test_report_generate`
- `dailyMetrics`

处理：调用 `advanced-test-report-generator`。

输出：通过 `completed.resultYaml` 返回报告文本，并在摘要中记录指标键和报告长度。

---

## 8. 非功能需求

### 8.1 稳定性

- 轮询异常不应导致 worker 整体退出
- heartbeat 异常应尽量重试并保活主流程
- progress 上报失败不应中断模型生成

### 8.2 可恢复性

- 功能测试生成必须支持基于 `configJson` 恢复
- 中间结果必须可被平台审核后继续推进

### 8.3 可测试性

- 核心执行链路需要覆盖单元测试
- prompt 拼装、checkpoint 恢复、分片合并都需要有自动化验证

### 8.4 可维护性

- 平台协议适配层、nanobot 调用层、执行编排层分离
- 关键调用链路需要有清晰注释

---

## 9. 平台交互流程

### 9.1 获取任务流程

1. worker 调用 `task_claim_path`
2. 平台返回任务 claim 信息
3. worker 调用 `task_snapshot_path`
4. 如有 `llm_connection_id`，worker 调用 `task_llm_credentials_path`
5. worker 将平台对象转换成内部 `Task`

### 9.2 生命周期回传流程

1. 任务开始前回传 `started`
2. 执行中后台定时回传 `heartbeat`
3. 中间阶段可选回传 `progress`
4. 最终成功或失败回传 `completed`

---

## 10. 配置需求

配置采用 TOML，当前主要包括：

- `worker`
  - worker 标识
  - 轮询间隔
  - 心跳间隔
  - 是否单轮执行
- `platform`
  - 平台地址
  - 任务与结果接口路径
  - `X-Worker-Token`
- `nanobot`
  - `config_path`
  - `workspace_root`
- `logging`
  - 日志级别
  - 输出目录
  - 保留天数

---

## 11. 技术实现概览

### 11.1 模块分层

- `app`
  - 负责应用启动装配，集中创建 poller、runner、平台适配器和执行器
- `platform`
  - 负责平台协议适配、HTTP 调用、claim/snapshot/credentials、started/progress/completed 回传
- `services`
  - 薄服务层，连接上层执行编排与底层平台适配
- `worker`
  - 负责轮询、心跳、任务生命周期和按 `task_type` 分发执行器
- `tasks`
  - 按任务类型组织业务编排，每个任务目录内维护 executor、chain 和任务专属辅助逻辑
- `nanobot_runtime`
  - 负责共享的 skill prompt 拼装、nanobot 配置构建和运行路径管理
- `config`
  - 负责 TOML 配置加载
- `models`
  - 负责内部任务与执行结果模型

### 11.2 核心调用链路

任务获取链路：

`main -> app.bootstrap.build_task_poller -> TaskPoller -> TaskService -> HttpClaimTaskSource.poll_task`

项目 skill 同步链路：

`main -> app.bootstrap.build_task_runner -> PlatformProjectSkillSource -> workspace/project-{projectId}/skills`

任务执行链路：

`main -> app.bootstrap.build_task_runner -> WorkerRunner.process_task -> WorkerTaskDispatcherExecutor.execute`

API 任务链路：

`tasks.api_case_generate.executor.ApiCaseNanobotExecutor.execute -> tasks.api_case_generate.chain.run_chain -> extractor -> generator`

功能任务链路：

`tasks.functional_case_generate.executor.FunctionalCaseNanobotExecutor.execute -> tasks.functional_case_generate.chain.run_functional_chain`

checkpoint 恢复链路：

`tasks.functional_case_generate.checkpoint.execute_checkpoint_task -> tasks.functional_case_generate.chain.run_skill_step / tasks.functional_case_generate.detailed_batches.run_functional_detailed_case_batches`

需求分析链路：

`tasks.requirement_analysis.executor.RequirementAnalysisNanobotExecutor.execute -> tasks.requirement_analysis.chain.run_requirement_analysis_chain -> skill step 1 -> skill step 2 -> skill step 3`

结果回传链路：

`WorkerRunner -> ResultService -> HttpResultSink -> platform callbacks`

---

## 12. 当前限制

- `functional_case_generate` 支持 `source_type=text/word`，均直接使用 `sourceContent`
- `requirement_analysis` 支持 `documentType=text/word`，不支持 `richtext`
- `docx` 功能链路尚未接入
- worker 依赖平台已约定的 `sourceArchiveDownloadUrl`、`dailyMetrics` 等协议字段，不额外发明流程字段
- 当前结果主要以内存态生成和回传为主，本地没有单独持久化数据库

---

## 13. 后续规划建议

- 支持 `functional_case_generate` 的 `source_type=docx`
- 支持更细粒度的 workspace / session_key 映射策略
- 增加本地失败记录和重试审计
- 增加运行态观测指标与任务统计
- 补充集成测试和真实平台联调脚本
