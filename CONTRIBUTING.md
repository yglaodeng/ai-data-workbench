# Contributing

感谢你关注 AI Data Workbench。

## 开始之前

- 请先搜索现有 Issues，避免重复提交。
- 功能建议应说明输入文件类型、自然语言目标、预期输出和可追溯要求。
- Bug 报告应使用合成或脱敏样例，并写明复现步骤和运行环境。
- 不要提交真实业务文件、客户资料、账号、Token、密钥、数据库快照或运行历史。

## Pull Request

1. 每个 PR 只解决一个明确问题。
2. 从 `main` 创建分支并保持最小改动。
3. 运行 `.venv/bin/python -m unittest discover -s tests -v`。
4. 在 PR 中写明测试对象、步骤、通过标准和实际结果。
5. 不得改变“原始文件只读、执行生成派生结果、人工确认后执行”的边界，除非先有公开讨论和明确验收方案。

English issues and pull requests are welcome. Use synthetic or redacted fixtures only.
