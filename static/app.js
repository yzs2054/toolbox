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
    ? `<a href="/downloads/${encodeURIComponent(task.output_file)}" download
        class="text-blue-400 hover:underline text-xs">下载文件: ${escapeHtml(task.output_file)}</a>`
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
    <div class="task-msg text-xs text-gray-500 mt-1">
      ${escapeHtml(task.message || '')}
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

// ========== 自动更新 ==========

let _updateUrl = '';

async function checkForUpdate() {
  try {
    const resp = await fetch('/api/update/check');
    const data = await resp.json();

    $('version').textContent = '当前版本: ' + data.current;

    if (data.has_update && data.download_url) {
      _updateUrl = data.download_url;
      $('update-latest').textContent = data.latest;
      $('update-notes').textContent = data.notes || '';
      $('update-area').classList.remove('hidden');
    }
  } catch (e) {
    // 静默失败，不影响使用
    console.warn('检查更新失败:', e);
  }
}

async function doUpdate() {
  if (!_updateUrl) return;
  $('btn-update').disabled = true;
  $('btn-update').textContent = '更新中...';
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
        $('btn-update').textContent = '重启后生效';
        $('btn-update').className = 'bg-green-600 px-4 py-2 rounded-lg text-sm font-medium';
        return;
      }
      if (data.status === 'error') {
        $('btn-update').textContent = '更新失败';
        $('btn-update').className = 'bg-red-600 px-4 py-2 rounded-lg text-sm font-medium';
        return;
      }
      setTimeout(pollUpdate, 1000);
    });
}

// 页面加载后检查更新
checkForUpdate();
loadTasks();
