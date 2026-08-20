# AI 数据工作台

用自然语言描述目标，经过人工确认后处理 Excel、CSV、TSV 或 JSON，并输出可追溯的派生结果。

**English:** A local-first AI data workbench for natural-language goals, multi-file analysis, approval gates, traceable transformations, and derived Excel/CSV outputs. Original files remain read-only.

[查看源码](https://github.com/yglaodeng/ai-data-workbench) · [提交问题或建议](https://github.com/yglaodeng/ai-data-workbench/issues)

![AI 数据工作台](./docs/workbench.jpg)

## 30 秒了解项目

- **输入：** 最多 5 个 Excel、CSV、TSV 或 JSON 文件，可包含多个工作表
- **过程：** 用自然语言说明目标，预览处理计划和影响范围，再由人工确认执行
- **输出：** 生成可追溯的派生文件，不覆盖原始文件
- **当前状态：** 可在本地运行的原型，不连接生产账号、密钥或数据库

## 当前能力

- 最多上传 5 个文件，支持多工作表
- 字段选择、重命名、排序、类型转换和空值处理
- 去重、筛选、拆分、合并、计算列和分组汇总
- 多文件纵向合并和单键或多键关联
- 处理前后预览、字段画像、影响行数和风险提示
- 预览确认令牌门禁，计划变化后旧预览自动失效
- CSV、Excel 和保留原工作表的关联结果导出
- 原始文件只读保存，执行只生成派生文件

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

打开 `http://127.0.0.6:8006/`。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 数据边界

- 仓库不包含真实业务文件、分析记录和历史任务。
- `data/` 中的运行记录和工作区由 `.gitignore` 排除。
- 连接业务系统功能只接受用户提供的安全导出快照，不读取生产账号、密钥或数据库。
- 本项目不执行自主业务决策。

## 许可

当前仓库用于公开展示和学习参考，暂未附加开源许可证。
