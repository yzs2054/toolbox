// Tab 切换
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

const $ = id => document.getElementById(id);
let pollTimers = {};

async function extractVideos() {
  const url = $('url-input').value.trim();
  if (!url) return;

  $('btn-extract').disabled = true;
  $('loading').classList.remove('hidden');
  $('error').classList.add('hidden');
  $('video-list').innerHTML = '';

  try {
    const resp = await fetch('/api/video/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await resp.json();

    if (data.error) {
      $('error').textContent = data.error;
      $('error').classList.remove('hidden');
      return;
    }

    const videos = data.videos || [];
    if (videos.length === 0) {
      $('error').textContent = '未找到视频';
      $('error').classList.remove('hidden');
      return;
    }

    renderVideoList(videos);
  } catch (e) {
    $('error').textContent = '请求失败: ' + e.message;
    $('error').classList.remove('hidden');
  } finally {
    $('loading').classList.add('hidden');
    $('btn-extract').disabled = false;
  }
}

function renderVideoList(videos) {
  const list = $('video-list');
  list.innerHTML = videos.map((v, i) => {
    const quality = (v.title || '').match(/[(（]\s*(标清|高清|超清|蓝光|4K|720P|480P|360P|1080P)[^)）]*[)）]\s*$/i);
    const qualityLabel = quality ? quality[1] : '';
    return `
    <div class="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div class="flex items-center justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="text-base font-medium text-gray-100 truncate mb-1">${escapeHtml(v.title || '未命名视频')}</div>
          <div class="flex items-center gap-2 text-xs flex-wrap">
            ${qualityLabel ? `<span class="bg-blue-900/60 text-blue-300 border border-blue-700 px-2 py-0.5 rounded">${escapeHtml(qualityLabel)}</span>` : ''}
            <span class="bg-gray-700 px-2 py-0.5 rounded text-gray-300">${escapeHtml(v.type)}</span>
            ${v.vid ? '<span class="text-gray-500">vid: ' + escapeHtml(v.vid) + '</span>' : ''}
          </div>
          <div class="text-xs truncate text-gray-500 mt-1.5">${escapeHtml(v.url)}</div>
        </div>
        <button onclick='downloadVideo(${JSON.stringify(v).replace(/'/g, "&#39;")})'
                class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap shrink-0">
          下载
        </button>
      </div>
    </div>
  `;}).join('');
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function downloadVideo(video) {
  const resp = await fetch('/api/video/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video }),
  });
  const data = await resp.json();

  if (data.error) {
    alert(data.error);
    return;
  }

  ensureTaskCard(data.task_id, video);
  startPolling(data.task_id);
}

function taskCardHtml(task) {
  const video = task.video || {};
  const title = video.title || task.title || '未命名视频';
  const quality = (title.match(/[(（]\s*(标清|高清|超清|蓝光|4K|720P|480P|360P|1080P)[^)）]*[)）]\s*$/i) || [])[1] || '';
  const started = task.started_at ? formatTime(task.started_at) : '';
  const statusText = task.status === 'done' ? '完成'
    : task.status === 'error' ? '失败'
    : (task.progress != null ? task.progress + '%' : '排队中');
  const statusColor = task.status === 'done' ? 'text-green-400'
    : task.status === 'error' ? 'text-red-400' : 'text-blue-400';
  const fillBg = task.status === 'done' ? '#22c55e'
    : task.status === 'error' ? '#ef4444' : '';
  const progress = task.progress != null ? task.progress : 0;
  const fileLink = (task.status === 'done' && task.output_file)
    ? `<button onclick="revealFile('video', '${escapeHtml(task.id)}')"
        class="text-blue-400 hover:underline text-xs">打开所在目录</button>`
    : '';

  return `
    <div class="flex items-center justify-between gap-3 mb-2">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-sm font-medium text-gray-200 truncate">${escapeHtml(title)}</span>
          ${quality ? `<span class="bg-blue-900/60 text-blue-300 border border-blue-700 px-1.5 py-0.5 rounded text-xs">${escapeHtml(quality)}</span>` : ''}
          ${video.type ? `<span class="bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded text-xs">${escapeHtml(video.type)}</span>` : ''}
        </div>
        <div class="text-xs text-gray-500 mt-0.5">${escapeHtml(started)}</div>
      </div>
      <span class="task-status text-xs ${statusColor} whitespace-nowrap shrink-0">${statusText}</span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" style="width: ${progress}%; ${fillBg ? 'background:' + fillBg : ''}"></div>
    </div>
    <div class="task-msg text-xs text-gray-500 mt-1 flex items-center gap-3 flex-wrap">
      <span class="truncate flex-1 min-w-0">${escapeHtml(task.message || '')}</span>
      ${fileLink}
    </div>
  `;
}

