/**
 * Documentation viewer — lists the repo-docs catalogue and renders the
 * selected doc's HTML, fetched live from /api/repo-docs.
 */

const navEl = document.getElementById('docs-nav');
const contentEl = document.getElementById('docs-content');

function renderNav(docs) {
    navEl.innerHTML = '';
    docs.forEach(function (doc) {
        const item = document.createElement('a');
        item.href = '#' + doc.slug;
        item.className = 'list-group-item list-group-item-action';
        item.textContent = doc.title;
        item.dataset.slug = doc.slug;
        item.addEventListener('click', function (event) {
            event.preventDefault();
            selectDoc(doc.slug);
        });
        navEl.appendChild(item);
    });
}

function markActive(slug) {
    navEl.querySelectorAll('.list-group-item').forEach(function (el) {
        el.classList.toggle('active', el.dataset.slug === slug);
    });
}

async function selectDoc(slug) {
    markActive(slug);
    history.replaceState(null, '', '#' + slug);
    contentEl.innerHTML = '<p class="text-muted">Loading&hellip;</p>';
    try {
        const response = await fetch('/api/repo-docs/' + encodeURIComponent(slug));
        if (!response.ok) {
            contentEl.innerHTML = '<p class="text-danger">Document not found.</p>';
            return;
        }
        const data = await response.json();
        contentEl.innerHTML = data.html;
    } catch (error) {
        console.error('Failed to load doc:', error);
        contentEl.innerHTML = '<p class="text-danger">Failed to load document.</p>';
    }
}

async function init() {
    try {
        const response = await fetch('/api/repo-docs');
        const docs = await response.json();
        renderNav(docs);
        const initialSlug = window.location.hash ? window.location.hash.slice(1) : null;
        if (initialSlug && docs.some(function (d) { return d.slug === initialSlug; })) {
            selectDoc(initialSlug);
        } else if (docs.length > 0) {
            selectDoc(docs[0].slug);
        }
    } catch (error) {
        console.error('Failed to load doc list:', error);
        navEl.innerHTML = '<div class="list-group-item text-danger small">Failed to load documents.</div>';
    }
}

init();
