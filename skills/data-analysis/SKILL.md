---
name: data-analysis
description: 分析上传的 CSV，生成可复查的结论、图表和报告
allowed-tools:
  - list_dir
  - read_file
  - write_file
  - replace_file
  - bash
  - present_files
---

# Data Analysis

1. 先检查 CSV 的列名、数据类型、缺失值和样本范围。
2. 把分析脚本保存在 `workspace/`，不要只给出无法复现的口头计算。
3. 使用 Docker 执行脚本，在 `outputs/` 生成 Markdown 报告和 PNG 图表。
4. 报告中说明口径、异常值和局限，最后调用 `present_files`。
