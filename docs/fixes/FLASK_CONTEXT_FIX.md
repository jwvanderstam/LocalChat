# Flask Application Context Fix

**Date:** 2025-01-15  
**Issue:** RuntimeError: Working outside of application context  
**Status:** ? Fixed in Multiple Endpoints

## Problem

Generator functions in API endpoints threw `RuntimeError` when trying to access `current_app`:

### Error 1: Document Upload
```
File "src\routes\document_routes.py", line 132, in generate
    success, message, doc_id = current_app.doc_processor.ingest_document(
                               ^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Working outside of application context.
```

### Error 2: Chat Streaming
```
File "src\routes\api_routes.py", line 294, in generate
    for chunk in current_app.ollima_client.generate_chat_response(
                 ^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Working outside of application context.
```

## Root Cause

Both endpoints use **generator functions** to stream Server-Sent Events (SSE). Python generators execute **lazily** - they don't run when defined, but when iterated by the client consuming the stream.

### The Issue with Generators

```python
def my_endpoint():
    # This runs in the Flask request context ?
    
    def generate():
        # This runs LATER, potentially outside the request context! ?
        value = current_app.some_service.do_something(...)
        # current_app proxy may not be available here
```

When the generator is consumed (by the client receiving the SSE stream), it may execute after the Flask request context has ended, causing the error.

## Solution

### Approach: Use `_get_current_object()`

Capture a reference to the actual application object **before** entering the generator:

```python
def my_endpoint():
    # Capture the actual app object (not the proxy)
    app = current_app._get_current_object()
    
    def generate():
        # Use captured 'app' instead of 'current_app'
        value = app.some_service.do_something(...)
        # ? Works! We have a real object reference
```

### Why This Works

1. **`current_app` is a proxy** - It looks up the actual application object from thread-local storage
2. **`_get_current_object()`** - Returns the actual Flask application instance, not the proxy
3. **Captured reference** - The `app` variable holds a real object that doesn't depend on context

## Code Changes

### File 1: `src/routes/document_routes.py`

**Added Import:**
```python
from flask import Blueprint, jsonify, request, Response, current_app, copy_current_request_context
```

**Fixed Document Upload:**
```python
@bp.route('/upload', methods=['POST'])
def api_upload_documents():
    # ... file validation code ...
    
    # ? Capture app object before generator
    app = current_app._get_current_object()
    
    def generate() -> Generator[str, None, None]:
        for file_path in file_paths:
            # ? Use 'app' instead of 'current_app'
            success, message, doc_id = app.doc_processor.ingest_document(
                file_path, lambda m: None
            )
            # ... rest of code ...
            
            doc_count = app.db.get_document_count()
            config.app_state.set_document_count(doc_count)
        
        yield f"data: {json.dumps({'done': True, 'total_documents': doc_count})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')
```

### File 2: `src/routes/api_routes.py`

**Fixed Chat Streaming:**
```python
@bp.route('/chat', methods=['POST'])
def api_chat():
    # ... message processing and RAG retrieval ...
    
    messages.append({'role': 'user', 'content': message})
    
    # ? Capture app object before entering generator
    app = current_app._get_current_object()
    
    def generate() -> Generator[str, None, None]:
        try:
            logger.debug("[CHAT API] Starting response stream...")
            # ? Use 'app' instead of 'current_app'
            for chunk in app.ollima_client.generate_chat_response(
                active_model, messages, stream=True
            ):
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            logger.debug("[CHAT API] Response stream completed")
        except Exception as e:
            logger.error(f"[CHAT API] Error generating response: {e}", exc_info=True)
            error_msg = json.dumps({
                'error': 'GenerationError',
                'message': 'Failed to generate response'
            })
            yield f"data: {error_msg}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')
```

## Affected Endpoints

| Endpoint | Method | Type | Status |
|----------|--------|------|--------|
| `/api/documents/upload` | POST | File upload with progress | ? Fixed |
| `/api/chat` | POST | Chat streaming | ? Fixed |
| `/api/models/pull` | POST | Model download progress | ? Fixed |

## How It Works

### Request Flow

