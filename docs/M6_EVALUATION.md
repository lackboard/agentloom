# M6 真实评测报告

评测时间：2026-10-15。模型为本机 `config.yaml` 选择的
`openai_compatible / gpt-5.6-sol`，temperature 为 0。密钥、模型响应原始日志和运行数据库不提交。

## 固定 30 题

- 任务定义：[fixed_tasks.json](../backend/evaluations/fixed_tasks.json)
- 任务集 SHA-256：`5df9127b7197e30794f834a7921c94f5e668ef09a728542f8d5ddd9225ad5b4b`
- 分布：文件/代码 10、数据 8、检索/MCP 6、委派 6。
- 每题在运行前声明最终文本、工具、产物、子任务数或人工复核条件。
- 每题创建独立线程，走正式 HTTP 入场、后台图、审批恢复、工具账本、消息和产物查询。

| 指标 | 结果 |
| --- | ---: |
| 自动通过 | 25 / 30（83.3%） |
| 待人工复核 | 3 / 30（10.0%） |
| 自动失败 | 2 / 30（6.7%） |
| 人工复核后完成 | 28 / 30（93.3%） |
| 要求产物的任务交付率 | 100% |
| 模型提出后进入工具账本的调用比例 | 100% |
| Wall / 活跃时间 | 616.11s / 616.11s |
| Input / output Token | 145,364 / 8,484 |
| Usage 完整 | true |
| 费用 | N/A；配置没有可审计单价，不根据模型名猜测 |

人工复核结论：

- `FC-09` 通过：`read_file` 返回 `FILE_NOT_FOUND`，回答明确说明文件不存在，没有编造正文。
- `DA-08` 通过：回答和产物都说明 `oops` 是坏值，并明确只对 10、20 求和得到 30。
- `AG-06` 通过：一个 child 返回 7，另一个返回 `REFERENCE_NOT_FOUND`，Lead 同时保留两者。

两个自动失败必须保留：

- `RT-02` 回答“只能有 **1 个写者**”，预注册条件要求字面出现“一个写者”。事实正确但规则未命中。
- `RT-06` 回答“未找到任何匹配项”，预注册条件只接受“count 为 0 / count=0 / 0 条 / 没有匹配”。事实正确但规则未命中。

这两项显示字符串包含评分会低估同义表达。为了避免看完输出再改答案，本次没有修改条件或重跑后覆盖结果。后续可在新版本任务集加入结构化断言或独立裁判，并保留任务集版本。

## 单 Agent / 多 Agent 对照

- 任务定义：[comparison_tasks.json](../backend/evaluations/comparison_tasks.json)
- 任务集 SHA-256：`267ad578cf7800564071301fdce29dc221c49fda0e294299e326bb683b8f3d2a`
- 两组固定同一模型、temperature、任务内容、工具 schema、MCP 数据和 Run 预算，只改变提示中的执行策略。
- 每组 2 题，各重复 3 次，共 12 个真实 Run。

| 策略 | 运行 | 完成率 | 平均 wall time ± 总体标准差 | 平均 Token ± 总体标准差 |
| --- | ---: | ---: | ---: | ---: |
| Lead 直接执行 | 6 | 100% | 8.40 ± 1.64s | 1,798 ± 74 |
| 委派子 Agent | 6 | 100% | 15.53 ± 5.15s | 2,898 ± 201 |

在这些短小任务上，委派没有提高完成率，平均延迟约增加 85%，Token 约增加 61%。原因是 child 需要独立模型回合，Lead 还要读取结构化结果。这个结论只适用于本任务集；不能外推到需要并行检索或上下文隔离的复杂任务。

## 实际失败与修复

第一次真实冒烟中 3 个 Run 均 `succeeded`，工具也真实执行，但评测读到的最终回答为空。真实 provider 返回内容块列表，
`runtime/projection.py` 当时只保存 `blocks`；fake 模型返回字符串，因此旧测试没有暴露问题。

修复后投影同时保存 LangChain 归一化的 `text` 和原始 `blocks`，增加内容块回归测试。同一三题重跑从 0/3 变为 3/3：`add`、MCP 来源和 child 结果都能在最终文本中观察。该失败记录保留在本机
`output/evaluation/m6-live-smoke.json`，修复后记录为 `m6-live-smoke-fixed.json`。

## 复现

```powershell
cd backend
uv run python -m agentloom.evaluation `
  --tasks evaluations/fixed_tasks.json `
  --expected-count 30 `
  --output ../output/evaluation/m6-live-fixed-30.json `
  --require-live

uv run python -m agentloom.evaluation `
  --tasks evaluations/comparison_tasks.json `
  --repeat 3 `
  --output ../output/evaluation/m6-live-comparison.json `
  --require-live
```

JSON 保存逐题最终文本、工具、产物、usage、失败检查和 runner error；Markdown 是摘要。`output/` 被忽略，避免提交可能包含用户数据的原始模型输出。
