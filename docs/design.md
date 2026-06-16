# 设计文档

## 系统架构

**双轨入口**：同一套 `modules/`，跑在两个 UI 上：

```
┌────────────────┐         ┌────────────────┐
│   Web 版       │         │   Desktop 版   │
│  app.py+Flask  │         │ main.py+Qt     │
│  浏览器 UI     │         │ 原生窗口 UI    │
└───────┬────────┘         └────────┬───────┘
        │                           │
        └───────────┬───────────────┘
                    ▼
            ┌──────────────┐
            │   modules/   │  纯 Python 后端，跟 UI 完全解耦
            └──────────────┘
```

- **Web 版**（`app.py`）：Flask + 浏览器，跨平台，UI 在 `templates/` + `static/`
- **Desktop 版**（`main.py`）：PySide6（Qt6）原生窗口，无 Flask、无浏览器，UI 在 `desktop/`
- 两版本共用同一个 `data/` 目录与历史 JSON，**任务历史跨版本连续**

## 目录结构

```
toolbox/
├── app.py                    # Web 版入口（Flask）
├── main.py                   # Desktop 版入口（PySide6）
├── version.txt               # 当前版本号（双版本共用）
├── variant-web.txt           # 内容 "web"，打包时 bundle 为 variant.txt
├── variant-desktop.txt       # 内容 "desktop"，打包时 bundle 为 variant.txt
├── requirements.txt          # Python 依赖（含 pyside6）
├── modules/
│   ├── __init__.py
│   ├── video_dl.py           # 视频提取与下载 + 任务历史
│   ├── audio_extract.py      # 视频转 MP3 + 任务历史
│   ├── video_transcode.py    # 视频转码（H.264/H.265/VP9）+ 任务历史
│   ├── system_info.py        # 系统信息收集
│   ├── file_ops.py           # reveal_in_file_manager 等跨入口工具
│   ├── channels_dl.py        # 视频号解析（依赖 Cookie，未接入 Web）
│   └── updater.py            # 自动更新（含 variant 检测）
├── desktop/                  # Desktop UI
│   ├── main_window.py        # QMainWindow + QTabWidget
│   ├── video_tab.py          # 视频下载 tab
│   ├── audio_tab.py          # 音频提取 tab
│   ├── transcode_tab.py      # 视频转码 tab
│   ├── system_tab.py         # 系统信息 tab
│   ├── widgets.py            # TaskCard / VideoCard / Dropzone
│   └── style.qss             # 暗色 Qt 样式表
├── templates/
│   └── index.html            # Web 版单页面
├── static/
│   ├── style.css             # Web 版样式
│   └── app.js                # Web 版前端逻辑
├── data/                     # 应用产物根目录
│   ├── downloads/            # 视频下载产物
│   │   └── history.json      # 视频任务历史索引（自动生成，双版本共用）
│   ├── audio/                # MP3 转换产物
│   │   └── history.json      # 音频转换历史索引（自动生成，双版本共用）
│   ├── video_transcode/      # 转码产物
│   │   └── history.json      # 转码历史索引（自动生成，双版本共用）
│   └── _uploads/             # Web 版上传临时目录（自动清理）
├── docs/                     # 项目文档
└── .github/workflows/
    └── build.yml             # CI/CD：一次跑两次 PyInstaller，打两个 zip
```

## 运行配置

- 默认端口 `8080`，可用环境变量 `PORT` 覆盖：`PORT=8090 python3 app.py`
- 监听 `0.0.0.0`，可从局域网访问

## API 设计

### 视频下载

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/video/extract` | POST | 提取网页中的视频信息 |
| `/api/video/download` | POST | 开始下载任务（异步） |
| `/api/video/tasks` | GET | 查询下载任务状态 |

### 音频提取

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/audio/upload` | POST | 上传视频文件，启动 MP3 转换（multipart） |
| `/api/audio/tasks` | GET | 查询转换任务状态（支持 `?id=`） |
| `/downloads/audio/<filename>` | GET | 下载转换后的 MP3 文件 |

