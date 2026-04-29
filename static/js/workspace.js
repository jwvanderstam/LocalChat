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
            workspaces.forEach(function (ws) {
                const li = document.createElement('li');
                const a = document.createElement('a');
                a.className = 'dropdown-item' + (ws.active ? ' active' : '');
                a.href = '#';
                a.dataset.workspaceId = ws.id;
                a.textContent = ws.name;
                if (ws.active) {
                    document.getElementById('active-workspace-name').textContent = ws.name;
                    localStorage.setItem(ACTIVE_WS_KEY,    ws.name);
                    localStorage.setItem(ACTIVE_WS_ID_KEY, ws.id);
                }
                a.addEventListener('click', function (e) {
                    e.preventDefault();
                    switchWorkspace(ws.id, ws.name);
                });
                li.appendChild(a);
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
