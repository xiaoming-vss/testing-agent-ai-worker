# 功能测试输出校验与自动修复：模拟执行记录

本记录由实际 `generate_validated` 函数配合模拟模型生成，不调用远程模型。

默认每阶段／批次最多三次 Nanobot 调用（初次一次，修复两次）。Nanobot 内部的工具调用、网络重试或长度续写属于 SDK 自身行为，不计为新的 Worker 格式修复轮次。

## 第一次输出

```json
{
  "cases": [
    {
      "case_module": "登录",
      "case_title": "验证登录",
      "case_type": "功能测试",
      "priority": 2,
      "precondition": [],
      "test_steps": [
        "1. 登录"
      ],
      "expected_results": [
        "1. 展示首页"
      ]
    }
  ]
}
```

## 程序反馈

```json
[
  {
    "path": "$.cases[0].priority",
    "code": "literal_error",
    "expected": "Input should be '1', '2', '3' or '4'",
    "actual": "2"
  }
]
```

## 第二次输出与最终返回

```json
{
  "cases": [
    {
      "case_module": "登录",
      "case_title": "验证登录",
      "case_type": "功能测试",
      "priority": "2",
      "precondition": [],
      "test_steps": [
        "1. 登录"
      ],
      "expected_results": [
        "1. 展示首页"
      ]
    }
  ]
}
```

## 验证结果

- 调用次数：2。
- 第一次未提交产物；第二次通过严格校验。
- 修复请求含原始输入、Schema、上次输出和字段路径。
- 诊断记录包含两次响应和完整校验错误。
- 执行进度：`generating → repairing（1/2）→ 返回合格结果`。

## 运行时诊断位置

`<项目 workspace>/diagnostics/functional-output/<run_id>/<执行ID>/<stage>/batch-<批次>-<调用ID>/attempt-<轮次>.json`。目录与文件限制为当前用户访问；不写入模型连接配置或凭据。文件包含需求派生内容，仅用于本地排查。
