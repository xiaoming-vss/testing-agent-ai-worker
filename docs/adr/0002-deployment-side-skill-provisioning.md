# 技能包由部署侧预置,worker 移除技能同步

worker 原来在每个任务开始时从平台下载项目技能包并解压到 workspace 的 `skills/` 目录。这是任务执行路径中唯一的共享可变状态,并行化后必须按项目加锁才能安全。现决定:技能包改由部署侧预置(按项目放进 `workspaces/project-{project_id}/skills/`,与原同步逻辑的落点一致),worker 彻底删除同步代码(`PlatformProjectSkillSource`、各执行器的 `skill_syncer` 及相关配置)。移除后 workspace 对并发执行只读(inputs 按 task 隔离、sessions 按 run 隔离),并行执行无需任何锁。

## Consequences

- 部署侧必须保证项目技能在任务派发前就位;技能更新需要部署侧重放,worker 不再感知版本变化。
- 平台的项目技能查询接口(`project_skills_path`)worker 不再调用,成为平台单侧接口。
