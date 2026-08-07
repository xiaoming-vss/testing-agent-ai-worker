# 领域文档

说明工程技能在探索代码库时应如何使用本仓库的领域文档。

## 探索前先读取

- 仓库根目录的 `CONTEXT.md`；或
- 若根目录存在 `CONTEXT-MAP.md`，则读取它所指向且与当前主题相关的每个 `CONTEXT.md`；
- `docs/adr/` 中与当前工作范围相关的 ADR。

如这些文件不存在，静默继续：不要报告缺失，也不要主动建议创建。`/domain-modeling` 技能（可通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 使用）会在术语或决策真正明确时按需创建。

## 文件布局

本仓库采用单上下文布局：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

## 使用术语表中的词汇

当输出需要命名领域概念（如问题标题、重构建议、假设或测试名称）时，使用 `CONTEXT.md` 中定义的术语；不要改用术语表明确避免的同义词。

如果需要的概念不在术语表中，应重新考虑是否使用了项目未采用的说法；若确有缺口，请将其记录给 `/domain-modeling`。

## 标明 ADR 冲突

如果输出与现有 ADR 相冲突，必须显式说明，而不能悄然覆盖：

> 与 ADR-0007（订单事件溯源）相冲突；但值得重新审视，因为……
