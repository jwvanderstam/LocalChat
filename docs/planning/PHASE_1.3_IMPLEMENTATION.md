# Phase 1.3 Implementation: Conversation Memory

## Overview

**Priority:** Medium-High  
**Effort:** 3-4 days  
**Impact:** High  
**Dependencies:** Phase 1.1 recommended (for better citations)

## Goal

Enable multi-turn conversations with context retention.

**Current Limitation:**
- Each query is independent
- No memory of previous exchanges
- Follow-up questions fail: "What about X in that document?"

**After Implementation:**
- Maintains conversation history
- Understands context references
- Tracks mentioned documents
- Natural multi-turn dialogue
- "Tell me more" works naturally

---

## Architecture

### Conversation Flow

```
User: "What are the backup procedures?"
    ?
Assistant: [Answers with sources]
    ?
[Memory stores: query, response, sources]
    ?
User: "What about retention policies?"
    ?
[Memory provides: previous context]
    ?
Assistant: [Answers considering previous topic]
    ?
User: "Tell me more about that"
    ?
[Memory resolves: "that" = retention policies]
    ?
Assistant: [Provides more details]
```

---

## Data Model

### Conversation Session

```python
@dataclass
class ConversationTurn:
    """Single turn in conversation."""
    turn_id: str
    timestamp: datetime
    user_query: str
    assistant_response: str
    sources_used: List[str]  # Filenames referenced
    entities_mentioned: List[str]  # Key topics
    metadata: Dict[str, Any]


@dataclass
class ConversationSession:
    """Complete conversation session."""
    session_id: str
    created_at: datetime
    updated_at: datetime
    turns: List[ConversationTurn]
    document_refs: Set[str]  # All documents referenced
    active_topics: List[str]  # Current discussion topics
    metadata: Dict[str, Any]
```

---

## Implementation

### 1. Conversation Memory Module

**File:** `src/conversation_memory.py` (new file)

