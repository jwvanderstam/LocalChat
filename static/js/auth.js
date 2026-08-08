// Session handling: redirect to the login page when the server says we are not
// authenticated, and drive the login form itself.
//
// The session token is an httpOnly cookie, so nothing here can read it — which is
// the point. `fetch` sends it automatically on same-origin requests, so the 23
// existing call sites needed no change and cannot forget to send it.

const LOGIN_PATH = '/login';

// Pages that must stay reachable without a session, or the redirect loops.
const PUBLIC_PATHS = [LOGIN_PATH];

function redirectToLogin() {
    if (PUBLIC_PATHS.includes(window.location.pathname)) return;
    // Remember where we were so login can return the user there rather than home.
    const next = window.location.pathname + window.location.search;
    window.location.href = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
}

// Wrap fetch once rather than editing every call site: a call site that forgets is
// exactly the drift this session has been correcting elsewhere.
const _originalFetch = window.fetch;
window.fetch = async function (...args) {
    const response = await _originalFetch.apply(this, args);
    if (response.status === 401) {
        redirectToLogin();
    }
    return response;
};

// ---- login form ------------------------------------------------------------

function initLoginForm() {
    const form = document.getElementById('login-form');
    if (!form) return;

    const errorBox = document.getElementById('login-error');
    const submitBtn = document.getElementById('login-submit');

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorBox.style.display = 'none';
        submitBtn.disabled = true;

        try {
            // _originalFetch: the wrapper would bounce a failed login straight back
            // to this page, hiding the error message the user needs to read.
            const response = await _originalFetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value,
                }),
            });

            if (response.ok) {
                // localStorage is per browser, not per user. Whoever signs in next must
                // not inherit the previous account's active workspace: they may have no
                // access to it, and the pages that read this key send it as
                // X-Workspace-ID before the switcher has loaded anything to correct it.
                localStorage.removeItem('localchat_active_workspace_id');
                localStorage.removeItem('localchat_active_workspace');

                const params = new URLSearchParams(window.location.search);
                const next = params.get('next');
                // Only relative paths: an attacker-supplied absolute URL here would
                // make this an open redirect off the back of a real login.
                window.location.href = (next && next.startsWith('/') && !next.startsWith('//'))
                    ? next
                    : '/';
                return;
            }

            const data = await response.json().catch(() => ({}));
            errorBox.textContent = response.status === 429
                ? 'Too many attempts. Wait a minute and try again.'
                : (data.message || 'Login failed');
            errorBox.style.display = '';
        } catch (err) {
            errorBox.textContent = 'Could not reach the server.';
            errorBox.style.display = '';
        } finally {
            submitBtn.disabled = false;
        }
    });
}

// ---- logout ----------------------------------------------------------------

async function logout() {
    try {
        await _originalFetch('/api/logout', { method: 'POST' });
    } catch (err) {
        // Ignore: the cookie is cleared server-side on every path, and if the
        // request never arrived there is nothing to revoke.
    }
    window.location.href = LOGIN_PATH;
}

window.localchatLogout = logout;

// ---- role-aware chrome ------------------------------------------------------

// Elements marked `admin-only` start hidden and are revealed once the server says
// the caller is an admin. Presentation only — every route behind them is guarded
// regardless. Hiding them beats letting them render empty: a tab that shows nothing
// reads as broken, when the truth is that it was never meant for you.
async function revealAdminChrome() {
    const hidden = document.querySelectorAll('.admin-only');
    if (!hidden.length) return;
    try {
        const resp = await _originalFetch('/api/users/me');
        if (!resp.ok) return;
        const me = await resp.json();
        if (me.role !== 'admin') return;
    } catch (e) {
        selectFirstVisibleTab();
        return;  // a failed check must not reveal an admin surface
    }
    hidden.forEach((el) => el.classList.remove('d-none'));
}

// The first Settings tab is admin-only, and it is also the one marked active. Hiding
// it without moving the selection leaves a non-admin staring at an empty panel.
function selectFirstVisibleTab() {
    const list = document.getElementById('settingsTabs') || document.querySelector('.nav-tabs');
    if (!list) return;
    const activeItem = list.querySelector('.nav-link.active')?.closest('.nav-item');
    if (activeItem && !activeItem.classList.contains('d-none')) return;  // still visible

    list.querySelectorAll('.nav-link.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll('.tab-pane.show.active').forEach((el) => el.classList.remove('show', 'active'));

    const firstVisible = [...list.querySelectorAll('.nav-item:not(.d-none) .nav-link')][0];
    if (!firstVisible) return;
    firstVisible.classList.add('active');
    const pane = document.querySelector(firstVisible.getAttribute('href'));
    if (pane) pane.classList.add('show', 'active');
}

document.addEventListener('DOMContentLoaded', () => {
    initLoginForm();
    revealAdminChrome().then(selectFirstVisibleTab);
});