function ensureTaskCard(taskId, video) {
  $('task-area').classList.remove('hidden');
  let card = $('task-' + taskId);
  if (!card) {
    card = document.createElement('div');
    card.id = 'task-' + taskId;
    card.className = 'bg-gray-800 border border-gray-700 rounded-lg p-4';
    card.innerHTML = taskCardHtml({
      status: 'downloading',
      progress: 0,
      video,
      started_at: Date.now() / 1000,
    });
    $('task-list').prepend(card);
  }
  return card;
}

function formatTime(unixSec) {
  const d = new Date(unixSec * 1000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function loadTasks() {
  try {
    const resp = await fetch('/api/video/tasks');
    const data = await resp.json();
    const tasks = data.tasks || [];
    if (tasks.length === 0) {
      $('task-area').classList.add('hidden');
      $('task-list').innerHTML = '';
      return;
    }
    $('task-area').classList.remove('hidden');
    const list = $('task-list');
    const seen = new Set();
    list.innerHTML = '';
    tasks.forEach(t => {
      seen.add(t.id);
      const card = document.createElement('div');
      card.id = 'task-' + t.id;
      card.className = 'bg-gray-800 border border-gray-700 rounded-lg p-4';
      card.innerHTML = taskCardHtml(t);
      list.appendChild(card);
      if (t.status === 'downloading') startPolling(t.id);
    });
  } catch (e) {
    // 静默失败
  }
}

function startPolling(taskId) {
  if (pollTimers[taskId]) return;
  const poll = async () => {
    const resp = await fetch('/api/video/tasks?id=' + taskId);
    const task = await resp.json();

    const card = $('task-' + taskId);
    if (!card) { delete pollTimers[taskId]; return; }

    card.innerHTML = taskCardHtml(task);

    if (task.status === 'downloading') {
      pollTimers[taskId] = setTimeout(poll, 1000);
    } else {
      delete pollTimers[taskId];
    }
  };
  poll();
}

// 回车触发提取
$('url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') extractVideos();
});

// ========== 软件更新 ==========

let _updateUrl = '';
let _currentVersion = '';

function renderUpdateInitial() {
  const box = $('update-status');
  if (!box) return;
  if (_currentVersion) {
    box.innerHTML = `
      <div class="flex items-center justify-between gap-3">
        <div class="text-sm text-gray-300">当前版本: <span class="font-medium">${escapeHtml(_currentVersion)}</span></div>
        <button onclick="checkForUpdate()" class="bg-blue-600 hover:bg-blue-700 px-3 py-1.5 rounded-lg text-xs font-medium">检查更新</button>
      </div>`;
  } else {
    box.innerHTML = `<div class="text-sm text-gray-500">读取版本中...</div>`;
  }
}

async function checkForUpdate() {
  const box = $('update-status');
  if (box) box.innerHTML = `
    <div class="flex items-center justify-between gap-3">
      <div class="text-sm text-gray-400">正在检查更新...</div>
      <button disabled class="bg-gray-700 px-3 py-1.5 rounded-lg text-xs font-medium opacity-50 cursor-not-allowed">检查更新</button>
    </div>`;
  try {
    const resp = await fetch('/api/update/check');
    const data = await resp.json();
    _currentVersion = data.current || _currentVersion;

    if (data.error) {
      if (box) box.innerHTML = `
        <div class="flex items-center justify-between gap-3">
          <div class="text-sm min-w-0">
            <div class="text-gray-300">当前版本: <span class="font-medium">${escapeHtml(_currentVersion)}</span></div>
            <div class="text-xs text-red-400 mt-1">检查失败: ${escapeHtml(data.error)}</div>
          </div>
          <button onclick="checkForUpdate()" class="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium">重试</button>
        </div>`;
      return;
    }

    if (data.has_update && data.download_url) {
      _updateUrl = data.download_url;
      if (box) box.innerHTML = `
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div class="text-sm min-w-0 flex-1">
            <div class="text-gray-300">
              发现新版本:
              <span class="text-gray-500 mx-1">${escapeHtml(_currentVersion)}</span>
              <span class="mx-1 text-gray-600">→</span>
              <span class="text-blue-400 font-medium">${escapeHtml(data.latest)}</span>
            </div>
            ${data.notes ? `<div class="text-xs text-gray-500 mt-2 max-w-md whitespace-pre-wrap">${escapeHtml(data.notes)}</div>` : ''}
          </div>
          <div class="flex gap-2 shrink-0">
            <button onclick="renderUpdateInitial()" class="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium">取消</button>
            <button onclick="doUpdate()"
                    class="bg-yellow-600 hover:bg-yellow-700 px-4 py-1.5 rounded-lg text-xs font-medium">
              立即更新
            </button>
          </div>
        </div>`;
    } else {
      _updateUrl = '';
      if (box) box.innerHTML = `
        <div class="flex items-center justify-between gap-3">
          <div class="text-sm text-gray-300">已是最新版本 <span class="font-medium">${escapeHtml(_currentVersion)}</span></div>
          <button onclick="checkForUpdate()" class="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium">再检查一次</button>
        </div>`;
    }
  } catch (e) {
    if (box) box.innerHTML = `<div class="text-sm text-red-400">检查失败: ${escapeHtml(e.message)}</div>`;
  }
}