```python
"""
Conversation Memory Module
==========================

Maintains conversation context across multiple turns.
"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Any, Optional
from datetime import datetime, timedelta
import uuid
import json
from collections import deque

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationTurn:
    """Single conversation turn."""
    turn_id: str
    timestamp: datetime
    user_query: str
    assistant_response: str
    sources_used: List[str] = field(default_factory=list)
    entities_mentioned: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSession:
    """Conversation session with memory."""
    session_id: str
    created_at: datetime
    updated_at: datetime
    turns: List[ConversationTurn] = field(default_factory=list)
    document_refs: Set[str] = field(default_factory=set)
    active_topics: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_turn(
        self,
        user_query: str,
        assistant_response: str,
        sources: List[str],
        entities: Optional[List[str]] = None
    ):
        """Add a turn to the conversation."""
        turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            user_query=user_query,
            assistant_response=assistant_response,
            sources_used=sources,
            entities_mentioned=entities or []
        )
        
        self.turns.append(turn)
        self.document_refs.update(sources)
        
        if entities:
            self.active_topics = entities  # Update active topics
        
        self.updated_at = datetime.now()
    
    def get_recent_turns(self, n: int = 5) -> List[ConversationTurn]:
        """Get N most recent turns."""
        return self.turns[-n:] if len(self.turns) > n else self.turns
    
    def get_context_summary(self, max_turns: int = 3) -> str:
        """
        Generate context summary for LLM.
        
        Returns formatted string with recent conversation context.
        """
        recent = self.get_recent_turns(max_turns)
        
        if not recent:
            return ""
        
        summary_parts = ["Recent conversation context:"]
        
        for idx, turn in enumerate(recent, 1):
            summary_parts.append(
                f"\nTurn {idx}:\n"
                f"User: {turn.user_query}\n"
                f"Assistant: {turn.assistant_response[:200]}..."  # Truncate
            )
        
        if self.document_refs:
            docs = ", ".join(list(self.document_refs)[:5])
            summary_parts.append(f"\nDocuments discussed: {docs}")
        
        return "\n".join(summary_parts)


class ConversationMemory:
    """
    Manages conversation sessions and context.
    
    Features:
    - Session management
    - Context tracking
    - Entity extraction
    - Reference resolution
    """
    
    def __init__(self, max_sessions: int = 100, session_ttl: int = 3600):
        """
        Initialize conversation memory.
        
        Args:
            max_sessions: Maximum concurrent sessions to keep
            session_ttl: Session time-to-live in seconds (1 hour default)
        """
        self.sessions: Dict[str, ConversationSession] = {}
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl
        logger.info(f"Initialized conversation memory (max={max_sessions}, ttl={session_ttl}s)")
    
    def create_session(self, metadata: Optional[Dict] = None) -> str:
        """
        Create new conversation session.
        
        Returns:
            session_id
        """
        session_id = str(uuid.uuid4())
        now = datetime.now()
        
        session = ConversationSession(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )
        
        self.sessions[session_id] = session
        self._cleanup_old_sessions()
        
        logger.info(f"Created conversation session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """Get session by ID."""
        return self.sessions.get(session_id)
    
    def add_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_response: str,
        sources: List[str]
    ):
        """
        Add turn to session.
        
        Args:
            session_id: Session ID
            user_query: User's query
            assistant_response: Assistant's response
            sources: List of source filenames used
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Session not found: {session_id}")
            return
        
        # Extract entities from query
        entities = self._extract_entities(user_query)
        
        # Add turn
        session.add_turn(
            user_query=user_query,
            assistant_response=assistant_response,
            sources=sources,
            entities=entities
        )
        
        logger.debug(
            f"Added turn to session {session_id}: "
            f"{len(session.turns)} total turns"
        )
    
    def get_context_for_query(
        self,
        session_id: str,
        current_query: str,
        max_turns: int = 3
    ) -> str:
        """
        Get relevant context for current query.
        
        Args:
            session_id: Session ID
            current_query: Current user query
            max_turns: Maximum previous turns to include
        
        Returns:
            Formatted context string for LLM
        """
        session = self.get_session(session_id)
        if not session or not session.turns:
            return ""
        
        # Check if query contains references
        has_reference = self._contains_reference(current_query)
        
        if not has_reference:
            # No reference, maybe don't need full context
            # Just return summary
            return session.get_context_summary(max_turns=2)
        
        # Has reference ("that", "it", "them"), provide full context
        return session.get_context_summary(max_turns=max_turns)
    
    def resolve_references(
        self,
        session_id: str,
        query: str
    ) -> str:
        """
        Resolve references in query using conversation context.
        
        Example:
            Previous: "Tell me about backups"
            Current: "What about retention for that?"
            Resolved: "What about retention for backups?"
        
        Args:
            session_id: Session ID
            query: Query with potential references
        
        Returns:
            Query with references resolved
        """
        session = self.get_session(session_id)
        if not session or not session.turns:
            return query  # No context to resolve
        
        # Get last turn
        last_turn = session.turns[-1]
        
        # Simple reference resolution
        query_resolved = query
        
        # "that" ? last topic
        if 'that' in query.lower() and session.active_topics:
            topic = session.active_topics[0]
            query_resolved = query_resolved.replace('that', topic)
        
        # "it" ? last entity
        if 'it' in query.lower() and session.active_topics:
            entity = session.active_topics[0]
            query_resolved = query_resolved.replace('it', entity)
        
        # "those documents" ? document names
        if 'those documents' in query.lower():
            docs = list(session.document_refs)[:3]
            if docs:
                query_resolved = query_resolved.replace(
                    'those documents',
                    ', '.join(docs)
                )
        
        if query_resolved != query:
            logger.info(f"Resolved reference: '{query}' ? '{query_resolved}'")
        
        return query_resolved
    
    def _contains_reference(self, query: str) -> bool:
        """Check if query contains pronouns/references."""
        references = ['that', 'it', 'them', 'those', 'this', 'these']
        query_lower = query.lower()
        return any(ref in query_lower for ref in references)
    
    def _extract_entities(self, text: str) -> List[str]:
        """
        Extract key entities/topics from text.
        
        Simple approach: Extract noun phrases and important words.
        For production, consider using spaCy or similar NLP library.
        """
        import re
        
        # Remove common words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
            'to', 'for', 'of', 'with', 'by', 'from', 'about', 'as',
            'what', 'how', 'when', 'where', 'who', 'why', 'which', 'is', 'are'
        }
        
        # Extract words
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter stop words and short words
        entities = [w for w in words if w not in stop_words and len(w) > 3]
        
        # Return top 3
        return entities[:3]
    
    def _cleanup_old_sessions(self):
        """Remove expired sessions."""
        now = datetime.now()
        expired = []
        
        for session_id, session in self.sessions.items():
            age = (now - session.updated_at).total_seconds()
            if age > self.session_ttl:
                expired.append(session_id)
        
        for session_id in expired:
            del self.sessions[session_id]
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")
        
        # Limit total sessions
        if len(self.sessions) > self.max_sessions:
            # Remove oldest
            sorted_sessions = sorted(
                self.sessions.items(),
                key=lambda x: x[1].updated_at
            )
            to_remove = len(self.sessions) - self.max_sessions
            for session_id, _ in sorted_sessions[:to_remove]:
                del self.sessions[session_id]
            
            logger.info(f"Removed {to_remove} oldest sessions to stay under limit")
    
    def delete_session(self, session_id: str):
        """Delete session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Deleted session: {session_id}")
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get session statistics."""
        session = self.get_session(session_id)
        if not session:
            return {}
        
        return {
            'session_id': session_id,
            'created': session.created_at.isoformat(),
            'updated': session.updated_at.isoformat(),
            'turn_count': len(session.turns),
            'documents_used': list(session.document_refs),
            'active_topics': session.active_topics,
            'duration_minutes': (
                session.updated_at - session.created_at
            ).total_seconds() / 60
        }


# Global instance
conversation_memory = ConversationMemory()
```

