// Extracted verbatim from templates/models.html so the Content-Security-Policy can drop
// 'unsafe-inline' for scripts (audit M6). The template carried no Jinja
// interpolation here, so this is the same code in a file the browser fetches
// from this origin, loaded at the point the inline block used to run.

let currentActiveModel = null;
let ollamaUrl = 'Ollama';

// Fetch actual Ollama URL and connection status from server config
fetch('/api/settings/stats')
    .then(async (r) => {
        const statusSpan = document.getElementById('connection-status');
        if (r.status === 403) {
            // Not a connectivity problem. Model management is admin-only, and
            // reporting that as "Disconnected" sent people looking for a broken
            // Ollama that was running fine.
            document.getElementById('ollama-url-display').textContent = 'hidden';
            statusSpan.className = 'badge bg-secondary';
            statusSpan.textContent = 'Admin access required';
            document.getElementById('models-admin-notice')?.classList.remove('d-none');
            document.getElementById('models-admin-content')?.classList.add('d-none');
            return;
        }
        if (!r.ok) {
            statusSpan.className = 'badge bg-danger';
            statusSpan.textContent = 'Unavailable';
            return;
        }
        const d = await r.json();
        if (d.system?.ollama_url) {
            ollamaUrl = d.system.ollama_url;
            document.getElementById('ollama-url-display').textContent = ollamaUrl;
        }
        if (d.system?.ollama_available) {
            statusSpan.className = 'badge bg-success';
            statusSpan.textContent = 'Connected';
        } else {
            statusSpan.className = 'badge bg-danger';
            statusSpan.textContent = 'Disconnected';
        }
    })
    .catch(() => {
        document.getElementById('ollama-url-display').textContent = 'unknown';
    });

// Show/hide custom model input based on selection
document.getElementById('model-select').addEventListener('change', function() {
    const customGroup = document.getElementById('custom-model-group');
    if (this.value === 'custom') {
        customGroup.style.display = 'block';
    } else {
        customGroup.style.display = 'none';
    }
});

// Load models
async function loadModels() {
    const modelsList = document.getElementById('models-list');
    modelsList.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm"></div> Loading...</div>';

    try {
        const response = await fetch('/api/models');
        const data = await response.json();

        if (!data.success) {
            modelsList.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>Cannot reach Ollama at <code>${ollamaUrl}</code>. Check that Ollama is running and <code>OLLAMA_BASE_URL</code> is set correctly on the server.</div>`;
            return;
        }

        if (data.models.length === 0) {
            modelsList.innerHTML = '<div class="alert alert-warning">No models installed. Pull a model to get started.</div>';
            return;
        }

        modelsList.innerHTML = '';

        // Get active model
        const activeResponse = await fetch('/api/models/active');
        const activeData = await activeResponse.json();
        currentActiveModel = activeData.model;

        // Render each model
        data.models.forEach(model => {
            const template = document.getElementById('model-card-template');
            const card = template.content.cloneNode(true);

            card.querySelector('.model-name').textContent = model.name;
            card.querySelector('.model-size').textContent = formatBytes(model.size);
            card.querySelector('.model-modified').textContent = formatDate(model.modified_at);

            const cardElement = card.querySelector('.model-card');

            if (model.name === currentActiveModel) {
                card.querySelector('.active-badge').style.display = 'inline';
                cardElement.classList.add('border-success');
            }

            if (model.loaded) {
                card.querySelector('.loaded-badge').style.display = 'inline';
                card.querySelector('.unload-btn').style.display = '';
            }

            if (model.fits === false) {
                cardElement.style.opacity = '0.55';
                card.querySelector('.model-warning').style.display = '';
                card.querySelector('.model-warning-text').textContent =
                    model.reason || 'May not fit in available memory';
                const activateBtn = card.querySelector('.activate-btn');
                activateBtn.disabled = true;
                activateBtn.title = model.reason || 'Insufficient memory';
            }

            card.querySelector('.activate-btn').onclick = () => activateModel(model.name);
            card.querySelector('.test-btn').onclick = () => testModel(model.name);
            card.querySelector('.unload-btn').onclick = () => unloadModel(model.name);
            card.querySelector('.delete-btn').onclick = () => deleteModel(model.name);

            modelsList.appendChild(card);
        });
    } catch (error) {
        modelsList.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>Failed to load models: ${error.message}</div>`;
    }
}

// Activate model
async function activateModel(modelName) {
    try {
        const response = await fetch('/api/models/active', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName})
        });

        const data = await response.json();

        if (data.success) {
            showToast('Success', `${modelName} is now active`, 'success');
            loadModels();
            // Refresh the header badge now rather than waiting for its poll.
            if (window.refreshStatusBadges) window.refreshStatusBadges();
        } else {
            showToast('Error', data.message, 'danger');
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
    }
}

