/**
 * Document ingestion and management functionality
 */

// DOM elements
const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn');
const uploadProgress = document.getElementById('upload-progress');
const progressBar = document.getElementById('progress-bar');
const progressMessage = document.getElementById('progress-message');
const uploadResults = document.getElementById('upload-results');
const testForm = document.getElementById('test-form');
const testQuery = document.getElementById('test-query');
const testBtn = document.getElementById('test-btn');
const testResults = document.getElementById('test-results');
const documentsList = document.getElementById('documents-list');

// Initialize
function init() {
    // Upload form
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await uploadDocuments();
    });
    
    // Test form
    testForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await testRetrieval();
    });
    
    // Load documents on page load
    loadDocuments();
    loadStats();
}

// Upload documents
async function uploadDocuments() {
    const files = fileInput.files;
    
    if (!files || files.length === 0) {
        alert('Please select files to upload');
        return;
    }
    
    // Prepare form data
    const formData = new FormData();
    for (let file of files) {
        formData.append('files', file);
    }
    
    // Show progress
    uploadProgress.style.display = 'block';
    uploadResults.innerHTML = '';
    uploadBtn.disabled = true;
    progressBar.style.width = '10%';
    progressMessage.textContent = 'Starting upload...';
    
    try {
        const response = await fetch('/api/documents/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Upload failed');
        }
        
        // Read streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const results = [];
        let processedFiles = 0;
        const totalFiles = files.length;
        
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value);
            const lines = text.split('\n').filter(line => line.startsWith('data: '));
            
            for (const line of lines) {
                const data = JSON.parse(line.substring(6));
                
                if (data.message) {
                    progressMessage.textContent = data.message;
                }
                
                if (data.result) {
                    results.push(data.result);
                    processedFiles++;
                    const percent = (processedFiles / totalFiles) * 90; // Reserve 10% for final steps
                    progressBar.style.width = percent + '%';
                }
                
                if (data.done) {
                    progressBar.style.width = '100%';
                    progressMessage.textContent = `Completed! Total documents: ${data.total_documents}`;
                }
            }
        }
        
        // Display results
        displayUploadResults(results);
        
        // Reload documents list
        setTimeout(() => {
            loadDocuments();
            loadStats();
            fileInput.value = ''; // Clear file input
        }, 1000);
        
    } catch (error) {
        progressMessage.textContent = 'Error: ' + error.message;
        uploadResults.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
    } finally {
        uploadBtn.disabled = false;
    }
}

