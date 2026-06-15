# 多功能工具箱

本地运行的 Web 工具箱，浏览器操作。目前包含视频下载、视频转 MP3、系统信息三个功能模块，后续持续迭代。

## 功能

| 模块       | 说明                                                                                                                                    |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| 视频下载   | 从网页提取视频并下载，支持微信公众号（腾讯视频 iframe）、百度新闻视频（好看视频侧拉直链）、mpvideo 直链、HTML5 `<video>`、mp4/m3u8 直链 |
| 视频转 MP3 | 上传视频文件，ffmpeg 转 192 kbps MP3，带进度条                                                                                          |
| 系统信息   | 显示 OS / Python / CPU / ffmpeg / yt-dlp 版本 / 存储用量 / 功能列表 / 软件更新                                                          |

特性：
- 任务历史持久化（`downloads/history.json`、`downloads/audio/history.json`），跨重启保留
- 完成的文件可直接调起系统文件管理器高亮选中（Win `explorer /select,` / macOS `open -R` / Linux `xdg-open`）
- 软件自动更新（依赖 GitHub Releases，**仓库需公开**）

## 快速开始

### 从源码运行

```bash
git clone <repo>
cd toolbox
pip install -r requirements.txt

# 系统需安装 ffmpeg 和 ffprobe 并放入 PATH
# Debian/Ubuntu: sudo apt install ffmpeg
# macOS:         brew install ffmpeg
# Windows:       https://www.gyan.dev/ffmpeg/builds/

python app.py
# 默认 http://localhost:8080，可用 PORT 覆盖
PORT=8090 python app.py
```

打开浏览器访问 `http://localhost:<port>`。

### 使用打包版（Windows）

到 [Releases](../../releases) 下载 `toolbox-vX.Y.Z-windows.zip`，解压后双击 `toolbox.exe`。
捆绑了 `ffmpeg.exe` 和 `ffprobe.exe`，无需额外安装。

## 使用说明

### 视频下载

1. 切到「视频下载」tab
2. 粘贴网页链接（微信公众号文章、`mbd.baidu.com` 视频页等）
3. 点「提取视频」，列出所有可用源（百度源会列出多路清晰度）
4. 点「下载」，进度条显示状态
5. 完成后点卡片右下角「打开所在目录」直接定位到文件

### 视频转 MP3

1. 切到「音频提取」tab
2. 选择本地视频文件
3. 点「开始转换」，ffmpeg 自动转码为 192 kbps MP3
4. 完成后点「打开所在目录」获取文件

### 系统信息

切到「系统」tab，可查看：
- 操作系统 / 架构 / CPU 核数 / Python 版本
- 应用版本 / ffmpeg / yt-dlp 版本
- 下载目录与音频目录的文件数和总大小、磁盘剩余空间
- 功能列表（点「前往」直接切到对应 tab）
- 软件更新（点「检查更新」，有新版才会出现「立即更新」按钮）

## 项目结构

```
.
├── app.py                  # Flask 入口
├── version.txt             # 当前版本号
├── requirements.txt
├── modules/
│   ├── video_dl.py         # 视频提取与下载
│   ├── audio_extract.py    # 视频转 MP3
│   ├── system_info.py      # 系统信息收集
│   ├── updater.py          # 自动更新
│   └── channels_dl.py      # 视频号解析（未接入 Web UI）
├── templates/index.html    # 单页面
├── static/                 # JS / CSS
├── downloads/              # 下载产物与历史（gitignored）
└── docs/
    ├── design.md           # 架构与 API 设计
    ├── progress.md         # 版本进度
    └── requirements.md     # 需求清单
```

更多设计与进度细节见 [`docs/`](docs/)。

## 构建

CI 在打 tag 推送时自动构建 Windows exe 并发 Release：

```bash
# 修改 version.txt 后
git commit -am "bump version"
git tag v1.2.0
git push --tags
```

`.github/workflows/build.yml` 会在 `windows-latest` 上用 PyInstaller 打包，捆绑 ffmpeg，并自动创建 Release。

## 技术栈

- 后端：Python + Flask
- 前端：HTML + Tailwind CSS（CDN）+ 原生 JS
- 视频下载：yt-dlp（Python 库调用）
- 音频转码：ffmpeg + libmp3lame
- 打包：PyInstaller
- CI/CD：GitHub Actions

## 已知限制

- PyInstaller 打的 exe 在 Windows Defender 下偶有误报，计划换 Nuitka
- 视频号解析模块 `channels_dl.py` 依赖 Cookie，尚未接入 Web UI
- 音频码率固定 192 kbps，未暴露选项
- 百度视频直链 `auth_key` 有时效，过期的历史链接无法继续下载
