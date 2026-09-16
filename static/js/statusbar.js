// Extracted verbatim from templates/base.html so the Content-Security-Policy can drop
// 'unsafe-inline' for scripts (audit M6). The template carried no Jinja
// interpolation here, so this is the same code in a file the browser fetches
// from this origin, loaded at the point the inline block used to run.

// Render cached model name immediately to avoid "Loading..." flash on navigation
const _cachedModel = localStorage.getItem('lc-active-model');
if (_cachedModel) document.getElementById('active-model').textContent = _cachedModel;

// Update status bar
function updateStatus() {
    // The workspace header matters: /api/status scopes document_count to the
    // active workspace, and without it the badge reports the total across all
    // of them — a global number sitting next to a workspace switcher.
    const _wsId = localStorage.getItem('localchat_active_workspace_id');
    fetch('/api/status', { headers: _wsId ? { 'X-Workspace-ID': _wsId } : {} })
        .then(response => response.json())
        .then(data => {
            // Update model
            const modelName = data.active_model || 'None';
            document.getElementById('active-model').textContent = modelName;
            localStorage.setItem('lc-active-model', modelName);

            // Update document count
            document.getElementById('doc-count').textContent =
                data.document_count || 0;

            // Update service status
            const ollamaStatus = document.getElementById('ollama-status');
            const dbStatus = document.getElementById('db-status');

            if (data.ollama) {
                ollamaStatus.classList.remove('bg-secondary');
                ollamaStatus.classList.add('bg-success');
            } else {
                ollamaStatus.classList.remove('bg-success');
                ollamaStatus.classList.add('bg-danger');
            }

            if (data.database) {
                dbStatus.classList.remove('bg-secondary');
                dbStatus.classList.add('bg-success');
            } else {
                dbStatus.classList.remove('bg-success');
                dbStatus.classList.add('bg-danger');
            }

            // Show model override input when router is active
            const overrideContainer = document.getElementById('model-override-container');
            if (overrideContainer) {
                overrideContainer.style.display =
                    data.features && data.features.model_router ? 'flex' : 'none';
            }
        })
        .catch(error => {
            console.error('Error updating status:', error);
        });
}

// Update status on load and every 5 seconds
updateStatus();
setInterval(updateStatus, 5000);
// Model Management calls this after activating a model: a five-second wait
// to learn which model is active reads as the badge being broken.
window.refreshStatusBadges = updateStatus;

// ── Event wiring ──────────────────────────────────────────────────────────────
// These replace inline `on*=` attributes, which a Content-Security-Policy without
// 'unsafe-inline' blocks wherever the markup came from (audit M6).
document.getElementById('logout-link')?.addEventListener('click', (event) => {
    event.preventDefault();
    window.localchatLogout();
});
