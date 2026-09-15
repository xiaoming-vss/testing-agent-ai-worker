# 代码风险分析的需求输入是需求理解记录,而非原始需求文档

`code_risk_analysis` 任务的需求输入直接采用需求分析任务(`requirement_analysis`)三步链的最终产物——需求理解记录;控制面创建任务时将其固化进快照 `requirement.documentContent`(`documentType` 恒为 `text`),而不是原始需求文档。worker 侧因此不下载 docx、不调 `extract-docx-enhanced-text`;无需求理解记录的需求禁止发起风险分析(控制面创建时校验,worker 防御性失败)。

**Considered Options**:
- 原始需求文档(text/docx 双形态):worker 需下载 docx 并复用 `extract-docx-enhanced-text` 抽取文本;缺点是需求理解程度低,分析质量取决于模型对原始文档解读的临场发挥。
- 增强文本(第一步 `extract-docx-enhanced-text` 输出):字面上符合「增强文本」,但不是需求分析定稿产物。
- 需求理解记录(本决策):经过完整三步链与人工审核,质量与口径稳定,worker 处理路径最简。
