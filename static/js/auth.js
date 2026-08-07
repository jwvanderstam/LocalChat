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

document.addEventListener('DOMContentLoaded', initLoginForm);
