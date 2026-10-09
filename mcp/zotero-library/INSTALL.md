# 安装与诊断

下载或克隆仓库后，进入 `mcp/zotero-library/`。在本目录创建独立 `.venv`，无需修改全局 Python。

另一台 Windows 电脑准备 Python 3.12 或更新的兼容版本和 Codex。在服务目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$taskRoot = (Get-Location).Path
codex mcp add zotero-library --env PYTHONUTF8=1 -- "$taskRoot\.venv\Scripts\python.exe" -X utf8 "$taskRoot\server.py"
```

在 `%USERPROFILE%\.codex\config.toml` 的 `[mcp_servers.zotero-library]` 段中设置：

```toml
startup_timeout_sec = 20
tool_timeout_sec = 180
```

只在 `[mcp_servers.zotero-library]` 主段设置，不能误放到其 `[mcp_servers.zotero-library.env]` 子段。

打开 Windows“凭据管理器 → Windows 凭据 → 添加普通凭据”，按 README 中的名称写入 Zotero 和坚果云凭据，然后重启 Codex。密码不要贴进聊天或命令行。

诊断（只输出是否可用，不输出凭据值）：

```powershell
.\.venv\Scripts\python.exe -X utf8 server.py --doctor
.\.venv\Scripts\python.exe -X utf8 server.py --sync
.\.venv\Scripts\python.exe -X utf8 smoke_mcp.py
.\.venv\Scripts\python.exe -X utf8 smoke_mcp.py --live
# 可选：用你库中的 Zotero 条目 key 验证 PDF 下载和读取
.\.venv\Scripts\python.exe -X utf8 smoke_mcp.py --live --item-key YOURKEY1
```

`smoke_mcp.py` 默认只测试本地协议和分类目录，不需要凭据或文献缓存。`--live` 增加真实库同步与检索；提供 `--item-key` 时才下载指定论文 PDF，不依赖任何预置私有条目。

若在隔离的沙箱账户中运行，可能读不到当前 Windows 用户的凭据。应让 MCP 由保存凭据的 Windows 用户运行，不必把密码改存到配置文件。

单元测试（开发时使用；需安装 pytest）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

卸载连接可运行 `codex mcp remove zotero-library`；仅移除 Codex 注册，不删除云端或本地文献。不要在仍需使用服务时移动代码目录或删除 `.venv`。
