/**
 * Web UI 前端交互（Phase 2 Step 1）
 * 功能：拖拽上传 / 文件列表 / 设置面板 / 日志 SSE
 */

// ── DOM 引用 ──────────────────────────────────────────
const dropzone = document.getElementById('dropzone');
const dropzoneActive = document.getElementById('dropzoneActive');
const fileInput = document.getElementById('fileInput');
const browseBtn = document.getElementById('browseBtn');
const fileList = document.getElementById('fileList');
const startBtn = document.getElementById('startBtn');
const clearBtn = document.getElementById('clearBtn');
const testLogBtn = document.getElementById('testLogBtn');
const logContainer = document.getElementById('logContainer');
const logEmpty = document.getElementById('logEmpty');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');

// ── 状态 ──────────────────────────────────────────────
let uploadedFiles = [];
let currentTaskId = null;
let sseConnection = null;

// ── 工具函数 ──────────────────────────────────────────
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getFileIcon(format) {
    return format === 'pdf' ? '📕' : format === 'docx' ? '📘' : '📄';
}

// ── 拖拽上传 ──────────────────────────────────────────
['dragenter', 'dragover'].forEach(evt => {
    dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.parentElement.classList.add('dragover');
    });
});

['dragleave', 'drop'].forEach(evt => {
    dropzoneActive.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.parentElement.classList.remove('dragover');
    });
});

dropzoneActive.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.parentElement.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files);
    uploadFiles(files);
});

dropzone.addEventListener('click', () => fileInput.click());
browseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        uploadFiles(Array.from(fileInput.files));
        fileInput.value = '';
    }
});

// ── 上传文件 ──────────────────────────────────────────
async function uploadFiles(files) {
    setStatus('busy', '上传中...');

    const formData = new FormData();
    files.forEach(f => formData.append('files', f));

    try {
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await resp.json();

        for (const f of data.files) {
            if (f.error) {
                addFileToList({ ...f, hasError: true });
                addLog('warning', `⚠ ${f.name}: ${f.error}`);
            } else {
                uploadedFiles.push(f);
                addFileToList(f);
                addLog('success', `✅ 已上传: ${f.name} (${formatSize(f.size)})`);
            }
        }
        updateStartButton();
        setStatus('ok', '就绪');
    } catch (err) {
        addLog('error', `上传失败: ${err.message}`);
        setStatus('ok', '就绪');
    }
}

// ── 文件列表 UI ───────────────────────────────────────
function addFileToList(file) {
    const emptyEl = fileList.querySelector('.file-list-empty');
    if (emptyEl) emptyEl.remove();

    const div = document.createElement('div');
    div.className = 'file-item' + (file.hasError ? ' error' : '');
    div.dataset.id = file.id;
    div.innerHTML = `
        <span class="file-item-icon">${getFileIcon(file.format)}</span>
        <div class="file-item-info">
            <div class="file-item-name">${escapeHtml(file.name)}</div>
            <div class="file-item-meta">
                ${file.hasError ? '❌ 不支持' : `${file.format.toUpperCase()} · ${formatSize(file.size)}`}
            </div>
        </div>
        <button class="file-item-remove" title="移除">✕</button>
    `;

    div.querySelector('.file-item-remove').addEventListener('click', () => removeFile(file.id, div));
    fileList.appendChild(div);
}

async function removeFile(id, element) {
    try {
        await fetch(`/api/upload/${id}`, { method: 'DELETE' });
        uploadedFiles = uploadedFiles.filter(f => f.id !== id);
        element.remove();
        if (fileList.querySelectorAll('.file-item').length === 0) {
            fileList.innerHTML = '<div class="file-list-empty">暂无文件，请上传</div>';
        }
        updateStartButton();
    } catch (err) {
        addLog('error', `删除失败: ${err.message}`);
    }
}

function updateStartButton() {
    startBtn.disabled = uploadedFiles.filter(f => !f.hasError).length === 0;
}