---

### 2. Integration with Chat API

**File:** `src/app.py`

**Update chat endpoint to use conversation memory:**

```python
from src.conversation_memory import conversation_memory

@app.route('/api/chat', methods=['POST'])
def api_chat():
    """Chat endpoint with conversation memory."""
    try:
        data = request.get_json()
        
        # Pydantic validation
        request_data = ChatRequest(**data)
        message = sanitize_query(request_data.message)
        use_rag = request_data.use_rag
        chat_history = request_data.history
        
        # Get or create session ID
        session_id = data.get('session_id')
        if not session_id:
            session_id = conversation_memory.create_session()
        
        logger.info(
            f"[CHAT] Session: {session_id[:8]}, "
            f"RAG: {use_rag}, Query: {message[:50]}..."
        )
        
        # Resolve references using conversation memory
        resolved_message = conversation_memory.resolve_references(
            session_id,
            message
        )
        
        if resolved_message != message:
            logger.info(f"[MEMORY] Resolved: {message} ? {resolved_message}")
            message = resolved_message
        
        # Get conversation context
        conv_context = conversation_memory.get_context_for_query(
            session_id,
            message,
            max_turns=3
        )
        
        # ... existing RAG retrieval code ...
        
        if use_rag:
            results = doc_processor.retrieve_context(message)
            
            # Track sources for memory
            sources_used = list(set(r[1] for r in results))
            
            # Format context...
            formatted_context = doc_processor.format_context_for_llm(results)
            
            # Add conversation context if available
            if conv_context:
                user_prompt = f"""{conv_context}

---

{formatted_context}

---

Question: {message}

Remember: Consider the conversation history above."""
            else:
                user_prompt = f"""{formatted_context}

---

Question: {message}"""
        
        # ... generate response ...
        
        # After response generation, store turn
        def store_turn_after_complete(response_text):
            """Store turn after response is complete."""
            conversation_memory.add_turn(
                session_id=session_id,
                user_query=message,
                assistant_response=response_text,
                sources=sources_used if use_rag else []
            )
        
        # Wrap generator to capture full response
        full_response = []
        
        def generate_with_memory():
            for chunk in generate():  # Original generator
                full_response.append(chunk)
                yield chunk
            
            # After streaming complete
            response_text = ''.join(full_response)
            store_turn_after_complete(response_text)
        
        response = Response(generate_with_memory(), mimetype='text/event-stream')
        response.headers['X-Session-ID'] = session_id
        return response
        
    except Exception as e:
        logger.error(f"[CHAT] Error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500
```

---

### 3. Session Management API

**File:** `src/app.py`

**Add session management endpoints:**

```python
@app.route('/api/conversation/session', methods=['POST'])
def api_create_session():
    """Create new conversation session."""
    session_id = conversation_memory.create_session()
    return jsonify({
        'success': True,
        'session_id': session_id
    })


@app.route('/api/conversation/session/<session_id>', methods=['GET'])
def api_get_session(session_id: str):
    """Get session details."""
    stats = conversation_memory.get_session_stats(session_id)
    
    if not stats:
        return jsonify({
            'success': False,
            'message': 'Session not found'
        }), 404
    
    return jsonify({
        'success': True,
        'session': stats
    })


@app.route('/api/conversation/session/<session_id>', methods=['DELETE'])
def api_delete_session(session_id: str):
    """Delete conversation session."""
    conversation_memory.delete_session(session_id)
    return jsonify({
        'success': True,
        'message': 'Session deleted'
    })
```

---

### 4. Frontend Integration

**File:** `static/js/app.js` (or equivalent)

**Update to maintain session ID:**

```javascript
class ConversationManager {
    constructor() {
        this.sessionId = null;
    }
    
    async startSession() {
        const response = await fetch('/api/conversation/session', {
            method: 'POST'
        });
        const data = await response.json();
        this.sessionId = data.session_id;
        console.log('Started session:', this.sessionId);
    }
    
    async sendMessage(message) {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: message,
                use_rag: true,
                history: [],  // Not needed with memory
                session_id: this.sessionId
            })
        });
        
        // Handle streaming response...
        return response;
    }
    
    async getSessionStats() {
        if (!this.sessionId) return null;
        
        const response = await fetch(
            `/api/conversation/session/${this.sessionId}`
        );
        return await response.json();
    }
    
    async clearSession() {
        if (!this.sessionId) return;
        
        await fetch(`/api/conversation/session/${this.sessionId}`, {
            method: 'DELETE'
        });
        
        // Start new session
        await this.startSession();
    }
}

// Usage
const conversation = new ConversationManager();
await conversation.startSession();
```

