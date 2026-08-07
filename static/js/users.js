// Users tab in Settings (AUTH-2). Admin-only, and the tab only appears once the
// server has said so — but the routes behind it are admin-guarded either way, so
// hiding here is presentation, never protection.

(function () {
'use strict';

// Resolved in initUsers(), not here: when the DOM is still parsing we wait for
// DOMContentLoaded, and elements captured now would be null forever.
let usersTbody = null;
let usersAlert = null;

function showAlert(message, kind = 'danger') {
    if (!usersAlert) return;
    usersAlert.className = `alert alert-${kind} py-2 small`;
    usersAlert.textContent = message;
    usersAlert.style.display = '';
}

function clearAlert() {
    if (usersAlert) usersAlert.style.display = 'none';
}

async function revealForAdmins() {
    const tabItem = document.getElementById('users-tab-item');
    if (!tabItem) return false;
    try {
        const resp = await fetch('/api/users/me');
        if (!resp.ok) return false;
        const me = await resp.json();
        if (me.role === 'admin') {
            tabItem.classList.remove('d-none');
            return true;
        }
    } catch (e) {
        // Leave it hidden. A failed check must not reveal an admin surface.
    }
    return false;
}

function renderUsers(users) {
    usersTbody.innerHTML = users.map((u) => {
        const retired = Boolean(u.deleted_at);
        // Retired users stay visible rather than disappearing: their documents and
        // conversations still reference them, so hiding them would make the list
        // disagree with the data.
        return `
        <tr class="${retired ? 'opacity-50' : ''}">
            <td>${escapeHtml(u.username)}${retired ? ' <span class="badge bg-secondary">retired</span>' : ''}</td>
            <td>${escapeHtml(u.email || '—')}</td>
            <td><span class="badge bg-${u.role === 'admin' ? 'warning text-dark' : 'secondary'}">${escapeHtml(u.role)}</span></td>
            <td>${u.is_active === false ? 'inactive' : 'active'}</td>
            <td class="text-end">
                ${retired ? `
                    <button class="btn btn-sm btn-outline-danger" data-purge="${u.id}" data-name="${escapeHtml(u.username)}">
                        Purge
                    </button>` : `
                    <button class="btn btn-sm btn-outline-secondary" data-role="${u.id}" data-current="${u.role}">
                        ${u.role === 'admin' ? 'Make user' : 'Make admin'}
                    </button>
                    <button class="btn btn-sm btn-outline-warning" data-retire="${u.id}" data-name="${escapeHtml(u.username)}">
                        Retire
                    </button>`}
            </td>
        </tr>`;
    }).join('');
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

async function loadUsers() {
    clearAlert();
    try {
        // include_retired: a retired user still owns documents and conversations, so
        // the list must show them rather than pretend they are gone.
        const resp = await fetch('/api/users?include_retired=true');
        if (!resp.ok) return;
        const data = await resp.json();
        renderUsers(data.users || []);
    } catch (e) {
        showAlert('Could not load users.');
    }
}

async function send(url, options, okMessage) {
    clearAlert();
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));
    if (resp.ok) {
        showAlert(okMessage, 'success');
        await loadUsers();
        return true;
    }
    // 409 carries a precondition the server enforced — last admin, or a purge
    // blocked by workspace membership. Its message is the useful one.
    showAlert(data.message || `Request failed (${resp.status})`);
    return false;
}

function initUsers() {
    usersTbody = document.getElementById('users-tbody');
    usersAlert = document.getElementById('users-alert');
    if (!usersTbody) return;  // not the settings page

    usersTbody.addEventListener('click', async (event) => {
        const btn = event.target.closest('button');
        if (!btn) return;

        if (btn.dataset.role) {
            const next = btn.dataset.current === 'admin' ? 'user' : 'admin';
            await send(`/api/users/${btn.dataset.role}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: next }),
            }, `Role changed to ${next}.`);
        }

        if (btn.dataset.retire) {
            if (!confirm(`Retire ${btn.dataset.name}? They keep their history and can be restored.`)) return;
            await send(`/api/users/${btn.dataset.retire}`, { method: 'DELETE' }, 'User retired.');
        }

        if (btn.dataset.purge) {
            // Deliberately heavier than retiring: this one cannot be undone.
            if (!confirm(
                `Permanently delete ${btn.dataset.name}?\n\n` +
                'This cannot be undone. It is refused if the user still belongs to any workspace.'
            )) return;
            await send(`/api/users/${btn.dataset.purge}/purge`, { method: 'DELETE' }, 'User purged.');
        }
    });

    const createBtn = document.getElementById('user-create-btn');
    if (createBtn) {
        createBtn.addEventListener('click', async () => {
            const username = prompt('Username for the new user:');
            if (!username) return;
            const password = prompt(`Initial password for ${username}:`);
            if (!password) return;
            await send('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, role: 'user' }),
            }, `User ${username} created.`);
        });
    }

    start();
}

async function start() {
    if (await revealForAdmins()) loadUsers();
}

// The script tag sits at the end of <body>, but do not depend on that: if the DOM
// is already parsed, DOMContentLoaded has fired and a listener would never run.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUsers);
} else {
    initUsers();
}
})();
