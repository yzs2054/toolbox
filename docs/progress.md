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

## v1.2.0 — 规划中

### 计划功能

- [ ] 音频提取模块
- [ ] 格式转换模块
- [ ] Nuitka 替代 PyInstaller 打包
- [ ] 视频号解析接入 Web UI（依赖 Cookie）

## 版本号规则

- 主版本号.次版本号.修订号
- 新功能 → 次版本号 +1
- Bug 修复 → 修订号 +1