async function doUpdate() {
  if (!_updateUrl) return;
  $('update-progress-area').classList.remove('hidden');

  await fetch('/api/update/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ download_url: _updateUrl }),
  });

  pollUpdate();
}

function pollUpdate() {
  fetch('/api/update/progress')
    .then(r => r.json())
    .then(data => {
      $('update-fill').style.width = data.progress + '%';
      $('update-msg').textContent = data.message;

      if (data.status === 'ready') {
        $('update-msg').textContent = '更新已就绪，重启后生效';
        return;
      }
      if (data.status === 'error') {
        $('update-msg').textContent = '更新失败: ' + (data.message || '');
        return;
      }
      setTimeout(pollUpdate, 1000);
    });
}

// ========== 系统信息 ==========

async function loadSystemInfo() {
  const box = $('system-info');
  try {
    const resp = await fetch('/api/system/info');
    const data = await resp.json();
    if (data.app_version) {
      _currentVersion = data.app_version;
      $('version').textContent = '当前版本: ' + _currentVersion;
      renderUpdateInitial();
    }
    box.innerHTML = renderSystemInfo(data);
  } catch (e) {
    box.innerHTML = `<div class="text-red-400 text-sm">加载失败: ${escapeHtml(e.message)}</div>`;
  }
}

function infoRow(label, value) {
  return `
    <div class="flex items-center justify-between py-1.5">
      <span class="text-gray-500">${escapeHtml(label)}</span>
      <span class="text-gray-200 font-mono text-xs text-right">${escapeHtml(value)}</span>
    </div>`;
}

function infoCard(title, rowsHtml) {
  return `
    <div class="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">${escapeHtml(title)}</div>
      <div class="divide-y divide-gray-700/50">${rowsHtml}</div>
    </div>`;
}

function renderSystemInfo(data) {
  const os = data.os || {};
  const tools = data.tools || {};
  const st = data.storage || {};
  const features = data.features || [];

  const osCard = infoCard('操作系统', `
    ${infoRow('系统', `${os.system} ${os.release}`)}
    ${infoRow('架构', os.machine || '-')}
    ${infoRow('CPU', `${os.processor || '-'} (${os.cpu_count || 0} 核)`)}
    ${infoRow('Python', os.python || '-')}
  `);

  const toolsCard = infoCard('工具版本', `
    ${infoRow('应用版本', _currentVersion || '-')}
    ${infoRow('ffmpeg', tools.ffmpeg || '-')}
    ${infoRow('yt-dlp', tools.yt_dlp || '-')}
  `);

  const dl = st.downloads || {};
  const au = st.audio || {};
  const storageCard = infoCard('存储', `
    ${infoRow('下载目录', `${dl.size_human || '0 B'} / ${dl.file_count || 0} 文件`)}
    ${infoRow('音频目录', `${au.size_human || '0 B'} / ${au.file_count || 0} 文件`)}
    ${infoRow('磁盘剩余', `${st.disk_free_human || '-'} / ${st.disk_total_human || '-'}`)}
  `);

  const featuresHtml = features.map(f => `
    <div class="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div class="flex items-center justify-between gap-3 mb-1">
        <span class="text-sm font-medium text-gray-200">${escapeHtml(f.name)}</span>
        <button onclick="switchTab('${escapeHtml(f.tab)}')"
                class="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded text-xs font-medium">前往</button>
      </div>
      <div class="text-xs text-gray-500">${escapeHtml(f.desc)}</div>
    </div>`).join('');

  return `
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      ${osCard}
      ${toolsCard}
    </div>
    <div>${storageCard}</div>
    <div>
      <div class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2 mt-5">功能</div>
      <div class="space-y-2">${featuresHtml}</div>
    </div>
  `;
}

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    if (b.dataset.tab === name) b.click();
  });
}

// 页面加载后
loadTasks();
loadAudioTasks();
loadSystemInfo();

// ========== 音频提取 ==========

const audioPollTimers = {};

function onAudioFilePicked() {
  const f = $('audio-file').files[0];
  $('audio-file-name').textContent = f ? f.name : '未选择';
  $('btn-audio-convert').disabled = !f;
}

