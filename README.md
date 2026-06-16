# 多功能工具箱

本地运行的多功能工具箱，**双版本可用**：

- **Web 版**：Flask + 浏览器，跨平台，启动后自动打开浏览器
- **Desktop 版**：PySide6 原生窗口（Qt6），不启 Flask、不开浏览器，双击即弹原生窗口

两版共用同一套后端与 `data/` 数据目录，任务历史跨版本连续。目前包含视频下载、视频转 MP3、视频转码、系统信息四个功能模块，后续持续迭代。

## 功能

| 模块       | 说明                                                                                                                                    |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| 视频下载   | 从网页提取视频并下载，支持微信公众号（腾讯视频 iframe）、百度新闻视频（好看视频侧拉直链）、mpvideo 直链、HTML5 `<video>`、mp4/m3u8 直链 |
| 视频转 MP3 | 上传视频文件，ffmpeg 转 192 kbps MP3，带进度条                                                                                          |
| 视频转码   | 上传视频文件，转 H.264 / H.265 / VP9，可选分辨率（1080p/720p/480p）与质量档位（CRF 18/23/28）                                           |
| 系统信息   | 显示 OS / Python / CPU / ffmpeg / yt-dlp 版本 / 存储用量 / 功能列表 / 软件更新                                                          |

特性：
- 任务历史持久化（`data/downloads/history.json`、`data/audio/history.json`、`data/video_transcode/history.json`），跨重启保留
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

# Web 版（浏览器 UI）
python app.py
# 默认 http://localhost:8080，可用 PORT 覆盖
PORT=8090 python app.py

# Desktop 版（原生窗口）
python main.py
```

### 使用打包版（Windows）

到 [Releases](../../releases) 按需下载：

- `toolbox-vX.Y.Z-windows-web.zip` —— 浏览器版，解压双击 `toolbox-web.exe`，启动后自动开浏览器
- `toolbox-vX.Y.Z-windows-desktop.zip` —— 原生窗口版，解压双击 `toolbox-desktop.exe`，直接弹原生窗口

两个 zip 都捆绑了 `ffmpeg.exe` 和 `ffprobe.exe`，无需额外安装。
两个版本的「检查更新」各自只看自己通道的 Release 资产，互不串扰。

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

### 视频转码

1. 切到「视频转码」tab
2. 选择本地视频文件
3. 选输出格式（H.264 / H.265 / VP9）、分辨率（保持原分辨率 / 1080p / 720p / 480p）、质量（高质 / 平衡 / 压缩）
4. 点「开始转码」，ffmpeg 实时进度
5. 完成后点「打开所在目录」获取文件

### 系统信息

切到「系统」tab，可查看：
- 操作系统 / 架构 / CPU 核数 / Python 版本
- 应用版本 / ffmpeg / yt-dlp 版本
- 下载目录、音频目录、转码目录（均在 `data/` 下）的文件数和总大小、磁盘剩余空间
- 功能列表（点「前往」直接切到对应 tab）
- 软件更新（点「检查更新」，有新版才会出现「立即更新」按钮）

## 项目结构

```
.
├── app.py                  # Web 版入口（Flask）
├── main.py                 # Desktop 版入口（PySide6）
├── version.txt             # 当前版本号（双版本共用）
├── variant-web.txt         # bundle 时改名 variant.txt，标识 web 通道
├── variant-desktop.txt     # bundle 时改名 variant.txt，标识 desktop 通道
├── requirements.txt        # 依赖（含 pyside6）
├── modules/                # 后端，双版本共用
│   ├── video_dl.py         # 视频提取与下载
│   ├── audio_extract.py    # 视频转 MP3
│   ├── video_transcode.py  # 视频转码
│   ├── system_info.py      # 系统信息收集
│   ├── file_ops.py         # reveal_in_file_manager 等工具
│   ├── updater.py          # 自动更新（含 variant 检测）
│   └── channels_dl.py      # 视频号解析（未接入 UI）
├── desktop/                # Desktop UI（PySide6）
│   ├── main_window.py      # QMainWindow + QTabWidget
│   ├── video_tab.py / audio_tab.py / transcode_tab.py / system_tab.py
│   ├── widgets.py          # TaskCard / VideoCard / Dropzone
│   └── style.qss           # 暗色 Qt 样式
├── templates/index.html    # Web 版单页面
├── static/                 # Web 版 JS / CSS
├── data/                   # 产物与历史（gitignored，自动生成，双版本共用）
│   ├── downloads/          # 视频下载
│   ├── audio/              # MP3 转换
│   ├── video_transcode/    # 视频转码
│   └── _uploads/           # Web 版上传临时目录
└── docs/
    ├── design.md           # 架构与 API 设计
    ├── progress.md         # 版本进度
    └── requirements.md     # 需求清单
```

更多设计与进度细节见 [`docs/`](docs/)。

## 构建

CI 在打 tag 推送时**一次跑两次 PyInstaller**，分别打 Web / Desktop 两个 exe，捆绑 ffmpeg 后生成两个 zip：

```bash
# 修改 version.txt 后
git commit -am "bump version"
git tag v1.4.0
git push --tags
```

`.github/workflows/build.yml` 会在 `windows-latest` 上：
1. 跑 PyInstaller 打 `toolbox-web.exe`（含 templates/ + static/ + variant-web.txt → variant.txt）
2. 跑 PyInstaller 打 `toolbox-desktop.exe`（含 desktop/style.qss + variant-desktop.txt → variant.txt）
3. 各自捆绑 ffmpeg.exe / ffprobe.exe 后生成 `toolbox-vX.Y.Z-windows-{web,desktop}.zip`
4. 自动创建 Release 上传两个 zip

## 技术栈

- 后端：Python（modules/，双版本共用）
- Web 版：Flask + HTML + Tailwind CSS（CDN）+ 原生 JS
- Desktop 版：PySide6（Qt6 官方 Python 绑定），无 Flask、无 WebView
- 视频下载：yt-dlp（Python 库调用）
- 音视频转码：ffmpeg（libx264 / libx265 / libvpx-vp9 / libmp3lame / libopus）
- 打包：PyInstaller（双 zip）
- CI/CD：GitHub Actions

## 已知限制

- PyInstaller 打的 exe 在 Windows Defender 下偶有误报，计划换 Nuitka
- 视频号解析模块 `channels_dl.py` 依赖 Cookie，尚未接入 Web UI
- 音频码率固定 192 kbps，未暴露选项
- 视频转码未启用硬件加速（NVENC / VideoToolbox）
- 百度视频直链 `auth_key` 有时效，过期的历史链接无法继续下载
