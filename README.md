# Han-gpt-skill
The chatgpt skill for multiple pc to synchronization

## 科研绘图：lab-plot-style

[`lab-plot-style`](lab-plot-style/) 用于绘制或统一实验曲线的版式，适合时域波形、幅频谱、点线图和多组对比图。坐标范围随数据调整，默认使用白底黑框、向内刻度，导出 600 dpi PNG 和矢量 PDF。

在另一台电脑上，将整个 `lab-plot-style/` 目录复制到个人 skills 目录（默认 `~/.codex/skills/`）。安装后，可以这样调用：

> 用 `$lab-plot-style` 把三组实验数据画在同一张图里，用三种颜色区分，保留原始数据点和单位。

技能只规定绘图格式；采样率、标定关系和数据处理方法由各实验单独指定。[技能说明](lab-plot-style/SKILL.md) · [Matplotlib 样式文件](lab-plot-style/assets/lab.mplstyle)

## 文献库 MCP

[Zotero + 坚果云文献库 MCP](mcp/zotero-library/README.md) 为 Codex 提供文献检索、摘要读取、PDF 下载与按页阅读、增量同步及知识目录查询。

- [安装与诊断](mcp/zotero-library/INSTALL.md)
- 支持 Windows，凭据保存于各设备的 Windows 凭据管理器。
- 源码和分类目录可以跨设备复用；凭据、文献缓存、PDF 和私人阅读记录不随仓库上传。
- `mcp/` 是独立服务目录，不作为 skill 安装。
