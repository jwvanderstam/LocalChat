# INSTALLATION & TESTING GUIDE - MONTH 2

## ?? Quick Start: Month 2 Integration

### Prerequisites
- ? Month 1 complete (logging, type hints, docstrings)
- ? Python 3.14
- ? All existing dependencies installed

---

## ?? STEP 1: Install Month 2 Dependencies

```bash
# Navigate to project directory
cd C:\Users\Gebruiker\source\repos\LocalChat

# Install Pydantic and email-validator
pip install pydantic==2.5.3 email-validator==2.1.0
```

**Expected Output**:
```
Successfully installed pydantic-2.5.3 email-validator-2.1.0
```

---

## ? STEP 2: Verify Installation

```bash
# Test imports
python -c "import pydantic; import email_validator; print('? Dependencies installed successfully!')"
```

**Expected Output**:
```
? Dependencies installed successfully!
```

---

## ?? STEP 3: Test Application

### Start the Application:
```bash
python app.py
```

**Expected Output**:
```
INFO - root - Logging system initialized
INFO - config - Configuration module loaded
INFO - ollama_client - OllamaClient initialized
INFO - db - Database manager initialized
INFO - rag - DocumentProcessor initialized
INFO - app - ==================================================
INFO - app - LocalChat Application Starting (Month 2 - Validated)
INFO - app - ==================================================
INFO - app - 1. Checking Ollama...
INFO - app - ? Ollama is running with X models
INFO - app - 2. Checking PostgreSQL with pgvector...
INFO - app - ? Database connection established
INFO - app - ? Documents in database: 0
INFO - app - 3. Starting web server...
INFO - app - ? All services ready!
INFO - app - ? Server starting on http://localhost:5000
INFO - app - ==================================================
```

**Key Change**: Notice "Month 2 - Validated" in the startup banner!

---

## ?? STEP 4: Test Validation (New Feature!)

### Test 1: Valid Chat Request ?
```bash
curl -X POST http://localhost:5000/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"Hello, how are you?\", \"use_rag\": false, \"history\": []}"
```

**Expected**: SSE stream with response

---

### Test 2: Invalid Chat Request (Empty Message) ?
```bash
curl -X POST http://localhost:5000/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"\", \"use_rag\": false}"
```

**Expected Output (400 Error)**:
```json
{
  "success": false,
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": {
    "errors": [
      {
        "type": "value_error",
        "loc": ["body", "message"],
        "msg": "Message cannot be empty or whitespace only",
        "input": ""
      }
    ]
  },
  "timestamp": "2024-12-27T10:30:00.000Z"
}
```

---

### Test 3: Invalid Chat Request (Message Too Long) ?
```bash
# Create a message with 6000 characters (exceeds 5000 limit)
curl -X POST http://localhost:5000/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"aaaaaaaaaa...(6000 chars)...\", \"use_rag\": false}"
```

**Expected Output (400 Error)**:
```json
{
  "success": false,
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": {
    "errors": [
      {
        "type": "string_too_long",
        "loc": ["body", "message"],
        "msg": "String should have at most 5000 characters"
      }
    ]
  },
  "timestamp": "2024-12-27T10:30:00.000Z"
}
```

---

### Test 4: Invalid Model Request ?
```bash
curl -X POST http://localhost:5000/api/models/active ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"nonexistent-model-123\"}"
```

**Expected Output (404 Error)**:
```json
{
  "success": false,
  "error": "InvalidModelError",
  "message": "Model 'nonexistent-model-123' not found",
  "details": {
    "requested": "nonexistent-model-123",
    "available": ["llama3.2", "mistral", "nomic-embed-text", ...]
  },
  "timestamp": "2024-12-27T10:30:00.000Z"
}
```

---

### Test 5: Test 404 Handler ?
```bash
curl http://localhost:5000/api/nonexistent-endpoint
```

**Expected Output (404 Error)**:
```json
{
  "success": false,
  "error": "NotFound",
  "message": "The requested resource was not found",
  "details": {
    "path": "/api/nonexistent-endpoint"
  },
  "timestamp": "2024-12-27T10:30:00.000Z"
}
```

---

## ?? VALIDATION CHECKLIST