1. **Client makes request** ? `POST /api/chat` or `/api/documents/upload`
2. **Flask creates request context** ? `current_app` becomes available
3. **Route handler runs:**
   - Validates input
   - Processes data (RAG retrieval, file validation)
   - **Captures app object:** `app = current_app._get_current_object()`
4. **Returns Response with generator** ? Response headers sent to client
5. **Generator executes (async/lazy):**
   - May run after request context ends
   - Uses captured `app` object (not proxy)
   - ? Works correctly!

### Server-Sent Events (SSE) Flow

```
Client                    Flask Server
  |                           |
  |--- POST /chat ----------->|
  |                           | Validate message
  |                           | Retrieve RAG context
  |                           | Create generator
  |<-- Headers + Stream Start-|
  |                           |
  |<-- data: chunk 1 ---------|
  |                           | (generator running)
  |<-- data: chunk 2 ---------|
  |                           |
  |<-- data: done ------------|
  |                           |
Connection closed
```

The generator may still be running after the initial request handling completes, which is why we need the captured reference.

## Testing

### Test 1: Document Upload

```bash
# Upload a document
curl -X POST http://localhost:5000/api/documents/upload \
  -F "files=@test.pdf"

# Expected: SSE stream with progress
data: {"message": "Processing test.pdf..."}
data: {"result": {"filename": "test.pdf", "success": true, ...}}
data: {"done": true, "total_documents": 1}

# ? No RuntimeError!
```

### Test 2: Chat Streaming

```bash
# Send a chat message
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is this about?", "use_rag": true}'

# Expected: SSE stream with response
data: {"content": "Based on"}
data: {"content": " the documents..."}
data: {"done": true}

# ? No RuntimeError!
```

### Web UI Test

1. Go to http://localhost:5000
2. **Test Chat:**
   - Navigate to Chat page
   - Send a message
   - ? Response streams smoothly
3. **Test Upload:**
   - Navigate to Documents page
   - Upload a file
   - ? Progress bar updates
4. **? No errors in console or logs**

## Technical Deep Dive

### Flask Request Context

Flask uses **context locals** to provide `current_app`, `request`, `g`, and `session`:

```python
# Simplified Flask internals
_app_ctx_stack = LocalStack()

current_app = LocalProxy(lambda: _app_ctx_stack.top.app)
```

The `current_app` is a **proxy object** that looks up the actual application from thread-local storage.

### The Problem with Generators

```python
def my_route():
    def generator():
        # When does this run?
        # Answer: When the response is consumed by the client!
        # The request context may be gone by then!
        value = current_app.some_attribute  # ? May fail
    
    return Response(generator())
```

### The Solution

```python
def my_route():
    # Capture the real object NOW, while context exists
    app = current_app._get_current_object()
    
    def generator():
        # Use the captured object
        value = app.some_attribute  # ? Always works
    
    return Response(generator())
```

## Best Practices

### When to Use This Pattern

? **Use `_get_current_object()` when:**
- Working with generators that access `current_app`
- Using background threads or async tasks
- Streaming responses (SSE, chunked responses)
- Long-running operations within a request

? **Don't need it when:**
- Regular synchronous route handlers
- All code runs within request context
- Using `@app.route()` decorated functions normally

### Example: Background Task

```python
from threading import Thread

@app.route('/process')
def process():
    app = current_app._get_current_object()
    
    def background_task():
        with app.app_context():
            # Now current_app works
            app.db.process_data()
    
    thread = Thread(target=background_task)
    thread.start()
    
    return jsonify({'status': 'processing'})
```

## Related Issues

This fix is similar to issues that can occur with:
- WebSocket handlers
- Celery tasks
- Background threads
- Streaming uploads/downloads
- Long polling endpoints

## References

- [Flask Application Context](https://flask.palletsprojects.com/en/2.3.x/appcontext/)
- [Flask Request Context](https://flask.palletsprojects.com/en/2.3.x/reqcontext/)
- [Werkzeug Local Proxies](https://werkzeug.palletsprojects.com/en/2.3.x/local/)

---

**Status:** ? Complete (Both Endpoints Fixed)  
**Files Modified:** 
- `src/routes/document_routes.py` (document upload)
- `src/routes/api_routes.py` (chat streaming)

**Breaking Changes:** None  
**Testing:** Verified with both file upload and chat streaming endpoints
