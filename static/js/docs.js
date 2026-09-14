/**
 * Documentation viewer — lists the repo-docs catalogue and renders the
 * selected doc's HTML, fetched live from /api/repo-docs.
 */

const navEl = document.getElementById('docs-nav');
const contentEl = document.getElementById('docs-content');

if (window.mermaid) {
    window.mermaid.initialize({ startOnLoad: false });
}

async function renderMermaidBlocks() {
    if (!window.mermaid) return;
    const blocks = contentEl.querySelectorAll('pre code.language-mermaid');
    blocks.forEach(function (code) {
        const div = document.createElement('div');
        div.className = 'mermaid';
        div.textContent = code.textContent;
        code.closest('pre').replaceWith(div);
    });
    if (blocks.length > 0) {
        try {
            await window.mermaid.run({ querySelector: '#docs-content .mermaid' });
        } catch (error) {
            console.error('Mermaid render failed:', error);
        }
    }
}

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

let catalogue = [];

function normalisePath(path) {
    const parts = [];
    path.replace(/\\/g, '/').split('/').forEach(function (part) {
        if (part === '..') parts.pop();
        else if (part !== '.' && part !== '') parts.push(part);
    });
    return '/' + parts.join('/');
}

// The docs link each other the way the repository does — `[X](X.md)`, relative to
// the file — and the server renders that href as written. In the viewer it resolves
// to /docs/X.md, which nothing serves, so every cross-document link was a 404.
// The catalogue carries each doc's path, so a relative .md link can be resolved
// against the current doc's directory and pointed at the slug instead.
function rewriteDocLinks(html, currentPath) {
    const base = normalisePath(currentPath).replace(/[^/]*$/, '');
    return html.replace(/href="([^"#:]+\.md)(#[^"]*)?"/g, function (match, file) {
        const target = normalisePath(base + file);
        const doc = catalogue.find(function (d) { return normalisePath(d.path) === target; });
        return doc ? 'href="#' + doc.slug + '"' : match;
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
        const current = catalogue.find(function (d) { return d.slug === slug; });
        contentEl.innerHTML = current ? rewriteDocLinks(data.html, current.path) : data.html;
        await renderMermaidBlocks();
    } catch (error) {
        console.error('Failed to load doc:', error);
        contentEl.innerHTML = '<p class="text-danger">Failed to load document.</p>';
    }
}

// A rewritten link is `#slug`, which only moves the hash; selecting the doc is
// what the nav's own click handler does, so a click inside the content does the same.
contentEl.addEventListener('click', function (event) {
    const link = event.target.closest && event.target.closest('a[href^="#"]');
    if (!link) return;
    const slug = link.getAttribute('href').slice(1);
    if (catalogue.some(function (d) { return d.slug === slug; })) {
        event.preventDefault();
        selectDoc(slug);
    }
});

async function init() {
    try {
        const response = await fetch('/api/repo-docs');
        const docs = await response.json();
        catalogue = docs;
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