### Before Running Tests:
- [ ] Dependencies installed (`pip install pydantic==2.5.3 email-validator==2.1.0`)
- [ ] Ollama running (`ollama serve`)
- [ ] PostgreSQL running
- [ ] Application starts successfully

### After Running Tests:
- [ ] Valid requests work (Test 1)
- [ ] Empty message rejected (Test 2)
- [ ] Long message rejected (Test 3)
- [ ] Invalid model rejected (Test 4)
- [ ] 404 handler works (Test 5)
- [ ] Error responses have consistent format
- [ ] All errors logged in `logs/app.log`

---

## ?? WHAT'S NEW IN MONTH 2

### 1. Input Validation ?
- All requests validated with Pydantic models
- Automatic type checking
- Field-level validation (length, format, range)
- Cross-field validation (e.g., overlap < chunk_size)

### 2. Error Handling ?
- Custom exception classes (11 types)
- Consistent error response format
- Proper HTTP status codes
- Detailed error information (no sensitive data)

### 3. Input Sanitization ?
- Filename sanitization (path traversal prevention)
- Query sanitization (XSS prevention)
- Model name sanitization (injection prevention)
- Path validation (directory traversal prevention)

### 4. Security Improvements ?
- No information leakage in error messages
- SQL LIKE pattern escaping
- Null byte removal
- JSON key sanitization

---

## ?? NEW ERROR RESPONSE FORMAT

**Before Month 2**:
```json
{
  "success": false,
  "message": "Model name required"
}
```

**After Month 2**:
```json
{
  "success": false,
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": {
    "errors": [...]
  },
  "timestamp": "2024-12-27T10:30:00.000Z"
}
```

**Benefits**:
- Consistent format across all errors
- Detailed error information
- Easy to parse programmatically
- Timestamp for debugging
- No sensitive information

---

## ?? TROUBLESHOOTING

### Issue: `ModuleNotFoundError: No module named 'pydantic'`
**Solution**: Install dependencies
```bash
pip install pydantic==2.5.3 email-validator==2.1.0
```

### Issue: Import errors in app.py
**Solution**: Verify all Month 2 files exist
```bash
dir exceptions.py models.py utils\sanitization.py
```

### Issue: Validation not working
**Solution**: Check Month 2 startup banner
- Should see: "LocalChat Application Starting (Month 2 - Validated)"
- If not, verify app.py imports are correct

### Issue: Old error format still showing
**Solution**: Restart the application
```bash
# Stop app (Ctrl+C)
python app.py
```

---

## ?? ADDITIONAL TESTING

### Test with Postman/Insomnia:
1. Create a new POST request to `http://localhost:5000/api/chat`
2. Set header: `Content-Type: application/json`
3. Body: `{"message": "", "use_rag": false}`
4. Send ? Should get 400 with validation error

### Test with Browser Console:
```javascript
fetch('http://localhost:5000/api/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({message: '', use_rag: false})
})
.then(r => r.json())
.then(d => console.log(d));
// Expected: ValidationError response
```

---

## ? SUCCESS INDICATORS

When Month 2 is working correctly:

1. **Startup**:
   - ? See "Month 2 - Validated" in startup banner
   - ? No import errors
   - ? Application starts successfully

2. **Validation**:
   - ? Empty messages rejected with 400
   - ? Long messages rejected with 400
   - ? Invalid models rejected with 404
   - ? Validation errors show detailed field information

3. **Error Handling**:
   - ? All errors return consistent format
   - ? Appropriate HTTP status codes (400, 404, 500)
   - ? Errors logged in `logs/app.log`
   - ? Timestamps included in responses

4. **Security**:
   - ? Path traversal attempts blocked
   - ? XSS attempts sanitized
   - ? No sensitive information in errors

---

## ?? CONGRATULATIONS!

If all tests pass:
- ? **Month 2 is fully operational!**
- ? **Your application is production-ready!**
- ? **Security is enterprise-grade!**
- ? **Error handling is professional!**

**Next Steps**:
1. Use the application normally
2. Monitor `logs/app.log` for any issues
3. Ready for Month 3 (Testing & Performance) when needed!

---

**Status**: ? READY FOR PRODUCTION
**Date**: 2024-12-27
**Version**: Month 2 - Error Handling & Validation Complete