### 视频转码

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/video_transcode/upload` | POST | 上传视频文件，启动转码（multipart，附带 codec/quality/resolution） |
| `/api/video_transcode/tasks` | GET | 查询转码任务状态（支持 `?id=`） |
| `/downloads/video_transcode/<filename>` | GET | 下载转码后的视频文件 |

### 自动更新

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/update/check` | GET | 检查 GitHub Releases 是否有新版本 |
| `/api/update/start` | POST | 开始下载更新包 |
| `/api/update/progress` | GET | 查询更新下载进度 |

### 系统信息

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/system/info` | GET | 返回 OS / 工具版本 / 存储用量 / 功能列表 |

### 文件下载

| 接口 | 方法 | 说明 |
|---|---|---|
| `/downloads/<filename>` | GET | 下载已完成的文件 |
| `/downloads/audio/<filename>` | GET | 下载转换后的 MP3 |
| `/downloads/video_transcode/<filename>` | GET | 下载转码后的视频 |
| `/api/file/reveal` | POST | 在系统文件管理器中打开并选中文件（跨平台） |

**`/api/file/reveal`** 仅供本地用户使用 —— 文件已在 `data/` 下，
没必要再走浏览器下载。请求体 `{"kind": "video"\|"audio"\|"video_transcode", "id": "<task_id>"}`，
后端按 task_id 反查 `output_file` 后调用：
- Windows: `explorer /select,"<path>"`
- macOS: `open -R <path>`
- Linux: `xdg-open <父目录>`

路径必须解析后仍位于对应模块的 `DOWNLOAD_DIR` / `AUDIO_DIR` / `TRANSCODE_DIR` 之内，否则拒绝。

## Desktop 版架构

### 双入口共用后端

`modules/` 是纯 Python 函数集合，跟 Flask 完全解耦。Desktop 版直接 `import` 调用，
不走 HTTP。两版共用同一份 `data/` 与历史 JSON，**任务历史跨版本连续**。

### `start_task` 签名约定

`audio_extract.start_task()` 和 `video_transcode.start_task()` 接收磁盘路径而非 werkzeug
FileStorage：

```python
def start_task(input_path: str, source_name: str, owns_input: bool = True) -> str
```

- **Web 版** `owns_input=True`：FileStorage 先 `save_upload()` 到 `data/_uploads/`，
  转换完删掉这个临时上传
- **Desktop 版** `owns_input=False`：QFileDialog 直接拿到的是用户本地路径，
  不属于应用，转换完不删

worker / 历史 / 锁机制两边完全一致。

### `main.py` 入口

```python
if getattr(sys, "frozen", False):
    # 把捆绑的 ffmpeg.exe 同目录注入 PATH（与 app.py 相同处理）
    _exe_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = _exe_dir + os.pathsep + os.environ.get("PATH", "")

app = QApplication(sys.argv)
app.setStyleSheet(resource_path("desktop/style.qss").read_text(...))
win = MainWindow()   # QTabWidget 装 4 个 tab
win.show()
sys.exit(app.exec())
```

`resource_path()` 在 frozen 模式下从 `sys._MEIPASS` 读 QSS 等资源，
开发态从仓库根目录读。

### Qt 线程模型

后端模块的 worker 跑在 `threading.Thread` 里，**不能**直接动 Qt 控件。
通用做法：worker 把结果存 `self._pending_xxx`，主线程用
`QTimer.singleShot(0, self._apply_xxx)` 读取并刷新 UI。

`SystemTab._check_update` 用这个模式调 `updater.check_update()` —— 网络 IO 不阻塞 UI。
各 tab 的轮询 `QTimer` 1s 拉 `list_tasks()` / `get_progress()`，刷新 TaskCard。

### `variant.txt` 检测

`updater.get_variant()` 读 PyInstaller 捆绑的 `variant.txt`：

```python
def get_variant() -> str:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent
    vf = base / "variant.txt"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "dev"
