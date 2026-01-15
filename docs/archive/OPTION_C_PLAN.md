# Option C: Sprint to 80% - Execution Plan

**Start Date:** January 2025  
**Current Coverage:** 58-62%  
**Target Coverage:** 80%  
**Gap to Close:** ~20%  
**Estimated Duration:** 10-15 hours

---

## Phase Breakdown

### Phase 1: High-Impact Modules (6-8 hours, +12%)

#### 1.1 Complete RAG Module (2 hours, +4%)
- **Current:** 31%
- **Target:** 70%
- **Tests Needed:** ~40
- **Priority:** HIGH (large module, core functionality)

**Focus Areas:**
- Document loaders (PDF, DOCX)
- BM25 scoring implementation
- Hybrid search logic
- Context retrieval
- Chunk management
- Embedding generation

#### 1.2 Security Module (1.5 hours, +2%)
- **Current:** 0%
- **Target:** 70%
- **Tests Needed:** ~25
- **Priority:** HIGH (completely uncovered)

**Focus Areas:**
- JWT authentication
- Rate limiting
- CORS configuration
- Auth routes
- Security middleware

#### 1.3 App Routes (2 hours, +3%)
- **Current:** 0%
- **Target:** 50%
- **Tests Needed:** ~30
- **Priority:** HIGH (main application)

**Focus Areas:**
- Chat endpoints
- SSE streaming
- Document upload
- Model management

#### 1.4 Cache Backends (1 hour, +1%)
- **Current:** 0%
- **Target:** 60%
- **Tests Needed:** ~20
- **Priority:** MEDIUM

**Focus Areas:**
- Database cache implementation
- Redis backend (if testable)
- Cache operations

#### 1.5 Complete Routes (1.5 hours, +2%)
- **Current:** document_routes 17%, model_routes 12%
- **Target:** 70%+
- **Tests Needed:** ~25
- **Priority:** HIGH

**Focus Areas:**
- Document CRUD operations
- Model operations
- Error handling in routes

---

### Phase 2: Polish Existing (3-4 hours, +5%)

#### 2.1 DB Module (1 hour, +2%)
- **Current:** 74%
- **Target:** 90%
- **Tests Needed:** ~15
- **Priority:** MEDIUM

**Focus Areas:**
- Connection pooling
- Advanced queries
- Error handling
- Cleanup operations

#### 2.2 Monitoring (30 min, +0.5%)
- **Current:** 82%
- **Target:** 95%
- **Tests Needed:** ~8
- **Priority:** LOW

**Focus Areas:**
- Health checks with app context
- Request timing middleware
- Metrics endpoints

#### 2.3 Error Handlers (30 min, +0.5%)
- **Current:** 40%
- **Target:** 70%
- **Tests Needed:** ~10
- **Priority:** MEDIUM

**Focus Areas:**
- All error types (500, 422, etc.)
- Error response formats
- Logging integration

#### 2.4 App Factory (1 hour, +1%)
- **Current:** 88%
- **Target:** 95%
- **Tests Needed:** ~10
- **Priority:** LOW

**Focus Areas:**
- Configuration edge cases
- Service initialization
- Cleanup handlers

#### 2.5 Smaller Modules (1 hour, +1%)
- Bring 70-89% modules to 90%+
- api_docs, batch_processor, sanitization
- ~15 tests total

---

### Phase 3: Edge Cases & Integration (2-3 hours, +3%)

#### 3.1 Integration Testing (1.5 hours, +2%)
- Fix remaining 3 failing integration tests
- Add missing route tests
- Document upload/download flows

#### 3.2 Edge Cases (1 hour, +1%)
- Error paths
- Boundary conditions
- Unicode/encoding
- Performance scenarios

#### 3.3 Final Polish (30 min, +0%)
- Fix any failing tests
- Improve weak assertions
- Documentation updates

---

## Execution Strategy

### Day 1 (6-8 hours): Core Coverage Push
1. ? Morning: RAG complete (2h) ? +4%
2. ? Midday: Security module (1.5h) ? +2%
3. ? Afternoon: App routes (2h) ? +3%
4. ? Evening: Cache backends (1h) ? +1%

**Day 1 Target:** 68-70%

### Day 2 (4-6 hours): Polish & Integration
1. ? Morning: Complete routes (1.5h) ? +2%
2. ? Midday: DB polish (1h) ? +2%
3. ? Afternoon: Smaller modules (1.5h) ? +2%
4. ? Evening: Integration tests (1h) ? +2%

**Day 2 Target:** 78-82%

---

## Success Metrics

- [ ] Total coverage ? 80%
- [ ] All modules > 50%
- [ ] Critical modules > 80%
- [ ] Pass rate ? 95%
- [ ] No regressions
- [ ] All committed to Git
- [ ] HTML coverage report generated

---

## Risk Mitigation

### Known Challenges
1. **Security module** - Needs Flask app context
   - Solution: Use test fixtures with app
   
2. **App.py routes** - Complex SSE streaming
   - Solution: Mock streaming, test structure
   
3. **Integration tests** - Slow execution
   - Solution: Run in batches, optimize
   
4. **Time constraints** - 10-15 hours is significant
   - Solution: Focus on high-value, skip diminishing returns

### Contingencies
- If stuck on module > 30min, move on
- Document blockers for later
- Prioritize breadth over depth
- 75% is acceptable compromise

---

## Tools & Commands

### Quick Coverage Check
```bash
pytest tests/unit/test_MODULE.py --cov=src.MODULE --cov-report=term
```

### Full Coverage Report
```bash
pytest tests/unit/ tests/integration/ --cov=src --cov-report=html
```

### Module-Specific Run
```bash
pytest tests/unit/test_MODULE.py -v --tb=short
```

---

## Tracking Progress

| Phase | Module | Start | Current | Target | Status |
|-------|--------|-------|---------|--------|--------|
| 1.1 | RAG | 31% | - | 70% | ?? NEXT |
| 1.2 | Security | 0% | - | 70% | ? |
| 1.3 | App Routes | 0% | - | 50% | ? |
| 1.4 | Cache Backends | 0% | - | 60% | ? |
| 1.5 | Routes | 17% | - | 70% | ? |
| 2.1 | DB | 74% | - | 90% | ? |
| 2.2 | Monitoring | 82% | - | 95% | ? |
| 2.3 | Error Handlers | 40% | - | 70% | ? |
| 2.4 | App Factory | 88% | - | 95% | ? |
| 3.1 | Integration | - | - | - | ? |

---

## Commit Strategy

- Commit after each module completion
- Group small changes together
- Clear, descriptive messages
- Push regularly to backup work

---

**Status:** ?? READY TO START  
**Next Action:** Begin Phase 1.1 - RAG Module  
**Expected Completion:** 10-15 hours from start

*Plan created: January 2025*  
*Target: 80% coverage*  
*Current: 58-62%*
