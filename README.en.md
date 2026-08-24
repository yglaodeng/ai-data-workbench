# AI Data Workbench

A local-first AI data workbench for turning natural-language goals into traceable Excel, CSV, TSV, and JSON transformations. Users preview the plan and impact before approval; original files remain read-only and execution creates derived outputs.

[中文说明](./README.md) · [Roadmap](./ROADMAP.md) · [Report an issue](https://github.com/yglaodeng/ai-data-workbench/issues)

![AI Data Workbench](./docs/workbench.jpg)

## Why this project exists

Many spreadsheet tasks require more than a one-off script: users need to describe the result they want, inspect the proposed operations, protect source files, and trace every generated output. This prototype focuses on that controlled workflow.

## What it does

- Accepts up to five Excel, CSV, TSV, or JSON files, including multi-sheet workbooks.
- Supports field selection, renaming, sorting, type conversion, and missing-value handling.
- Supports deduplication, filtering, splitting, merging, calculated columns, and aggregation.
- Performs vertical concatenation and single-key or multi-key joins.
- Shows before-and-after previews, field profiles, affected rows, and risk notes.
- Uses an approval token that becomes invalid when the plan changes.
- Exports CSV, Excel, and joined results while preserving source workbooks.
- Stores source files as read-only inputs and creates derived files for execution results.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open `http://127.0.0.6:8006/`.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Data and security boundaries

- The repository contains no real business workbooks, analysis history, credentials, or production records.
- Runtime records and workspaces under `data/` are excluded by `.gitignore`.
- Connecting to a business system is not part of this public prototype.
- The application does not make autonomous business decisions.

## Contributing

Read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening an issue or pull request. Planned work and known boundaries are listed in [ROADMAP.md](./ROADMAP.md).

## License

[MIT](./LICENSE)
