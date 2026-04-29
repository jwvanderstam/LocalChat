/**
 * Workspace switcher — loads workspaces into the navbar dropdown,
 * switches on click, and provides a modal to create new workspaces.
 */

(function () {
    'use strict';

    const ACTIVE_WS_KEY    = 'localchat_active_workspace';
    const ACTIVE_WS_ID_KEY = 'localchat_active_workspace_id';

    function renderWorkspaceList(workspaces) {
        const list = document.getElementById('workspace-list');
        if (!list) return;

        list.innerHTML = '';

        if (!workspaces || workspaces.length === 0) {
            const empty = document.createElement('li');
            empty.innerHTML = '<span class="dropdown-item-text text-muted small">No workspaces found</span>';
            list.appendChild(empty);
        } else {
            const canDelete = workspaces.length > 1;
            workspaces.forEach(function (ws) {
                if (ws.active) {
                    document.getElementById('active-workspace-name').textContent = ws.name;
                    localStorage.setItem(ACTIVE_WS_KEY,    ws.name);
                    localStorage.setItem(ACTIVE_WS_ID_KEY, ws.id);
                }

                const li = document.createElement('li');

                // Wrapper div acts as the dropdown item so we can flex name + button.
                const row = document.createElement('div');
                row.className = 'dropdown-item d-flex align-items-center gap-1 pe-1'
                    + (ws.active ? ' active' : '');
                row.style.cursor = 'pointer';

                const nameSpan = document.createElement('span');
                nameSpan.className = 'flex-grow-1 text-truncate';
                nameSpan.textContent = ws.name;
                nameSpan.addEventListener('click', function () {
                    switchWorkspace(ws.id, ws.name);
                });

                row.appendChild(nameSpan);

                if (canDelete) {
                    const delBtn = document.createElement('button');
                    delBtn.className = 'btn btn-link btn-sm p-0 ms-1 text-danger opacity-50';
                    delBtn.style.lineHeight = '1';
                    delBtn.title = 'Delete workspace';
                    delBtn.innerHTML = '<i class="bi bi-trash" style="font-size:0.75rem;pointer-events:none;"></i>';
                    delBtn.addEventListener('click', function (e) {
                        e.stopPropagation();
                        deleteWorkspace(ws.id, ws.name);
                    });
                    row.appendChild(delBtn);
                }

                li.appendChild(row);
                list.appendChild(li);
            });
        }

        const divider = document.createElement('li');
        divider.innerHTML = '<hr class="dropdown-divider">';
        list.appendChild(divider);

        const newItem = document.createElement('li');
        const newLink = document.createElement('a');
        newLink.className = 'dropdown-item';
        newLink.href = '#';
        newLink.innerHTML = '<i class="bi bi-plus-circle me-1"></i>New workspace…';
        newLink.addEventListener('click', function (e) {
            e.preventDefault();
            openNewWorkspaceModal();
        });
        newItem.appendChild(newLink);
        list.appendChild(newItem);
    }

    function loadWorkspaces() {
        const cachedId   = localStorage.getItem(ACTIVE_WS_ID_KEY);
        const cachedName = localStorage.getItem(ACTIVE_WS_KEY);

        // Show cached name immediately while the fetch is in flight.
        if (cachedName) {
            const el = document.getElementById('active-workspace-name');
            if (el) el.textContent = cachedName;
        }

        const headers = cachedId ? { 'X-Workspace-ID': cachedId } : {};
        fetch('/api/workspaces', { headers })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) return;
                const workspaces = data.workspaces || [];

                // First-load: no workspace stored yet — default to first in list.
                if (!cachedId && workspaces.length > 0) {
                    const first = workspaces[0];
                    localStorage.setItem(ACTIVE_WS_ID_KEY, first.id);
                    localStorage.setItem(ACTIVE_WS_KEY,    first.name);
                    first.active = true;
                }

                renderWorkspaceList(workspaces);
            })
            .catch(function (err) {
                console.warn('[Workspace] Failed to load workspaces:', err);
            });
    }

    function switchWorkspace(workspaceId, workspaceName) {
        fetch('/api/workspaces/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workspace_id: workspaceId }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    localStorage.setItem(ACTIVE_WS_ID_KEY, workspaceId);
                    localStorage.setItem(ACTIVE_WS_KEY,    workspaceName);
                    document.getElementById('active-workspace-name').textContent = workspaceName;
                    loadWorkspaces();
                    // Notify other modules so they reload their workspace-scoped data.
                    document.dispatchEvent(new CustomEvent('workspace-switched', {
                        detail: { workspaceId: workspaceId, workspaceName: workspaceName },
                    }));
                } else {
                    console.warn('[Workspace] Switch failed:', data.message);
                }
            })
            .catch(function (err) {
                console.warn('[Workspace] Switch request failed:', err);
            });
    }

    function deleteWorkspace(workspaceId, workspaceName) {
        if (!confirm('Delete workspace "' + workspaceName + '"?\n\nThis cannot be undone.')) {
            return;
        }
        fetch('/api/workspaces/' + workspaceId, { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) {
                    alert('Failed to delete workspace: ' + (data.message || 'Unknown error'));
                    return;
                }
                const fallbackId = data.fallback_workspace_id;
                // Clear stored state for the deleted workspace.
                if (localStorage.getItem(ACTIVE_WS_ID_KEY) === workspaceId) {
                    localStorage.removeItem(ACTIVE_WS_ID_KEY);
                    localStorage.removeItem(ACTIVE_WS_KEY);
                }
                // Switch to the fallback workspace so the UI is never left in a void.
                if (fallbackId) {
                    fetch('/api/workspaces/' + fallbackId)
                        .then(function (r) { return r.json(); })
                        .then(function (wsData) {
                            const name = wsData.workspace ? wsData.workspace.name : 'Default';
                            switchWorkspace(fallbackId, name);
                        })
                        .catch(function () { loadWorkspaces(); });
                } else {
                    loadWorkspaces();
                }
            })
            .catch(function (err) {
                console.warn('[Workspace] Delete request failed:', err);
            });
    }

    function openNewWorkspaceModal() {
        const modalEl = document.getElementById('newWorkspaceModal');
        if (!modalEl) return;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    document.addEventListener('DOMContentLoaded', function () {
        loadWorkspaces();

        // Tooltip on the info icon
        const tooltipEl = document.getElementById('workspace-info-tooltip');
        if (tooltipEl) {
            new bootstrap.Tooltip(tooltipEl);
        }

        // New workspace form submit
        const form = document.getElementById('newWorkspaceForm');
        if (!form) return;

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            const errorEl = document.getElementById('ws-error');
            errorEl.textContent = '';

            const name = document.getElementById('ws-name').value.trim();
            if (!name) return;

            fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    description: document.getElementById('ws-description').value.trim(),
                    system_prompt: document.getElementById('ws-system-prompt').value.trim(),
                }),
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.success) {
                        bootstrap.Modal.getInstance(document.getElementById('newWorkspaceModal')).hide();
                        form.reset();
                        switchWorkspace(data.workspace.id, data.workspace.name);
                    } else {
                        errorEl.textContent = data.message || 'Failed to create workspace';
                    }
                })
                .catch(function () {
                    errorEl.textContent = 'Request failed, please try again.';
                });
        });
    });
})();