async function uploadAndConvert() {
  const f = $('audio-file').files[0];
  if (!f) return;
  $('audio-error').classList.add('hidden');
  $('btn-audio-convert').disabled = true;
  $('btn-audio-convert').textContent = '上传中...';

  const fd = new FormData();
  fd.append('file', f);

  try {
    const resp = await fetch('/api/audio/upload', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.error) {
      showAudioError(data.error);
      return;
    }
    ensureAudioTaskCard(data.task_id, f.name);
    startAudioPolling(data.task_id);
    // 重置选择，允许立即转下一个
    $('audio-file').value = '';
    onAudioFilePicked();
  } catch (e) {
    showAudioError('上传失败: ' + e.message);
  } finally {
    $('btn-audio-convert').disabled = false;
    $('btn-audio-convert').textContent = '开始转换';
  }
}

function showAudioError(msg) {
  $('audio-error').textContent = msg;
  $('audio-error').classList.remove('hidden');
}

async function revealFile(kind, taskId) {
  try {
    const resp = await fetch('/api/file/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, id: taskId }),
    });
    const data = await resp.json();
    if (data.error) alert(data.error);
  } catch (e) {
    alert('调用失败: ' + e.message);
  }
}

function audioTaskCardHtml(task) {
  const source = task.source_name || '未命名';
  const started = task.started_at ? formatTime(task.started_at) : '';
  const statusText = task.status === 'done' ? '完成'
    : task.status === 'error' ? '失败'
    : (task.progress != null ? task.progress + '%' : '排队中');
  const statusColor = task.status === 'done' ? 'text-green-400'
    : task.status === 'error' ? 'text-red-400' : 'text-blue-400';
  const fillBg = task.status === 'done' ? '#22c55e'
    : task.status === 'error' ? '#ef4444' : '';
  const progress = task.progress != null ? task.progress : 0;
  const fileLink = (task.status === 'done' && task.output_file)
    ? `<button onclick="revealFile('audio', '${escapeHtml(task.id)}')"
        class="text-blue-400 hover:underline text-xs">打开所在目录</button>`
    : '';

  return `
    <div class="flex items-center justify-between gap-3 mb-2">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-sm font-medium text-gray-200 truncate">${escapeHtml(source)}</span>
          <span class="bg-purple-900/60 text-purple-300 border border-purple-700 px-1.5 py-0.5 rounded text-xs">MP3</span>
        </div>
        <div class="text-xs text-gray-500 mt-0.5">${escapeHtml(started)}</div>
      </div>
      <span class="text-xs ${statusColor} whitespace-nowrap shrink-0">${statusText}</span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" style="width: ${progress}%; ${fillBg ? 'background:' + fillBg : ''}"></div>
    </div>
    <div class="text-xs text-gray-500 mt-1 flex items-center gap-3 flex-wrap">
      <span class="truncate flex-1 min-w-0">${escapeHtml(task.message || '')}</span>
      ${fileLink}
    </div>
  `;
}

function ensureAudioTaskCard(taskId, sourceName) {
  $('audio-task-area').classList.remove('hidden');
  let card = $('audio-task-' + taskId);
  if (!card) {
    card = document.createElement('div');
    card.id = 'audio-task-' + taskId;
    card.className = 'bg-gray-800 border border-gray-700 rounded-lg p-4';
    card.innerHTML = audioTaskCardHtml({
      status: 'downloading',
      progress: 0,
      source_name: sourceName,
      started_at: Date.now() / 1000,
    });
    $('audio-task-list').prepend(card);
  }
  return card;
}

async function loadAudioTasks() {
  try {
    const resp = await fetch('/api/audio/tasks');
    const data = await resp.json();
    const tasks = data.tasks || [];
    if (tasks.length === 0) {
      $('audio-task-area').classList.add('hidden');
      $('audio-task-list').innerHTML = '';
      return;
    }
    $('audio-task-area').classList.remove('hidden');
    const list = $('audio-task-list');
    list.innerHTML = '';
    tasks.forEach(t => {
      const card = document.createElement('div');
      card.id = 'audio-task-' + t.id;
      card.className = 'bg-gray-800 border border-gray-700 rounded-lg p-4';
      card.innerHTML = audioTaskCardHtml(t);
      list.appendChild(card);
      if (t.status === 'downloading') startAudioPolling(t.id);
    });
  } catch (e) {
    // 静默
  }
}

function startAudioPolling(taskId) {
  if (audioPollTimers[taskId]) return;
  const poll = async () => {
    const resp = await fetch('/api/audio/tasks?id=' + taskId);
    const task = await resp.json();
    const card = $('audio-task-' + taskId);
    if (!card) { delete audioPollTimers[taskId]; return; }

    card.innerHTML = audioTaskCardHtml(task);

    if (task.status === 'downloading') {
      audioPollTimers[taskId] = setTimeout(poll, 1000);
    } else {
      delete audioPollTimers[taskId];
    }
  };
  poll();
}
