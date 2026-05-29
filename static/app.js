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
  list.innerHTML = videos.map((v, i) => `
    <div class="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div class="flex items-center justify-between">
        <div class="flex-1 min-w-0">
          <div class="text-sm text-gray-400 mb-1">
            <span class="bg-gray-700 px-2 py-0.5 rounded text-xs">${v.type}</span>
            ${v.vid ? '<span class="ml-2 text-xs text-gray-500">vid: ' + v.vid + '</span>' : ''}
          </div>
          <div class="text-sm truncate text-gray-300">${v.url}</div>
        </div>
        <button onclick='downloadVideo(${JSON.stringify(v).replace(/'/g, "&#39;")})'
                class="ml-3 bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap">
          下载
        </button>
      </div>
    </div>
  `).join('');
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

  addTaskCard(data.task_id, video);
  startPolling(data.task_id);
}

function addTaskCard(taskId, video) {
  const list = $('task-list');
  const card = document.createElement('div');
  card.id = 'task-' + taskId;
  card.className = 'bg-gray-800 border border-gray-700 rounded-lg p-4';
  card.innerHTML = `
    <div class="flex items-center justify-between mb-2">
      <span class="text-sm text-gray-300">${video.title || '视频'}</span>
      <span class="task-status text-xs text-blue-400">下载中...</span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" style="width: 0%"></div>
    </div>
    <div class="task-msg text-xs text-gray-500 mt-1"></div>
  `;
  list.appendChild(card);
}

function startPolling(taskId) {
  const poll = async () => {
    const resp = await fetch('/api/video/tasks?id=' + taskId);
    const task = await resp.json();

    const card = $('task-' + taskId);
    if (!card) return;

    const fill = card.querySelector('.progress-fill');
    const status = card.querySelector('.task-status');
    const msg = card.querySelector('.task-msg');

    fill.style.width = task.progress + '%';

    if (task.status === 'done') {
      status.textContent = '完成';
      status.className = 'task-status text-xs text-green-400';
      msg.textContent = task.message;
      fill.style.background = '#22c55e';
      return;
    }

    if (task.status === 'error') {
      status.textContent = '失败';
      status.className = 'task-status text-xs text-red-400';
      msg.textContent = task.message;
      fill.style.background = '#ef4444';
      return;
    }

    status.textContent = task.progress + '%';
    pollTimers[taskId] = setTimeout(poll, 1000);
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
