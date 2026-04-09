/**
 * Workspace switcher — loads workspaces into the navbar dropdown and
 * sends a switch request when the user picks one.
 */

(function () {
    'use strict';

    const ACTIVE_WS_KEY = 'localchat_active_workspace';

    function renderWorkspaceList(workspaces) {
        const list = document.getElementById('workspace-list');
        if (!list) return;

        list.innerHTML = '';

        if (!workspaces || workspaces.length === 0) {
            list.innerHTML = '<li><span class="dropdown-item-text text-muted small">No workspaces found</span></li>';
            return;
        }

        workspaces.forEach(function (ws) {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item' + (ws.active ? ' active' : '');
            a.href = '#';
            a.dataset.workspaceId = ws.id;
            a.textContent = ws.name;
            if (ws.active) {
                document.getElementById('active-workspace-name').textContent = ws.name;
                localStorage.setItem(ACTIVE_WS_KEY, ws.name);
            }
            a.addEventListener('click', function (e) {
                e.preventDefault();
                switchWorkspace(ws.id, ws.name);
            });
            li.appendChild(a);
            list.appendChild(li);
        });
    }

    function loadWorkspaces() {
        fetch('/api/workspaces')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    renderWorkspaceList(data.workspaces);
                }
            })
            .catch(function (err) {
                console.warn('[Workspace] Failed to load workspaces:', err);
            });

        // Restore label from cache immediately to avoid flicker
        const cached = localStorage.getItem(ACTIVE_WS_KEY);
        if (cached) {
            const el = document.getElementById('active-workspace-name');
            if (el) el.textContent = cached;
        }
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
                    localStorage.setItem(ACTIVE_WS_KEY, workspaceName);
                    document.getElementById('active-workspace-name').textContent = workspaceName;
                    loadWorkspaces();
                } else {
                    console.warn('[Workspace] Switch failed:', data.message);
                }
            })
            .catch(function (err) {
                console.warn('[Workspace] Switch request failed:', err);
            });
    }

    document.addEventListener('DOMContentLoaded', loadWorkspaces);
})();
