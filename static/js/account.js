/*
 * Settings → Account: a signed-in user changes their own password.
 *
 * POST /api/users/me/password decides; the checks here only save a round trip for
 * the mistakes a user can see for themselves. A wrong current password comes back
 * as 400, not 401, so auth.js does not mistake it for an expired session.
 */
(function () {
'use strict';

// Mirrors config.USER_PASSWORD_MIN_LENGTH. The server enforces it either way; this
// only lets the form say so before sending.
const MIN_LENGTH = 12;

function initAccount() {
    const form = document.getElementById('change-password-form');
    if (!form) return;
    const current = document.getElementById('current-password');
    const fresh = document.getElementById('new-password');
    const confirmation = document.getElementById('confirm-password');
    const status = document.getElementById('password-status');

    function say(message, ok) {
        status.textContent = message;
        status.className = 'small ms-2 ' + (ok ? 'text-success' : 'text-danger');
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!current.value || !fresh.value) {
            say('Fill in your current and your new password.', false);
            return;
        }
        if (fresh.value.length < MIN_LENGTH) {
            say(`The new password needs at least ${MIN_LENGTH} characters.`, false);
            return;
        }
        if (fresh.value !== confirmation.value) {
            say('The new passwords do not match.', false);
            return;
        }
        try {
            const resp = await fetch('/api/users/me/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: current.value,
                    new_password: fresh.value,
                }),
            });
            const data = await resp.json();
            if (!data.success) {
                say(data.message || 'The password was not changed.', false);
                return;
            }
        } catch (err) {
            say('The password was not changed: the server could not be reached.', false);
            return;
        }
        current.value = '';
        fresh.value = '';
        confirmation.value = '';
        say('Password changed.', true);
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAccount);
} else {
    initAccount();
}
})();
