// Users tab in Settings. Admin-only; the tab appears once the server confirms that,
// but every route behind it is admin-guarded regardless — hiding is presentation.
//
// Each user is a card showing their workspace access, because that is what decides
// whether the account can do anything at all. A user with no workspace can sign in
// and see nothing, so the empty state says so instead of looking tidy.

(function () {
'use strict';

let usersGrid = null;
let usersAlert = null;
let workspaces = [];

// ---- helpers ---------------------------------------------------------------

function esc(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

function notify(message, kind = 'danger') {
    if (!usersAlert) return;
    usersAlert.className = `alert alert-${kind} py-2 small`;
    usersAlert.textContent = message;
    setTimeout(() => usersAlert.classList.add('d-none'), kind === 'success' ? 4000 : 8000);
}

function inlineError(el, message) {
    el.textContent = message;
    el.classList.remove('d-none');
}

async function api(url, options = {}) {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        // A 409 carries a precondition the server enforced — last admin, last owner,
        // purge blocked by membership. Its message is the useful one to show.
        throw new Error(data.message || `Request failed (${resp.status})`);
    }
    return data;
}

const ROLE_BADGE = { owner: 'bg-primary', editor: 'bg-success', viewer: 'bg-secondary' };

// ---- rendering -------------------------------------------------------------

function renderUserCard(user, memberships) {
    const retired = Boolean(user.deleted_at);
    const isAdmin = user.role === 'admin';

    const access = memberships.length
        ? memberships.map((w) => `
            <span class="badge ${ROLE_BADGE[w.role] || 'bg-secondary'} me-1 mb-1">
                ${esc(w.name)} · ${esc(w.role)}
                ${retired ? '' : `<a href="#" class="text-white ms-1 text-decoration-none"
                     data-revoke="${user.id}" data-ws="${w.id}" data-wsname="${esc(w.name)}"
                     title="Remove access">&times;</a>`}
            </span>`).join('')
        : `<span class="badge bg-warning text-dark">
               <i class="bi bi-exclamation-triangle me-1"></i>No workspace — cannot use the app
           </span>`;

    return `
    <div class="col-12 col-lg-6">
      <div class="card h-100 ${retired ? 'opacity-50' : ''}">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <div>
              <h6 class="mb-1">
                <i class="bi bi-person-circle me-1"></i>${esc(user.username)}
                ${isAdmin ? '<span class="badge bg-warning text-dark ms-1">admin</span>' : ''}
                ${retired ? '<span class="badge bg-secondary ms-1">retired</span>' : ''}
              </h6>
              <div class="text-muted small">${esc(user.email || 'no email')}</div>
            </div>
            <div class="btn-group btn-group-sm">
              ${retired ? `
                <button class="btn btn-outline-danger" data-purge="${user.id}"
                        data-name="${esc(user.username)}" title="Delete permanently">
                  <i class="bi bi-trash"></i>
                </button>` : `
                <button class="btn btn-outline-secondary" data-role="${user.id}"
                        data-current="${user.role}" title="${isAdmin ? 'Make normal user' : 'Make admin'}">
                  <i class="bi bi-shield${isAdmin ? '-slash' : '-check'}"></i>
                </button>
                <button class="btn btn-outline-warning" data-retire="${user.id}"
                        data-name="${esc(user.username)}" title="Retire (reversible)">
                  <i class="bi bi-person-dash"></i>
                </button>`}
            </div>
          </div>
          <div class="mb-2">${access}</div>
          ${retired ? '' : `
            <button class="btn btn-sm btn-outline-primary" data-grant="${user.id}"
                    data-name="${esc(user.username)}">
              <i class="bi bi-plus-lg me-1"></i>Add workspace
            </button>`}
        </div>
      </div>
    </div>`;
}

async function loadUsers() {
    try {
        const data = await api('/api/users?include_retired=true');
        const users = data.users || [];
        // One request per user. Fine at the scale ADR-1 describes (<= 25 users), and it
        // avoids inventing a bulk endpoint that exists only for this screen.
        const memberships = await Promise.all(
            users.map((u) =>
                api(`/api/users/${u.id}/workspaces`)
                    .then((d) => d.workspaces || [])
                    .catch(() => [])),
        );
        usersGrid.innerHTML = users.map((u, i) => renderUserCard(u, memberships[i])).join('');
    } catch (err) {
        notify(err.message);
    }
}

// ---- API keys --------------------------------------------------------------

function keysNotify(message, kind = 'danger') {
    const box = document.getElementById('keys-alert');
    if (!box) return;
    box.className = `alert alert-${kind} py-2 small`;
    box.textContent = message;
    setTimeout(() => box.classList.add('d-none'), kind === 'success' ? 4000 : 8000);
}

function renderKeyRow(key, workspace) {
    const used = key.last_used_at
        ? new Date(key.last_used_at).toLocaleString()
        : '<span class="text-muted">never</span>';
    return `
    <tr>
      <td>${esc(key.name)}</td>
      <td><span class="badge bg-light text-dark border">${esc(workspace.name)}</span></td>
      <td><span class="badge ${ROLE_BADGE[key.role] || 'bg-secondary'}">${esc(key.role)}</span></td>
      <td><code class="small">${esc(key.key_prefix)}…</code></td>
      <td class="small">${used}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-danger" data-revoke-key="${key.id}"
                data-ws="${workspace.id}" data-name="${esc(key.name)}" title="Revoke">
          <i class="bi bi-x-circle"></i>
        </button>
      </td>
    </tr>`;
}

async function loadKeys() {
    const body = document.getElementById('keys-body');
    if (!body) return;
    // One request per workspace: the endpoint is workspace-scoped, and at ADR-1's
    // scale that is cheaper than inventing a cross-workspace listing route.
    const perWorkspace = await Promise.all(
        workspaces.map((w) =>
            api(`/api/workspaces/${w.id}/keys`)
                .then((d) => (d.keys || []).map((k) => renderKeyRow(k, w)))
                .catch(() => [])),
    );
    const rows = perWorkspace.flat();
    body.innerHTML = rows.length ? rows.join('') : `
      <tr><td colspan="6" class="text-muted small py-3">
        No keys yet. A bot or workflow needs one to reach a workspace.
      </td></tr>`;
}

async function loadWorkspaces() {
    try {
        workspaces = (await api('/api/workspaces')).workspaces || [];
    } catch (err) {
        workspaces = [];
    }
}

function fillWorkspaceSelect(select) {
    select.innerHTML = workspaces.length
        ? workspaces.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join('')
        : '<option value="">No workspaces available</option>';
}

// ---- actions ---------------------------------------------------------------

async function act(fn, okMessage) {
    try {
        await fn();
        notify(okMessage, 'success');
        await loadUsers();
    } catch (err) {
        notify(err.message);
    }
}

function initUsers() {
    usersGrid = document.getElementById('users-grid');
    usersAlert = document.getElementById('users-alert');
    if (!usersGrid) return;  // not the settings page

    usersGrid.addEventListener('click', async (event) => {
        const el = event.target.closest('[data-role],[data-retire],[data-purge],[data-grant],[data-revoke]');
        if (!el) return;
        event.preventDefault();

        if (el.dataset.role) {
            const next = el.dataset.current === 'admin' ? 'user' : 'admin';
            await act(() => api(`/api/users/${el.dataset.role}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: next }),
            }), `Account type changed to ${next}.`);
        }

        if (el.dataset.retire) {
            if (!await window.localchatConfirm({
                title: `Retire ${el.dataset.name}?`,
                body: 'They keep their documents and history, and can be restored.',
                confirmText: 'Retire',
                danger: false,
            })) return;
            await act(() => api(`/api/users/${el.dataset.retire}`, { method: 'DELETE' }), 'User retired.');
        }

        if (el.dataset.purge) {
            if (!await window.localchatConfirm({
                title: `Permanently delete ${el.dataset.name}?`,
                body: 'This cannot be undone, and is refused while they still belong to a workspace.',
                confirmText: 'Delete permanently',
            })) return;
            await act(() => api(`/api/users/${el.dataset.purge}/purge`, { method: 'DELETE' }), 'User deleted.');
        }

        if (el.dataset.revoke) {
            if (!await window.localchatConfirm({
                title: 'Remove access',
                body: `Access to ${el.dataset.wsname} will be removed.`,
                confirmText: 'Remove',
            })) return;
            await act(() => api(`/api/users/${el.dataset.revoke}/workspaces/${el.dataset.ws}`,
                { method: 'DELETE' }), 'Access removed.');
        }

        if (el.dataset.grant) {
            document.getElementById('ug-userid').value = el.dataset.grant;
            document.getElementById('ug-username').textContent = el.dataset.name;
            document.getElementById('ug-error').classList.add('d-none');
            fillWorkspaceSelect(document.getElementById('ug-workspace'));
            bootstrap.Modal.getOrCreateInstance(document.getElementById('user-grant-modal')).show();
        }
    });

    const createBtn = document.getElementById('user-create-btn');
    if (createBtn) {
        createBtn.addEventListener('click', () => {
            document.getElementById('user-create-form').reset();
            document.getElementById('nu-error').classList.add('d-none');
            fillWorkspaceSelect(document.getElementById('nu-workspace'));
            bootstrap.Modal.getOrCreateInstance(document.getElementById('user-create-modal')).show();
        });
    }

    const createForm = document.getElementById('user-create-form');
    if (createForm) {
        createForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const errorBox = document.getElementById('nu-error');
            errorBox.classList.add('d-none');
            try {
                await api('/api/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: document.getElementById('nu-username').value.trim(),
                        password: document.getElementById('nu-password').value,
                        role: document.getElementById('nu-role').value,
                        workspace_id: document.getElementById('nu-workspace').value,
                        workspace_role: document.getElementById('nu-wsrole').value,
                    }),
                });
                bootstrap.Modal.getInstance(document.getElementById('user-create-modal')).hide();
                notify('User created.', 'success');
                await loadUsers();
            } catch (err) {
                inlineError(errorBox, err.message);
            }
        });
    }

    const keyCreateBtn = document.getElementById('key-create-btn');
    if (keyCreateBtn) {
        keyCreateBtn.addEventListener('click', () => {
            document.getElementById('key-create-form').reset();
            document.getElementById('nk-error').classList.add('d-none');
            fillWorkspaceSelect(document.getElementById('nk-workspace'));
            bootstrap.Modal.getOrCreateInstance(document.getElementById('key-create-modal')).show();
        });
    }

    const keyForm = document.getElementById('key-create-form');
    if (keyForm) {
        keyForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const errorBox = document.getElementById('nk-error');
            errorBox.classList.add('d-none');
            const workspaceId = document.getElementById('nk-workspace').value;
            try {
                const data = await api(`/api/workspaces/${workspaceId}/keys`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: document.getElementById('nk-name').value.trim(),
                        role: document.getElementById('nk-role').value,
                    }),
                });
                bootstrap.Modal.getInstance(document.getElementById('key-create-modal')).hide();
                // The server returns the key once and stores only its hash; if this
                // modal does not show it, it is gone.
                document.getElementById('kr-value').value = data.key || '';
                bootstrap.Modal.getOrCreateInstance(document.getElementById('key-reveal-modal')).show();
                await loadKeys();
            } catch (err) {
                inlineError(errorBox, err.message);
            }
        });
    }

    const copyBtn = document.getElementById('kr-copy');
    if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
            const field = document.getElementById('kr-value');
            try {
                await navigator.clipboard.writeText(field.value);
            } catch (err) {
                field.select();  // clipboard needs HTTPS or localhost; selecting still works
            }
            copyBtn.innerHTML = '<i class="bi bi-check2"></i> Copied';
        });
    }

    const keysBody = document.getElementById('keys-body');
    if (keysBody) {
        keysBody.addEventListener('click', async (event) => {
            const el = event.target.closest('[data-revoke-key]');
            if (!el) return;
            if (!await window.localchatConfirm({
                title: `Revoke ${el.dataset.name}?`,
                body: 'Anything using this key stops working immediately.',
                confirmText: 'Revoke',
            })) return;
            try {
                await api(`/api/workspaces/${el.dataset.ws}/keys/${el.dataset.revokeKey}`,
                    { method: 'DELETE' });
                keysNotify('Key revoked.', 'success');
                await loadKeys();
            } catch (err) {
                keysNotify(err.message);
            }
        });
    }

    const grantForm = document.getElementById('user-grant-form');
    if (grantForm) {
        grantForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const errorBox = document.getElementById('ug-error');
            errorBox.classList.add('d-none');
            try {
                await api(`/api/users/${document.getElementById('ug-userid').value}/workspaces`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        workspace_id: document.getElementById('ug-workspace').value,
                        role: document.getElementById('ug-role').value,
                    }),
                });
                bootstrap.Modal.getInstance(document.getElementById('user-grant-modal')).hide();
                notify('Access granted.', 'success');
                await loadUsers();
            } catch (err) {
                inlineError(errorBox, err.message);
            }
        });
    }

    start();
}

async function start() {
    const tabItem = document.getElementById('users-tab-item');
    if (!tabItem) return;
    try {
        const me = await (await fetch('/api/users/me')).json();
        if (me.role !== 'admin') return;  // leave the tab hidden
    } catch (e) {
        return;  // a failed check must not reveal an admin surface
    }
    tabItem.classList.remove('d-none');
    await loadWorkspaces();
    await loadUsers();
    await loadKeys();  // after loadWorkspaces: keys are listed per workspace
}

// Elements are resolved inside initUsers, not here: when the DOM is still parsing we
// wait for DOMContentLoaded, and anything captured now would be null forever.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUsers);
} else {
    initUsers();
}
})();
