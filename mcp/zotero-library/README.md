# 我的 Zotero 文献库 MCP

用于本机 Codex 的只读文献库服务。Zotero 提供条目、摘要、笔记和分类；坚果云 WebDAV 提供 PDF。后续增加文献无需重建服务。

## 平时怎么用

在 Codex 中直接说：

- “用 zotero-library 同步文献库，看看最近增加了哪些文献。”
- “在我的文献库中查找 PVC 凝胶驱动器，先看摘要，再读相关 PDF。”
- “列出 2024 年之后的柔性推进论文，比较研究问题与结论。”
- “按我的 02 分类：解释机理、预测性能、结构优化、实时控制，整理这几篇论文。”
- “把这篇 PDF 给我。”

首次配置后，需要重启 Codex 或刷新 MCP 连接，使新工具加载。这个操作不会重新下载整个库。

## 新增文献如何生效

1. 正常把文献放入 Zotero，并让 Zotero 完成云端数据同步和坚果云附件同步。
2. 检索、读取条目或 PDF 时，若距离上次检查超过 5 分钟，服务会检查并增量更新索引。
3. 刚添加完就需要使用时，直接说“立即同步文献库”，会强制检查，不受 5 分钟间隔影响。

这是使用时检查，不是后台定时监控。新增和修改会更新索引；永久删除会从索引移除；回收站条目及其子附件不会出现在检索结果里。同步失败保留上一完整索引，并在结果中标明旧数据和同步错误。

新增文献可以被检索和读取，但不会自动拥有阅读结论。需要 Codex 调用摘要/PDF 工具完成阅读后再分析。全文 PDF 只在需要时下载，不会每次扫描或下载全库。

## 工具

| 工具 | 用途 |
|---|---|
| library_status | 查看本地索引时间、数量、PDF 缓存状态 |
| sync_library | 立即增量同步；full=true 可完整重建索引 |
| search_library | 检索标题、作者、摘要、DOI、期刊和标签；支持年份、Zotero 分类及入库日期 |
| get_item | 当前摘要、PDF 附件、可选笔记、历史阅读记录 |
| list_collections | Zotero 实际分类及父子关系 |
| get_pdf | 下载或复用 PDF，返回本地文件路径 |
| read_pdf | 按页提取 PDF 文字 |
| search_pdf | 在单篇 PDF 中定位关键词及页码 |
| get_knowledge_map | 读取已确认的七领域三级建议目录 |

搜索使用词面匹配，空格分词取 AND；必要时让 Codex 分别使用中文和英文关键词。全文关键词搜索是单篇范围，不是全库语义搜索。扫描件、公式、图表不保证能由文字提取器读出；结果会提示空文字层，不能将“无文本”解释为“没有研究内容”。

## 分类目录与可选阅读记录

- 2026-09-30 确认的分类目录：7 个一级、26 个二级、78 个三级主题。
- 仓库仅包含分类目录，不包含私人文献或逐篇摘要阅读记录。可选的本地 `knowledge/reading-notes.json` 以 Zotero key 关联历史阅读笔记；没有此文件也能正常检索和读取文献。
- 条目摘要变化时，会提示历史阅读记录可能已经过期。
- 分类目录是建议体系，不等于已经在 Zotero 中执行分类。MCP 不自动修改云端分类、标签、笔记或文献。

## 凭据与运行方式

服务由 Codex 以 STDIO 启动，无需开放端口或租用服务器。凭据只从当前 Windows 用户的凭据管理器读取：

- `Codex.Zotero`：用户名是数字 Zotero User ID；密码是 Zotero API key。
- `Codex.Jianguoyun`：用户名是坚果云账号；密码是 WebDAV 应用密码。

只请求 `https://api.zotero.org` 和 `https://dav.jianguoyun.com/dav/zotero/`。只使用 GET，不跟随重定向。不会将凭据存进源码、MCP 配置或运行日志。PDF 按 Zotero MD5 校验，缓存保存在本目录 `data/`，其中含私人文献资料，不要公开上传。

本版支持当前个人 Zotero 文献库和坚果云同步附件；群组库、仅链接到其他本地路径的附件需另行适配。没有额外调用 OpenAI API；由 Codex 自己阅读和分析工具返回的资料。

## 换电脑

在另一台 Windows 电脑下载或克隆本仓库，进入 `mcp/zotero-library/`，创建 Python 环境并安装依赖，再配置同名两条 Windows 凭据并注册 MCP。首次使用会从云端重建索引；不需要复制旧电脑的 `.venv/` 或 `data/`。历史阅读笔记不会通过 GitHub 同步，需要时单独安全迁移。每台电脑使用独立索引，云端 Zotero 和坚果云是共同来源。

技术安装命令见 `INSTALL.md`。日常使用无需手工运行脚本。

## 实现依据

- [OpenAI 官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Zotero Web API 增量同步](https://www.zotero.org/support/dev/web_api/v3/syncing)
- [MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)

SDK 固定在受维护的 v1 分支并锁定版本，避免随 v2 接口变化而意外升级。升级依赖后应重新运行单元测试和真实连接测试。