---

## Testing

### Unit Tests

**File:** `tests/test_conversation_memory.py`

```python
import pytest
from src.conversation_memory import conversation_memory, ConversationSession


def test_create_session():
    """Test session creation."""
    session_id = conversation_memory.create_session()
    
    assert session_id
    session = conversation_memory.get_session(session_id)
    assert session is not None
    assert len(session.turns) == 0


def test_add_turn():
    """Test adding turns."""
    session_id = conversation_memory.create_session()
    
    conversation_memory.add_turn(
        session_id=session_id,
        user_query="What are backups?",
        assistant_response="Backups are...",
        sources=["doc1.pdf"]
    )
    
    session = conversation_memory.get_session(session_id)
    assert len(session.turns) == 1
    assert 'doc1.pdf' in session.document_refs


def test_reference_resolution():
    """Test reference resolution."""
    session_id = conversation_memory.create_session()
    
    # Add context
    conversation_memory.add_turn(
        session_id=session_id,
        user_query="Tell me about backups",
        assistant_response="Backups are...",
        sources=[]
    )
    
    # Resolve reference
    resolved = conversation_memory.resolve_references(
        session_id,
        "What about retention for that?"
    )
    
    # Should resolve "that" to "backups"
    assert 'backup' in resolved.lower()


def test_context_generation():
    """Test context generation."""
    session_id = conversation_memory.create_session()
    
    # Add multiple turns
    for i in range(5):
        conversation_memory.add_turn(
            session_id=session_id,
            user_query=f"Query {i}",
            assistant_response=f"Response {i}",
            sources=[]
        )
    
    # Get context
    context = conversation_memory.get_context_for_query(
        session_id,
        "New query",
        max_turns=3
    )
    
    # Should have 3 most recent turns
    assert "Query 4" in context
    assert "Query 3" in context
    assert "Query 2" in context
    assert "Query 0" not in context


def test_session_cleanup():
    """Test session cleanup."""
    # Create sessions with short TTL
    memory = ConversationMemory(session_ttl=1)
    
    session_id = memory.create_session()
    
    import time
    time.sleep(2)
    
    # Should be cleaned up
    memory._cleanup_old_sessions()
    assert memory.get_session(session_id) is None
```

---

### Integration Tests

```python
def test_multi_turn_conversation():
    """Test multi-turn conversation flow."""
    session_id = conversation_memory.create_session()
    
    # Turn 1
    conversation_memory.add_turn(
        session_id,
        "What are backups?",
        "Backups are copies of data...",
        ["doc1.pdf"]
    )
    
    # Turn 2 with reference
    query2 = "How often should I do that?"
    resolved = conversation_memory.resolve_references(session_id, query2)
    
    assert 'backup' in resolved.lower()
    
    conversation_memory.add_turn(
        session_id,
        query2,
        "Backups should be done daily...",
        ["doc1.pdf"]
    )
    
    # Turn 3
    context = conversation_memory.get_context_for_query(
        session_id,
        "What about retention?",
        max_turns=2
    )
    
    assert "backup" in context.lower()
    assert len(conversation_memory.get_session(session_id).turns) == 2
```

---

## Success Metrics

- [ ] **Multi-turn support:** 3+ turns work naturally
- [ ] **Reference resolution:** 85%+ accuracy
- [ ] **Context relevance:** Improves response quality
- [ ] **Latency:** <50ms overhead per request
- [ ] **Session management:** No memory leaks

---

## Configuration

**File:** `src/config.py`

```python
# Conversation Memory Settings
ENABLE_CONVERSATION_MEMORY: bool = True
MAX_CONVERSATION_SESSIONS: int = 100
SESSION_TTL_SECONDS: int = 3600  # 1 hour
MAX_CONTEXT_TURNS: int = 3       # Turns to include in context
```

---

## Rollback Plan

```python
# Disable in config
ENABLE_CONVERSATION_MEMORY = False

# Or revert code
git checkout main src/conversation_memory.py src/app.py
```

---

## Next Steps After Phase 1

Phase 1 Complete! Move to Phase 2:
- Semantic Chunking
- Parent-Child Chunking
- Cross-Encoder Reranking

---

**Status:** Ready to implement  
**Estimated Time:** 3-4 days (12-16 hours)  
**Risk:** Medium (more complex state management)  
**Dependencies:** None (works independently)

---

*Implementation Guide Version: 1.0*  
*See: RAG_ROADMAP_2025.md for context*
