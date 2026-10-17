---
name: research
description: 整理本地资料，核对事实并给出带依据的研究摘要
allowed-tools:
  - list_dir
  - read_file
  - lookup_note
  - write_file
  - present_files
---

# Research

1. 先列出已有资料，再读取与问题直接相关的文件。
2. 区分资料中的事实、自己的推断和仍缺少的信息。
3. 输出简洁摘要；引用本地资料时写清文件路径。
4. 需要交付报告时写入 `outputs/`，完成后调用 `present_files`。
