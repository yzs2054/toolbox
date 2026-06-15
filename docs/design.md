# 设计文档

## 系统架构

```
浏览器 ←→ Flask (app.py) ←→ modules/
                  │
                  ├── video_dl.py    视频下载模块
                  ├── updater.py     自动更新模块
                  └── (后续模块...)
```

## 目录结构

```
toolbox/
├── app.py                    # Flask 入口，路由定义
├── version.txt               # 当前版本号
├── requirements.txt          # Python 依赖
├── modules/
│   ├── __init__.py
│   ├── video_dl.py           # 视频提取与下载 + 任务历史
│   ├── channels_dl.py        # 视频号解析（依赖 Cookie，未接入 Web）
│   └── updater.py            # 自动更新
├── templates/
│   └── index.html            # 单页面，Tab 切换功能
├── static/
│   ├── style.css             # 样式
│   └── app.js                # 前端逻辑
├── downloads/                # 下载文件存放
│   └── history.json          # 任务历史索引（自动生成）
├── docs/                     # 项目文档
└── .github/workflows/
    └── build.yml             # CI/CD 构建配置
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

### 自动更新

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/update/check` | GET | 检查 GitHub Releases 是否有新版本 |
| `/api/update/start` | POST | 开始下载更新包 |
| `/api/update/progress` | GET | 查询更新下载进度 |

### 文件下载

| 接口 | 方法 | 说明 |
|---|---|---|
| `/downloads/<filename>` | GET | 下载已完成的文件 |

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

### updater.py — 自动更新

1. 读取 `version.txt` 获取当前版本
2. 请求 GitHub Releases API 获取最新版本
3. 版本不同则提示更新
4. 下载 zip → 解压到 `_update` 目录 → 生成更新脚本
5. 用户重启后自动替换文件

**注意**：GitHub API 失败时（如仓库尚无 release 返回 404），兜底响应中
仍带 `current` 字段，避免前端显示 `当前版本: undefined`。

## 发版流程

```
修改 version.txt → git commit → git tag vX.Y.Z → git push --tags
                                                      ↓
                                              GitHub Actions 触发
                                                      ↓
                                        Windows 环境打包 exe + ffmpeg
                                                      ↓
                                            自动创建 Release + 上传 zip
```
