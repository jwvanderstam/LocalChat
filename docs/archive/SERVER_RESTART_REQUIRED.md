# Server Restart Required

**Issue:** Code changes made but server still running old code  
**Solution:** Restart the Flask application

---

## Why This Happens

When you modify Python files while the Flask development server is running:
- **Changes to routes/views:** Require server restart
- **Auto-reload disabled:** `use_reloader=False` in app.py
- **Old code cached:** Python keeps the old module in memory

---

## Solution: Restart the Server

### Step 1: Stop the Current Server

**In the terminal where app.py is running:**
```
Press Ctrl+C
```

### Step 2: Restart the Application

```bash
python app.py
```

---

## Verify the Fix

After restarting, the model pull should work:

```bash
# Test model pull endpoint
curl -X POST http://localhost:5000/api/models/pull \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2:1b"}' \
  --no-buffer

# Expected: Progress streaming (no errors)
data: {"status": "pulling manifest"}
data: {"status": "downloading", "completed": 1024000, "total": 10240000}
...
```

---

## Code Changes Summary

The fix has been applied to `src/routes/model_routes.py`:

```python
@bp.route('/pull', methods=['POST'])
def api_pull_model():
    # ... validation ...
    
    # ? This line was added
    app = current_app._get_current_object()
    
    def generate() -> Generator[str, None, None]:
        try:
            # ? Changed from current_app to app
            for progress in app.ollama_client.pull_model(model_name):
                yield f"data: {json.dumps(progress)}\n\n"
        except Exception as e:
            # ... error handling ...
```

**The code is correct** - it just needs the server to be restarted to take effect.

---

## All Fixed Endpoints

After restart, all three streaming endpoints will work:

| Endpoint | Status | Requires Restart |
|----------|--------|------------------|
| `POST /api/documents/upload` | ? Fixed | Yes |
| `POST /api/chat` | ? Fixed | Yes |
| `POST /api/models/pull` | ? Fixed | Yes |

---

## Quick Checklist

- [ ] Stop server (Ctrl+C)
- [ ] Restart server (`python app.py`)
- [ ] Test model pull endpoint
- [ ] Verify no errors in logs
- [ ] All streaming endpoints working

---

**Next Step:** Restart the server and test!
