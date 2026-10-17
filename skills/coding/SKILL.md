---
name: coding
description: 在受控工作区内实现、检查并交付小型代码修改
allowed-tools:
  - list_dir
  - read_file
  - write_file
  - replace_file
  - bash
  - present_files
---

# Coding

1. 修改前先读取目标文件和相邻约定，保持改动范围最小。
2. 新文件使用 `write_file`；覆盖已有文件使用 `replace_file` 并接受审批。
3. 需要执行命令时使用 Docker 中的 `bash`，列出预期证据文件。
4. 只把验证过的输出登记为产物，并如实报告失败。
