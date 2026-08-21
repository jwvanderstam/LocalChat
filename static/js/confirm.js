/*
 * In-app confirmation dialog, replacing the native confirm().
 *
 * The destructive actions were the only ones still using confirm() while rename and
 * every other prompt used an in-app modal — the dangerous half of the app behaving
 * unlike the rest. A native dialog is also outside the page: it cannot be styled,
 * positioned, or told apart from a browser prompt, and automation drives it blind.
 * A QA pass lost a document to exactly that, by accepting a dialog it meant to dismiss.
 *
 * Exposed on window rather than exported: the call sites are a mix of ES modules and
 * plain scripts, and auth.js already establishes the global-helper pattern.
 */
(function () {
'use strict';

function esc(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Ask the user to confirm an action.
 *
 * @param {object} options
 * @param {string} options.title        Heading, e.g. "Delete conversation".
 * @param {string} options.body         What will happen. Rendered as text, not markup.
 * @param {string} [options.confirmText] Label on the confirming button.
 * @param {boolean} [options.danger]    Style the confirm button as destructive.
 * @returns {Promise<boolean>} true when confirmed, false when dismissed any other way.
 */
function localchatConfirm(options) {
    const opts = options || {};
    const modalEl = document.getElementById('confirmModal');

    // No modal on the page (an unexpected template, or a test harness) — fall back to
    // the native dialog rather than silently proceeding with a destructive action.
    if (!modalEl || typeof bootstrap === 'undefined') {
        const text = [opts.title, opts.body].filter(Boolean).join('\n\n');
        return Promise.resolve(window.confirm(text));
    }

    document.getElementById('confirmModalLabel').textContent = opts.title || 'Are you sure?';
    document.getElementById('confirm-modal-body').innerHTML = esc(opts.body || '')
        .replace(/\n/g, '<br>');

    const confirmBtn = document.getElementById('confirm-modal-accept');
    confirmBtn.textContent = opts.confirmText || 'Confirm';
    confirmBtn.className = 'btn btn-sm ' + (opts.danger === false ? 'btn-primary' : 'btn-danger');

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    return new Promise((resolve) => {
        let accepted = false;

        function onAccept() {
            accepted = true;
            modal.hide();
        }
        // Resolving on hide rather than on the button covers every dismissal —
        // backdrop click, Escape, the close button — with one answer: false.
        function onHidden() {
            confirmBtn.removeEventListener('click', onAccept);
            modalEl.removeEventListener('hidden.bs.modal', onHidden);
            resolve(accepted);
        }

        confirmBtn.addEventListener('click', onAccept);
        modalEl.addEventListener('hidden.bs.modal', onHidden);
        modal.show();
    });
}

window.localchatConfirm = localchatConfirm;
})();
