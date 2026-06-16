# 进度文档

## v1.0.0 — 初始版本 (2026-05-29)

### 已完成

- [x] 项目初始化，Flask + Tailwind CSS 单页面应用
- [x] 视频下载模块
  - [x] 微信公众号（腾讯视频 iframe）提取与下载
  - [x] mpvideo 直链提取
  - [x] HTML5 video 标签提取
  - [x] 直接 mp4/m3u8 链接提取
  - [x] 广告 vid 误匹配过滤
  - [x] yt-dlp 库调用（非命令行）
  - [x] 异步下载 + 进度查询
- [x] Web 界面
  - [x] URL 输入 + 提取视频
  - [x] 视频列表展示
  - [x] 一键下载 + 进度条
- [x] 自动更新
  - [x] GitHub Releases 版本检查
  - [x] 一键下载更新包
  - [x] 更新进度显示
- [x] CI/CD
  - [x] GitHub Actions 自动构建 Windows exe
  - [x] 打 tag 自动发布 Release
  - [x] ffmpeg 自动下载打包

### 待解决

- [ ] PyInstaller 打包 exe 被 Windows Defender 误报病毒 → 考虑换 Nuitka
- [ ] gh CLI 未登录，无法在终端查看构建状态

## v1.1.0 — (2026-06-15)

### 已完成

- [x] 百度新闻视频源支持
  - [x] `mbd.baidu.com/newspage/data/videolanding` 落地页反爬旁路
  - [x] 通过 `haokan.baidu.com/v?vid=<nid>` 拉取多路清晰度 mp4 直链
  - [x] 自动配对 360P / 480P / 720P / 1080P 标签
- [x] 下载历史持久化
  - [x] `downloads/history.json` 存储，跨重启保留
  - [x] 任务字段加 `started_at` / `finished_at` / `output_file`
  - [x] `_tasks_lock` 线程安全，原子写入（临时文件 + rename）
  - [x] 历史保留上限 200 条
- [x] Web 界面改进
  - [x] 视频卡片显示标题 + 清晰度徽章（标清/高清/超清/蓝光）
  - [x] 「下载记录」分区，页面打开自动加载历史
  - [x] 完成的任务提供「下载文件」直链
  - [x] 服务重启后进行中的任务自动恢复轮询
  - [x] 标题 HTML 转义防注入
- [x] 小修复
  - [x] 端口支持 `PORT` 环境变量覆盖（默认 8080）
  - [x] `updater.check_update()` 失败兜底返回 `current`，避免前端显示 undefined

### 待解决

- [ ] `app.py` 的 `webbrowser.open` 在 Linux 无桌面环境下误调用 xterm 报错
- [ ] 百度直链 `auth_key` 有时效，过期后历史里的「下载文件」链接会失效
- [ ] `channels_dl.py` 视频号解析模块未接入 Web UI

## v1.2.0 — (2026-06-15)

### 已完成

- [x] 视频转 MP3
  - [x] 新增 `modules/audio_extract.py`，ffmpeg + libmp3lame，默认 192 kbps
  - [x] multipart 文件上传，落 `downloads/_uploads/`，转换后自动清理
  - [x] `ffprobe` 拿时长 + `ffmpeg -progress` 解析实时进度
  - [x] 输出 `downloads/audio/`，独立 `history.json` 持久化
  - [x] 新增「音频提取」tab，文件选择 + 转换 + 进度卡片 + MP3 下载链接
  - [x] PyInstaller 打包模式下自动把 exe 同目录加入 PATH，让捆绑的 ffmpeg.exe 可被发现
  - [x] 完成任务提供「打开所在目录」按钮，跨平台调用系统文件管理器高亮选中文件，替代原浏览器下载链

- [x] 系统 tab
  - [x] 新增 `modules/system_info.py` + `GET /api/system/info`
  - [x] 展示 OS / Python / CPU / 工具版本（ffmpeg、yt-dlp）/ 存储用量
  - [x] 功能列表卡片，点「前往」直接切到对应 tab
  - [x] 把更新 UI 从视频 tab 挪到系统 tab，状态更明确（已是最新 / 发现新版 / 检查失败带重试）

## v1.3.0 — (2026-06-15)

### 已完成

- [x] 视频转码
  - [x] 新增 `modules/video_transcode.py`，支持 H.264 / H.265 / VP9 三种编码
  - [x] 分辨率缩放选项：保持原分辨率 / 1080p / 720p / 480p（`-vf scale=-2:HEIGHT`）
  - [x] 质量档位：高质 CRF 18 / 平衡 CRF 23 / 压缩 CRF 28
  - [x] `ffprobe` 拿时长 + `ffmpeg -progress` 解析实时进度
  - [x] 输出 `downloads/video_transcode/`，独立 `history.json` 持久化
  - [x] 新增「视频转码」tab，文件选择 + 编码/分辨率/质量三联下拉 + 进度卡片
  - [x] `/api/file/reveal` 扩展支持 `kind="video_transcode"`

- [x] Windows 打包版本号修复
  - [x] PyInstaller 加 `--add-data "version.txt;."` 把版本文件捆进 exe
  - [x] `updater.get_current_version()` 在 `sys.frozen` 时改用 `sys._MEIPASS` 解析路径
  - [x] 修复 Windows 下版本号始终为 `v0.0.0` 的问题

- [x] 更新检查健壮性
  - [x] 加 `_parse_version()` 语义化版本比较，避免字符串字典序误判
  - [x] GitHub Release `body` 字段为 `null` 时兜底为空字符串

- [x] 数据目录扁平化
  - [x] 产物目录从 `downloads/{audio,video_transcode,_uploads}` 改为 `data/{downloads,audio,video_transcode,_uploads}`，四者同级
  - [x] 历史文件迁移：旧 `downloads/history.json` → `data/downloads/history.json`，旧 `downloads/audio/history.json` → `data/audio/history.json`，转码同理
  - [x] `.gitignore` 把 `downloads/` 换成 `data/`

- [x] 更新检查与下载加速
  - [x] `updater._fetch_release_json()` 多源竞速：直连 + ghproxy + gh-proxy + moeyy，4 路并发取首胜，总超时 8s
  - [x] 记忆生效镜像前缀，下载阶段复用同一个镜像，失败再回退 `github.com` 直链
  - [x] 所有源都失败时 1.5s 内返回错误，避免 UI 假死

## v1.4.0 — 规划中

### 计划功能

- [ ] Nuitka 替代 PyInstaller 打包
- [ ] 视频号解析接入 Web UI（依赖 Cookie）
- [ ] 音频码率/采样率选项（当前固定 192 kbps）
- [ ] 音频格式扩展（wav / aac）
- [ ] 视频转码硬件加速（NVENC / VideoToolbox）
- [ ] 视频截取（指定起止时间）

## 版本号规则

- 主版本号.次版本号.修订号
- 新功能 → 次版本号 +1
- Bug 修复 → 修订号 +1