```

`check_update()` 按当前 variant 过滤 GitHub Release asset：

| 当前 variant | 匹配 asset 名（子串） |
|---|---|
| `web` | `windows-web.zip` |
| `desktop` | `windows-desktop.zip` |
| `dev`（开发态） | 默认按 `web` 处理 |

CI 把 `variant-web.txt` / `variant-desktop.txt` 分别以 `variant.txt` 名字 bundle 进两个 exe，
因此同一 Release 下，两个版本的「检查更新」会各自只看自己的 zip。

### 资源命名约定

Release 资产命名：`toolbox-vX.Y.Z-windows-{variant}.zip`

- `toolbox-v1.4.0-windows-web.zip`
- `toolbox-v1.4.0-windows-desktop.zip`

匹配规则 `f"-{variant}"`，不会交叉匹配。

## 核心模块设计

### video_dl.py — 视频提取与下载

**特殊源旁路**（在通用解析之前优先匹配）：

- **百度新闻视频** `mbd.baidu.com/newspage/data/videolanding?nid=sv_xxx`
  落地页反爬极重，IP 层验证码拦截；改为从 URL 提取 `nid`，访问好看视频侧
  `haokan.baidu.com/v?vid=<nid>`，从 HTML 中正则匹配 4 路清晰度
  （360P/480P/720P/1080P）的 `vdept3.bdstatic.com` mp4 直链，把 `&`
  还原成 `&`，按上下文配对清晰度标签。

**通用提取策略**（按优先级）：

1. **腾讯视频 iframe** — 解析 `<iframe src="v.qq.com">` 中的 vid
2. **vid 正则兜底** — 匹配 HTML 中的 vid（排除广告上下文 gdt_ 等）
3. **mpvideo 直链** — 匹配 `mpvideo.qpic.cn` 域名
4. **HTML5 video 标签** — 解析 `<video>` / `<source>` 元素
5. **直接链接** — 匹配 `.mp4` / `.m3u8` URL

**下载策略**：

- 腾讯视频 → yt-dlp 库下载（带进度回调）
- 其他类型 → 先尝试 requests 直连，失败回退 yt-dlp

**任务管理 + 历史持久化**：

- 全局 `_tasks: dict[str, dict]`，线程锁 `_tasks_lock` 保护并发写入
- 每个任务字段：`id / status / progress / message / video / started_at / finished_at / output_file`
- 完成或失败时 `_persist()` 原子写入 `downloads/history.json`（临时文件 + rename）
- 模块导入时 `_load_history()` 自动恢复历史任务
- 最多保留 200 条，超出按 `started_at` 倒序裁剪
- `output_file` 来源：yt-dlp `progress_hooks` 的 `finished` 事件 / `_run_direct` 的本地路径

### audio_extract.py — 视频转 MP3

**流程**：

1. Flask 接收 multipart 上传 → 落到 `data/_uploads/<uuid>.<ext>`
2. 启动后台线程，调用 `ffprobe` 拿视频时长（秒）
3. 调用 `ffmpeg -nostats -progress pipe:1 -i in -vn -acodec libmp3lame -b:a 192k out.mp3`
4. 解析 `out_time_ms` 进度行，结合时长实时更新进度百分比
5. 成功后输出到 `data/audio/<basename>.mp3`，删除临时上传文件
6. 任务持久化到 `data/audio/history.json`（结构与 video_dl 一致）

任务字段：`id / status / progress / message / source_name / output_file / started_at / finished_at / duration_sec`

固定参数：192 kbps MP3，初版不暴露码率/采样率选项。

### video_transcode.py — 视频转码

**流程**：

1. Flask 接收 multipart 上传（含 `codec` / `quality` / `resolution` 表单字段）→ 落 `data/_uploads/<uuid>.<ext>`
2. 启动后台线程，调用 `ffprobe` 拿时长（秒）
3. 按 codec 构造 ffmpeg 命令：
   - `h264`: `libx264` + `-crf N -preset medium`，输出 `.mp4`，音频 `aac 128k`
   - `h265`: `libx265` + `-crf N -preset medium`，输出 `.mp4`，音频 `aac 128k`
   - `vp9`:  `libvpx-vp9` + `-crf N -b:v 0`，输出 `.webm`，音频 `libopus 128k`
4. 按 resolution 加 `-vf scale=-2:HEIGHT`（保持宽高比，宽度自动），`source` 时跳过
5. 解析 `out_time_ms` 进度行，结合时长实时更新进度百分比
6. 成功后输出到 `data/video_transcode/<stem>.<codec><ext>`，删除临时上传文件
7. 任务持久化到 `data/video_transcode/history.json`（结构与 video_dl 一致）

**质量档位 → CRF**：`high=18` / `balanced=23` / `compressed=28`

**输出命名示例**：`八段锦.h264.mp4` / `八段锦.h265.mp4` / `八段锦.vp9.webm`

任务字段：`id / status / progress / message / source_name / output_file / codec / quality / quality_label / resolution / started_at / finished_at / duration_sec`

### system_info.py — 系统信息收集

`collect()` 聚合：
- **OS**: `platform.system / release / machine / processor / python_version / cpu_count`
- **工具版本**: ffmpeg（`ffmpeg -version` 解析首行）、yt-dlp（`yt_dlp.version.__version__`）
- **存储**: 递归统计 `data/downloads/`、`data/audio/`、`data/video_transcode/` 文件数与字节数；`shutil.disk_usage` 拿磁盘剩余
- **功能列表**: 静态硬编码，每个功能带 `name / tab / desc`，前端可点「前往」切换 tab

纯只读，无状态、无副作用。

### updater.py — 自动更新

1. 读取 `version.txt` 获取当前版本
2. 请求 GitHub Releases API 获取最新版本（**多源竞速**，见下）
3. 版本不同则提示更新
4. 下载 zip → 解压到 `_update` 目录 → 生成更新脚本
5. 用户重启后自动替换文件

**多源竞速**（解决 `api.github.com` 国内访问不稳）：

`_MIRRORS` 列出 4 个候选源，每条 `(镜像前缀, releases/latest URL)`：
- `""` + `https://api.github.com/...` —— 直连
- `https://ghproxy.com/` + `https://ghproxy.com/https://api.github.com/...`
- `https://gh-proxy.com/` + 同上
- `https://github.moeyy.xyz/` + 同上

