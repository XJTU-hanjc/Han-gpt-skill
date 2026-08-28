---
name: token-economy
description: Reduce token usage while preserving correctness for research and code tasks. Use when the user asks to 减少 token 消耗, 省 token, 低上下文, 简洁处理, 高信号摘要, 大文件处理, 长日志分析, 论文/PDF阅读, 文献综述, 科研数据分析, 代码仓库理解, bug定位, 测试定位, or when inputs are large and only focused evidence is needed.
---

# Token Economy

## Core Rule

Minimize context, not rigor. First locate the smallest useful evidence, then read only what is needed to answer or act safely.

## Workflow

1. State a compact intent: task, likely artifact type, and what evidence is needed.
2. Inventory before reading: list filenames, headings, symbols, tests, metadata, or log timestamps.
3. Search before opening: prefer `rg`, table of contents, abstracts, section headers, function names, error strings, and config keys.
4. Read narrow slices: open only relevant chunks with nearby context; avoid pasting whole files, full papers, full logs, or repeated outputs.
5. Summarize progressively: keep a short working summary of findings and only expand when the user asks.
6. Stop once the success criterion is met; do not continue broad exploration for completeness unless risk requires it.

## Research Tasks

For papers, PDFs, notes, datasets, and experiment records:

- Extract only the user-relevant parts: research question, method, data, experiments, metrics, results, limitations, and reproducibility details.
- Use title, abstract, conclusion, figure/table captions, and section names as a map before deeper reading.
- For literature review, group by claim, method, dataset, or limitation instead of summarizing every paragraph.
- For data analysis, inspect schema, row/column names, dimensions, missingness, and sample rows before loading or describing large data.
- For long experiment logs, search for error markers, metric names, timestamps, checkpoint names, and final summaries first.

## Code Tasks

For repositories, bugs, features, tests, and reviews:

- Map the repo first with `rg --files`, manifests, entrypoints, test folders, and config files.
- Locate relevant symbols with `rg`, language-aware search, or file names before opening files.
- Read the smallest caller/callee context needed to understand behavior; avoid unrelated refactors.
- Prefer existing tests, fixtures, and failing error text as anchors.
- When reporting, include only the key files, line references, behavior, and verification result.

## Output Style

- Default to concise Chinese unless the user requests another language.
- Put conclusion first, then minimal evidence.
- Use bullets only when they improve scanning.
- Do not paste large code, logs, papers, or tables; quote short snippets only when exact text matters.
- If more detail is available, say what can be expanded instead of expanding automatically.
- During long work, send short progress updates with the current finding and next narrow action.

## Image Constraint

When material includes images, figures, screenshots, scans, or plots, do not view images or call visual inspection tools. Use non-visual alternatives: text layer, OCR text already available from tools, filenames, captions, alt text, surrounding prose, metadata, logs, source data, or user-provided descriptions. If the answer depends on unseen visual content, state the limitation briefly and ask for text/OCR/description.

## Default Refusal to Waste Context

Avoid these unless explicitly needed:

- Whole-file reads of large files.
- Full-document translation before triage.
- Repeating command outputs already summarized.
- Loading generated artifacts, vendored code, build outputs, or dependency folders.
- Explaining obvious background knowledge when the user needs the result.