// Test model
async function testModel(modelName) {
    showToast('Testing', `Testing ${modelName}...`, 'info');

    try {
        const response = await fetch('/api/models/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName})
        });

        const data = await response.json();

        if (data.success) {
            showToast('Success', `${modelName} is working! Response: ${data.result}`, 'success');
        } else {
            showToast('Error', `Test failed: ${data.result}`, 'danger');
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
    }
}

// Unload model from memory
async function unloadModel(modelName) {
    try {
        const response = await fetch('/api/models/unload', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName})
        });

        const data = await response.json();

        if (data.success) {
            showToast('Success', `${modelName} unloaded from memory`, 'success');
            loadModels();
        } else {
            showToast('Error', data.message, 'danger');
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
    }
}

// Delete model
async function deleteModel(modelName) {
    if (!confirm(`Are you sure you want to delete ${modelName}?`)) {
        return;
    }

    try {
        const response = await fetch('/api/models/delete', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName})
        });

        const data = await response.json();

        if (data.success) {
            showToast('Success', `${modelName} deleted`, 'success');
            loadModels();
        } else {
            showToast('Error', data.message, 'danger');
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
    }
}

// Pull model
document.getElementById('pull-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const modelSelect = document.getElementById('model-select');
    let modelName = modelSelect.value;

    // Check if custom model is selected
    if (modelName === 'custom') {
        modelName = document.getElementById('custom-model-name').value.trim();
    }

    if (!modelName || modelName === 'custom') {
        alert('Please select or enter a model name');
        return;
    }

    const pullBtn = document.getElementById('pull-btn');
    const pullProgress = document.getElementById('pull-progress');
    const pullStatus = document.getElementById('pull-status');
    const progressBar = document.getElementById('pull-progress-bar');

    pullBtn.disabled = true;
    pullProgress.style.display = 'block';
    pullStatus.textContent = 'Starting pull...';
    progressBar.style.width = '10%';

    try {
        const response = await fetch('/api/models/pull', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName})
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || `Request failed (${response.status})`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const {done, value} = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n').filter(line => line.startsWith('data: '));

            for (const line of lines) {
                const data = JSON.parse(line.substring(6));

                if (data.error) {
                    throw new Error(data.error);
                }

                if (data.status) {
                    pullStatus.textContent = data.status;
                    if (data.completed && data.total) {
                        const percent = (data.completed / data.total) * 100;
                        progressBar.style.width = percent + '%';
                    }
                }
            }
        }

        pullStatus.textContent = 'Pull completed!';
        progressBar.style.width = '100%';
        showToast('Success', `${modelName} pulled successfully`, 'success');

        setTimeout(() => {
            pullProgress.style.display = 'none';
            modelSelect.value = '';
            document.getElementById('custom-model-group').style.display = 'none';
            document.getElementById('custom-model-name').value = '';
            loadModels();
        }, 2000);
    } catch (error) {
        pullStatus.textContent = 'Error: ' + error.message;
        showToast('Error', error.message, 'danger');
    } finally {
        pullBtn.disabled = false;
    }
});

// Test connection
document.getElementById('test-connection-btn').addEventListener('click', async () => {
    const statusSpan = document.getElementById('connection-status');
    statusSpan.className = 'badge bg-secondary';
    statusSpan.textContent = 'Testing...';

    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        if (data.ollama) {
            statusSpan.className = 'badge bg-success';
            statusSpan.textContent = 'Connected';
            showToast('Success', 'Ollama is running', 'success');
        } else {
            statusSpan.className = 'badge bg-danger';
            statusSpan.textContent = 'Disconnected';
            showToast('Error', 'Cannot connect to Ollama', 'danger');
        }
    } catch (error) {
        statusSpan.className = 'badge bg-danger';
        statusSpan.textContent = 'Error';
        showToast('Error', error.message, 'danger');
    }
});

// Helper functions
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

function showToast(title, message, type) {
    const container = document.getElementById('toast-container');
    const id = 'toast-' + Date.now();
    const bgClass = type === 'success' ? 'text-bg-success' : type === 'danger' ? 'text-bg-danger' : type === 'info' ? 'text-bg-info' : 'text-bg-secondary';
    container.insertAdjacentHTML('beforeend', `
        <div id="${id}" class="toast align-items-center ${bgClass} border-0 mb-2" role="alert">
            <div class="d-flex">
                <div class="toast-body"><strong>${title}:</strong> ${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>`);
    const toastEl = document.getElementById(id);
    new bootstrap.Toast(toastEl, {delay: 4000}).show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// Load on page load
loadModels();

// Replaces an inline onclick; see the note in statusbar.js (audit M6).
document.getElementById('refresh-models-btn')?.addEventListener('click', () => loadModels());
