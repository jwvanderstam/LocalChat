/**
 * settings.js — Theme picker for LocalChat
 *
 * Defines 5 color themes. Applies the saved (or default) theme on every page
 * load via CSS custom properties on <html>. On the Settings → Appearance tab,
 * renders clickable swatches so the user can switch themes.
 *
 * Theme choice is persisted in localStorage under the key 'lc-theme'.
 */

const THEMES = [
    {
        key:        'default',
        label:      'Violet',
        primary:    '#667eea',
        primaryEnd: '#764ba2',
        primaryRgb: '102, 126, 234',
        accent:     '#667eea',
        sidebarBg:  '#f0f2ff',
    },
    {
        key:        'ocean',
        label:      'Ocean',
        primary:    '#0ea5e9',
        primaryEnd: '#0369a1',
        primaryRgb: '14, 165, 233',
        accent:     '#0ea5e9',
        sidebarBg:  '#f0f8ff',
    },
    {
        key:        'forest',
        label:      'Forest',
        primary:    '#10b981',
        primaryEnd: '#065f46',
        primaryRgb: '16, 185, 129',
        accent:     '#10b981',
        sidebarBg:  '#f0fdf4',
    },
    {
        key:        'rose',
        label:      'Rose',
        primary:    '#f43f5e',
        primaryEnd: '#be123c',
        primaryRgb: '244, 63, 94',
        accent:     '#f43f5e',
        sidebarBg:  '#fff1f2',
    },
    {
        key:        'slate',
        label:      'Slate',
        primary:    '#6366f1',
        primaryEnd: '#312e81',
        primaryRgb: '99, 102, 241',
        accent:     '#6366f1',
        sidebarBg:  '#eef2ff',
    },
];

/**
 * Apply a theme by key. Updates CSS custom properties on :root and saves to
 * localStorage.
 *
 * @param {string} key - Theme key (e.g. 'ocean')
 */
function applyTheme(key) {
    const theme = THEMES.find(t => t.key === key) || THEMES[0];
    const root = document.documentElement;

    root.setAttribute('data-theme', theme.key);
    root.style.setProperty('--color-primary',     theme.primary);
    root.style.setProperty('--color-primary-end', theme.primaryEnd);
    root.style.setProperty('--color-primary-rgb', theme.primaryRgb);
    root.style.setProperty('--color-accent',      theme.accent);
    root.style.setProperty('--sidebar-active-bg', theme.sidebarBg);

    // Keep Bootstrap's own variables in sync so bg-primary, text-primary etc. match
    root.style.setProperty('--bs-primary',     theme.primary);
    root.style.setProperty('--bs-primary-rgb', theme.primaryRgb);
    root.style.setProperty('--bs-link-color',  theme.primary);

    try { localStorage.setItem('lc-theme', theme.key); } catch (_) { /* private browsing */ }

    // Update active state on swatches if they are rendered
    document.querySelectorAll('.theme-swatch').forEach(el => {
        el.classList.toggle('active', el.dataset.themeKey === theme.key);
    });
}

/**
 * Render theme swatches into the element with the given id.
 *
 * @param {string} containerId - ID of the container element
 */
function renderSwatches(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const saved = (() => { try { return localStorage.getItem('lc-theme'); } catch (_) { return null; } })();
    const activeKey = saved || 'default';

    container.innerHTML = THEMES.map(theme => `
        <div class="theme-swatch-wrap" title="${theme.label}" onclick="applyTheme('${theme.key}')">
            <div class="theme-swatch ${theme.key === activeKey ? 'active' : ''}"
                 data-theme-key="${theme.key}"
                 style="background: linear-gradient(135deg, ${theme.primary} 0%, ${theme.primaryEnd} 100%);"></div>
            <span>${theme.label}</span>
        </div>
    `).join('');
}

// ── Bootstrap ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Restore saved theme (FOUC prevention already applied it via inline script
    // in base.html, but we still need to set the CSS variables at runtime)
    const saved = (() => { try { return localStorage.getItem('lc-theme'); } catch (_) { return null; } })();
    applyTheme(saved || 'default');

    // Render swatches on the Appearance tab (only present on /settings)
    renderSwatches('theme-swatches');
});