// Display upload results
function displayUploadResults(results) {
    if (!results || results.length === 0) return;
    
    let html = '<div class="mt-3">';
    
    results.forEach(result => {
        const alertClass = result.success ? 'alert-success' : 'alert-danger';
        const icon = result.success ? 'check-circle' : 'x-circle';
        
        html += `
            <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
                <i class="bi bi-${icon} me-2"></i>
                <strong>${result.filename}:</strong> ${result.message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
    });
    
    html += '</div>';
    uploadResults.innerHTML = html;
}

// Test retrieval
async function testRetrieval() {
    const query = testQuery.value.trim();
    
    if (!query) {
        alert('Please enter a test query');
        return;
    }
    
    testBtn.disabled = true;
    testResults.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm"></div> Testing...</div>';
    
    try {
        const response = await fetch('/api/documents/test', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({query: query})
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Check both hybrid and semantic_only results
            const hybridResults = data.results?.hybrid?.chunks || [];
            const semanticResults = data.results?.semantic_only?.chunks || [];
            
            if (hybridResults.length > 0 || semanticResults.length > 0) {
                let html = '<div class="mt-3">';
                
                // Display Hybrid Results
                if (hybridResults.length > 0) {
                    html += '<h6>Hybrid Search Results (Semantic + BM25):</h6>';
                    hybridResults.forEach((result, idx) => {
                        html += `
                            <div class="card mb-2">
                                <div class="card-body">
                                    <h6 class="card-subtitle mb-2 text-muted">
                                        ${result.filename} - Chunk ${result.chunk_index}
                                        <span class="badge bg-info float-end">Similarity: ${(result.similarity * 100).toFixed(1)}%</span>
                                    </h6>
                                    <p class="card-text small">${result.preview}</p>
                                </div>
                            </div>
                        `;
                    });
                }
                
                // Display Semantic Only Results
                if (semanticResults.length > 0) {
                    html += '<h6 class="mt-3">Semantic Only Results:</h6>';
                    semanticResults.forEach((result, idx) => {
                        html += `
                            <div class="card mb-2">
                                <div class="card-body">
                                    <h6 class="card-subtitle mb-2 text-muted">
                                        ${result.filename} - Chunk ${result.chunk_index}
                                        <span class="badge bg-secondary float-end">Similarity: ${(result.similarity * 100).toFixed(1)}%</span>
                                    </h6>
                                    <p class="card-text small">${result.preview}</p>
                                </div>
                            </div>
                        `;
                    });
                }
                
                // Add diagnostic info
                if (data.diagnostic) {
                    html += `
                        <div class="alert alert-info mt-3">
                            <strong>Diagnostic Info:</strong><br>
                            ${data.diagnostic.recommendation}
                        </div>
                    `;
                }
                
                html += '</div>';
                testResults.innerHTML = html;
            } else {
                testResults.innerHTML = '<div class="alert alert-warning mt-3">No results found. Make sure documents are ingested.</div>';
            }
        } else {
            testResults.innerHTML = `<div class="alert alert-danger mt-3">Error: ${data.message || 'Unknown error'}</div>`;
        }
    } catch (error) {
        testResults.innerHTML = `<div class="alert alert-danger mt-3">Error: ${error.message}</div>`;
    } finally {
        testBtn.disabled = false;
    }
}

// Load documents list
async function loadDocuments() {
    documentsList.innerHTML = '<div class="text-center text-muted"><div class="spinner-border spinner-border-sm me-2"></div> Loading...</div>';
    
    try {
        const response = await fetch('/api/documents/list');
        const data = await response.json();
        
        if (data.success && data.documents && data.documents.length > 0) {
            let html = '<div class="list-group">';
            
            data.documents.forEach(doc => {
                const date = new Date(doc.created_at).toLocaleDateString();
                const chunkCount = doc.chunk_count || 0;
                
                html += `
                    <div class="list-group-item">
                        <div class="d-flex w-100 justify-content-between">
                            <h6 class="mb-1">
                                <i class="bi bi-file-text me-2"></i>${doc.filename}
                            </h6>
                            <small class="text-muted">${date}</small>
                        </div>
                        <p class="mb-1 text-muted small">
                            <span class="badge bg-secondary">${chunkCount} chunks</span>
                        </p>
                    </div>
                `;
            });
            
            html += '</div>';
            documentsList.innerHTML = html;
        } else {
            documentsList.innerHTML = '<div class="alert alert-info">No documents uploaded yet.</div>';
        }
    } catch (error) {
        documentsList.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
    }
}

// Load statistics
async function loadStats() {
    try {
        const response = await fetch('/api/documents/stats');
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('stat-docs').textContent = data.document_count || 0;
            document.getElementById('stat-chunks').textContent = data.chunk_count || 0;
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Clear database
async function clearDatabase() {
    // Confirm action
    if (!confirm('?? WARNING: This will permanently delete ALL documents and chunks from the database.\n\nThis action CANNOT be undone!\n\nAre you sure you want to continue?')) {
        return;
    }
    
    // Double confirmation
    if (!confirm('This is your LAST chance to cancel.\n\nClick OK to DELETE ALL DOCUMENTS permanently.')) {
        return;
    }
    
    const clearBtn = document.getElementById('clear-db-btn');
    clearBtn.disabled = true;
    clearBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Clearing...';
    
    try {
        const response = await fetch('/api/documents/clear', {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Show success message
            alert('? Database cleared successfully!\n\nAll documents and chunks have been deleted.');
            
            // Reload documents and stats
            loadDocuments();
            loadStats();
            
            // Clear upload results
            uploadResults.innerHTML = '';
            testResults.innerHTML = '';
        } else {
            alert('Error: ' + data.message);
        }
    } catch (error) {
        alert('Error clearing database: ' + error.message);
    } finally {
        clearBtn.disabled = false;
        clearBtn.innerHTML = '<i class="bi bi-trash me-2"></i>Clear Database';
    }
}

// Initialize on page load
init();