`_fetch_release_json()` 用 `ThreadPoolExecutor` 并发打四路，`as_completed` 取第一个返回
`tag_name` 字段的成功响应，总超时 8s，单源 connect 3s / read 5s。

记忆 `_working_mirror`：检查阶段哪个镜像通了，下载阶段就把它前缀拼到 `download_url` 前面，
避免又试一遍。下载阶段如果还失败，再退回 `github.com` 直链。

**版本读取的两种路径**：
- 开发态：`version.txt` 与 `app.py` 同目录
- 打包态：PyInstaller 已把 `version.txt` 通过 `--add-data "version.txt;."` 捆绑到
  `_MEIPASS` 临时解压目录，需用 `sys._MEIPASS / version.txt` 才能拿到，否则 Windows
  打包后始终显示 `v0.0.0`

**Variant 检测**（v1.4.0+）：`get_variant()` 读 `variant.txt`，返回 `web` / `desktop` / `dev`。
`check_update()` 按 variant 过滤 Release asset，确保两个版本各自只看自己的 zip。详见上文「Desktop 版架构」。

**版本比较**：解析 `vX.Y.Z` 拆成 `(major, minor, patch)` 元组逐段比较，
避免字符串 `"v1.1.0" > "v1.0.0"` 这类基于字典序的误判。

**注意**：GitHub API 失败时（如仓库尚无 release 返回 404），兜底响应中
仍带 `current` 字段，避免前端显示 `当前版本: undefined`。
GitHub Release `body` 字段可能为 `null`，统一用 `(release.get("body") or "")[:500]` 兜底。

## 发版流程

```
修改 version.txt → git commit → git tag vX.Y.Z → git push --tags
                                                      ↓
                                              GitHub Actions 触发
                                                      ↓
                          Windows 环境跑两次 PyInstaller：
                          toolbox-web.exe（含 templates/ + static/）
                          toolbox-desktop.exe（含 desktop/style.qss）
                                                      ↓
                          打两个 zip：windows-web.zip / windows-desktop.zip
                          各自捆绑 ffmpeg.exe / ffprobe.exe
                                                      ↓
                                        自动创建 Release + 上传两个 zip
```

用户从 Release 按需下载：
- 想要浏览器版 → `windows-web.zip`，运行后启 Flask 自动开浏览器
- 想要原生窗口版 → `windows-desktop.zip`，双击直接弹原生窗口，无 Flask、无浏览器