clearBtn.addEventListener('click', async () => {
    for (const f of [...uploadedFiles]) {
        await fetch(`/api/upload/${f.id}`, { method: 'DELETE' });
    }
    uploadedFiles = [];
    fileList.innerHTML = '<div class="file-list-empty">暂无文件，请上传</div>';
    updateStartButton();
    addLog('info', '已清空所有文件');
});

// ── 日志系统 ──────────────────────────────────────────
function addLog(level, message) {
    if (logEmpty) logEmpty.style.display = 'none';

    const line = document.createElement('div');
    line.className = 'log-line';

    const now = new Date();
    const time = now.toTimeString().slice(0, 8);

    const levelLabels = { info: '信息', success: '成功', warning: '警告', error: '错误' };
    line.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-level ${level}">[${levelLabels[level] || level}]</span>
        <span class="log-msg">${escapeHtml(message)}</span>
    `;

    logContainer.appendChild(line);
    logContainer.scrollTop = logContainer.scrollHeight;
}

function addLogEntry(entry) {
    if (logEmpty) logEmpty.style.display = 'none';
    // 移除旧进度条
    const oldProgress = logContainer.querySelector('.progress-bar');
    if (oldProgress) oldProgress.remove();

    const line = document.createElement('div');
    line.className = 'log-line';
    line.innerHTML = `
        <span class="log-time">${entry.timestamp}</span>
        <span class="log-level ${entry.level}">[${getLevelLabel(entry.level)}]</span>
        <span class="log-msg">${escapeHtml(entry.message)}</span>
    `;
    logContainer.appendChild(line);

    // 添加进度条
    if (entry.progress > 0) {
        const progressBar = document.createElement('div');
        progressBar.className = 'progress-bar';
        progressBar.innerHTML = `<div class="progress-bar-fill" style="width:${entry.progress}%"></div>`;
        logContainer.appendChild(progressBar);
    }

    logContainer.scrollTop = logContainer.scrollHeight;
}

function getLevelLabel(level) {
    const labels = { info: '信息', success: '成功', warning: '警告', error: '错误' };
    return labels[level] || level;
}

// ── SSE 日志流 ────────────────────────────────────────
function connectSSE(taskId) {
    if (sseConnection) sseConnection.close();
    currentTaskId = taskId;
    setStatus('busy', '运行中...');

    const url = `/api/logs/${taskId}`;
    sseConnection = new EventSource(url);

    sseConnection.addEventListener('log', (event) => {
        const entry = JSON.parse(event.data);
        addLogEntry(entry);

        if (entry.message.includes('完成') || entry.message.includes('失败')) {
            setStatus('ok', '就绪');
        }
    });

    sseConnection.addEventListener('heartbeat', () => {
        // 心跳，无需处理
    });

    sseConnection.onerror = () => {
        // SSE 自动重连
    };
}

// ── 设置状态指示 ──────────────────────────────────────
function setStatus(state, text) {
    statusDot.className = 'status-dot' + (state === 'busy' ? ' busy' : '');
    statusText.textContent = text;
}

// ── 测试日志流 ────────────────────────────────────────
testLogBtn.addEventListener('click', async () => {
    try {
        const resp = await fetch('/api/test-log', { method: 'POST' });
        const data = await resp.json();
        connectSSE(data.task_id);
        addLog('info', `🧪 测试日志流已启动 (task: ${data.task_id})`);
    } catch (err) {
        addLog('error', `启动测试日志失败: ${err.message}`);
    }
});

// ── 开始翻译（预留，暂不接入）──────────────────────────
startBtn.addEventListener('click', () => {
    addLog('warning', '🚧 翻译功能将在下一阶段接入');
});

// ── 安全函数 ──────────────────────────────────────────
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── 初始加载设置 ──────────────────────────────────────
async function loadSettings() {
    try {
        const resp = await fetch('/api/settings');
        const settings = await resp.json();
        document.getElementById('settingTranslator').value = settings.translation_engine || 'deepseek';
        document.getElementById('settingOCR').value = settings.ocr_engine || 'easyocr';
        document.getElementById('settingOutputDir').value = 'output/';
    } catch (err) {
        console.error('加载设置失败:', err);
    }
}

loadSettings();
addLog('info', '🟢 Web UI 已就绪，请上传文件');
