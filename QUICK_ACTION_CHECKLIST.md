# Quick Action Checklist - Week 1 Improvements

**Goal:** Address critical technical debt  
**Timeline:** 5 days  
**Focus:** High-impact, low-risk changes

---

## Day 1-2: Remove Hybrid Compatibility Mode ?

### Task: Eliminate MONTH2_ENABLED Pattern

#### Step 1: Audit Codebase
```bash
# Find all occurrences
grep -r "MONTH2_ENABLED" src/
grep -r "if MONTH2" src/
```

**Expected Locations:**
- [ ] `src/routes/error_handlers.py`
- [ ] `src/routes/api_routes.py`
- [ ] `src/routes/document_routes.py`
- [ ] `src/config.py` (definition)

#### Step 2: Update config.py
```python
# OLD
MONTH2_ENABLED = True

# NEW - Just remove this variable entirely
# Or set as constant if needed elsewhere
VALIDATION_MODE = 'pydantic'  # Always use Pydantic
```

#### Step 3: Clean Up error_handlers.py
```python
# BEFORE (lines ~35-41)
try:
    from .. import exceptions
    from ..models import ErrorResponse
    month2_enabled = True
    logger.info("? Month 2 error handlers enabled")
except ImportError:
    month2_enabled = False
    logger.info("??  Using basic error handlers (Month 1 mode)")

# AFTER
from .. import exceptions
from ..models import ErrorResponse
logger.info("? Error handlers initialized")
```

#### Step 4: Simplify Error Handlers
```python
# BEFORE
if month2_enabled:
    error_response = ErrorResponse(...)
    return jsonify(error_response.model_dump()), 400
else:
    return jsonify({'error': 'BadRequest', ...}), 400

# AFTER
error_response = ErrorResponse(...)
return jsonify(error_response.model_dump()), 400
```

#### Step 5: Update All Routes
- [ ] Remove `if MONTH2_ENABLED` checks
- [ ] Keep only Pydantic validation path
- [ ] Remove basic validation paths

#### Step 6: Test
```bash
pytest tests/ -v --tb=short
# Should all pass with single mode
```

**Expected Results:**
- ? -150-200 lines of code
- ? Simpler control flow
- ? Easier to understand
- ? All tests still passing

---

## Day 3: Fix Failing Tests ??

### Task: Achieve 99%+ Pass Rate

#### Step 1: Identify Failures
```bash
pytest tests/ -v --tb=short 2>&1 | grep "FAILED" | tee test_failures.txt
```

#### Step 2: Categorize Each Failure

**Template:**
```
Test: tests/integration/test_document_routes.py::test_upload
Reason: Database not available
Category: Environment dependency
Fix: Add @pytest.mark.skipif or mock DB
```

#### Step 3: Apply Fixes

**For Environment Dependencies:**
```python
@pytest.mark.skipif(not db.is_available(), reason="DB required")
def test_requires_database():
    pass
```

**For Flaky Tests:**
```python
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=1)
def test_sometimes_fails():
    # This test occasionally fails due to timing
    pass
```

**For Real Bugs:**
- Create GitHub issue
- Add `@pytest.mark.xfail(reason="Bug #123")`
- Fix in separate PR

#### Step 4: Verify
```bash
pytest tests/ -v --tb=short
# Target: 99%+ pass rate
```

**Expected Results:**
- ? 595+/600 tests passing
- ? Known failures documented
- ? No surprises in CI/CD

---

## Day 4-5: Standardize Error Handling ??

### Task: Consistent Error Responses

#### Step 1: Create Error Handler Template
```python
# src/routes/error_handlers.py

def create_error_response(
    error_type: str,
    message: str,
    status_code: int,
    details: Optional[Dict] = None
) -> tuple:
    """Standard error response factory."""
    from ..models import ErrorResponse
    
    error_response = ErrorResponse(
        error=error_type,
        message=message,
        details=details or {}
    )
    return jsonify(error_response.model_dump()), status_code
```

#### Step 2: Refactor All Error Handlers
```python
@app.errorhandler(400)
def bad_request_handler(error):
    return create_error_response(
        error_type="BadRequest",
        message="The request was invalid",
        status_code=400,
        details={'description': str(error)}
    )

@app.errorhandler(404)
def not_found_handler(error):
    return create_error_response(
        error_type="NotFound",
        message="Resource not found",
        status_code=404,
        details={'path': request.path}
    )

# Repeat for: 401, 405, 422, 500
```

#### Step 3: Add Tests
```python
# tests/unit/test_error_handlers.py

def test_error_responses_use_standard_format(client):
    """All errors should use ErrorResponse model."""
    
    # Test 400
    r1 = client.post('/api/chat', data="invalid")
    assert 'error' in r1.json
    assert 'message' in r1.json
    
    # Test 404
    r2 = client.get('/nonexistent')
    assert 'error' in r2.json
    assert r2.json['error'] == 'NotFound'
```

#### Step 4: Update Documentation
- [ ] Document error response format
- [ ] Add examples to API docs
- [ ] Update README

**Expected Results:**
- ? Consistent error format
- ? Easier to consume API
- ? Better error messages
- ? Documented behavior

---

## Verification Checklist

### Before Merge
- [ ] All tests passing (99%+)
- [ ] No `MONTH2_ENABLED` in codebase
- [ ] Error handlers consistent
- [ ] Coverage not decreased
- [ ] Documentation updated

### After Merge
- [ ] CI/CD green
- [ ] No production issues
- [ ] Team notified of changes

---

## Quick Commands

```bash
# Find hybrid mode usage
grep -rn "MONTH2_ENABLED" src/

# Run quick test
pytest tests/unit/ -q

# Check coverage
pytest tests/ --cov=src --cov-report=term:skip-covered

# Find failing tests
pytest tests/ -v | grep FAILED

# Run specific test file
pytest tests/unit/test_error_handlers.py -v
```

---

## Rollback Plan

If anything breaks:

```bash
# Revert last commit
git revert HEAD

# Or reset to before changes
git reset --hard origin/main

# Cherry-pick working changes
git cherry-pick <commit-hash>
```

---

## Success Criteria

### Must Have ?
- [ ] No MONTH2_ENABLED references
- [ ] 99%+ test pass rate
- [ ] All error handlers use ErrorResponse
- [ ] No regressions

### Nice to Have ??
- [ ] Coverage improved (+2%)
- [ ] Code reduced (-200 lines)
- [ ] Documentation complete

---

**Status:** Ready to implement  
**Priority:** High  
**Risk:** Low  
**Time:** 5 days  

*Checklist created: January 2025*
