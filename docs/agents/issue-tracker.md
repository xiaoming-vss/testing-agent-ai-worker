# 问题跟踪：本地 Markdown

本仓库的问题和规格说明（也可称 PRD）保存在 `.scratch/` 下的 Markdown 文件中。

## 约定

- 每项功能使用一个目录：`.scratch/<功能标识>/`
- 规格说明文件为：`.scratch/<功能标识>/spec.md`
- 实施问题每个文件单独保存于：`.scratch/<功能标识>/issues/<NN>-<标识>.md`；从 `01` 开始编号，禁止合并为一个总 tickets 文件
- 分诊状态记录在问题文件开头附近的 `Status:` 行；角色字符串见 `triage-labels.md`
- 评论和沟通记录追加在文件末尾的 `## Comments` 标题下

## 当技能要求“发布到问题跟踪器”时

在 `.scratch/<功能标识>/` 下创建新文件；目录不存在时一并创建。

## 当技能要求“获取相关 ticket”时

读取所引用路径的文件。用户通常会直接提供路径或问题编号。

## 路径发现操作

供 `/wayfinder` 使用。**地图**文件为每个 ticket 对应一个**子文件**的索引。

- **地图**：`.scratch/<工作项>/map.md`，正文包括 Notes、Decisions-so-far 和 Fog。
- **子 ticket**：`.scratch/<工作项>/issues/NN-<标识>.md`，从 `01` 开始编号，正文写明问题。文件开头的 `Type:` 记录类型（`research`、`prototype`、`grilling` 或 `task`），`Status:` 记录 `claimed` 或 `resolved`。
- **阻塞**：在文件开头附近使用 `Blocked by: NN, NN`。列出的所有文件均为 `resolved` 时，ticket 才会解除阻塞。
- **前沿**：扫描 `.scratch/<工作项>/issues/`，寻找未解决、未阻塞且未认领的文件；按编号最小者优先。
- **认领**：开始工作前，将 `Status:` 更新为 `claimed` 并保存。
- **解决**：在 `## Answer` 下追加答案，将 `Status:` 更新为 `resolved`，然后将上下文指针（摘要与链接）追加至 `map.md` 的 Decisions-so-far。
