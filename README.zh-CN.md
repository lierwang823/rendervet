# RenderVet

**在交付前给批量图片、音频和视频做一次本地体检：找出漏号、损坏、重复、旧文件和规格错误。**

[English](README.md)

![RenderVet 演示报告](docs/hero.svg)

批量生成或渲染经常会“看起来完成了”：目录里有很多文件，但其中一项漏号、一个
PNG 已损坏、两个结果完全相同，或者旧文件混进了新批次。RenderVet 使用一份简短的
TOML 契约检查目录，并生成：

- 可离线查看的 HTML 图形报告；
- 可供 CI 和自动化读取的 JSON 报告；
- 只包含失败项和缺失编号的重试清单。

RenderVet 完全本地运行，不上传、不删除、不移动、不重命名素材，也不会自动执行重试。

## 一分钟体验

```bash
git clone https://github.com/lierwang823/rendervet.git
cd rendervet
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/rendervet demo --force --open
```

演示会生成一组完全原创的几何测试图，并故意制造漏号、损坏、错误尺寸、旧文件、错误
扩展名和重复内容。命令会以退出码 `1` 结束，因为它正确发现了失败项。

## 检查自己的批次

```bash
rendervet init my-render-job --name "产品发布素材"
```

编辑生成的 `rendervet.toml`：

```toml
version = 1

[project]
name = "产品发布素材"
root = "outputs"
report_dir = ".rendervet"

[[batch]]
id = "hero-images"
glob = "hero_*"
kind = "image"
expected_count = 24
sequence_regex = 'hero_(\d+)'
sequence_start = 1
sequence_end = 24
allowed_extensions = [".png"]
min_bytes = 1024
width = 1536
height = 1024
duplicates = "error"
```

把文件放进 `outputs` 后运行：

```bash
rendervet check my-render-job/rendervet.toml --open
```

## 第一版支持

- 文件数量与连续编号检查；
- 重复编号与 SHA-256 完全重复检查；
- PNG、JPEG、GIF、WebP、BMP 结构和尺寸检查；
- 文件大小、扩展名和生成时间检查；
- 通过 `ffprobe` 检查音视频时长、尺寸和音轨；
- 离线 HTML、JSON 与 `retry-manifest.json`；
- 安全拒绝符号链接、越界 glob 和危险报告目标。

RenderVet 不会判断画面是否“好看”，也不声称理解生成提示词。当前只检查完全相同的
文件，不检查视觉近似；黑屏、静音和感知重复属于后续路线图。

完整配置见 [docs/contract.md](docs/contract.md)，参与开发见
[CONTRIBUTING.md](CONTRIBUTING.md)。项目采用 [MIT License](LICENSE)。
