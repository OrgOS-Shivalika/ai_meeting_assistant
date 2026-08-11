# System Architecture - Agentic Meeting Assistant

Detailed architectural overview and design decisions.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Diagram](#component-diagram)
3. [Data Flow Architecture](#data-flow-architecture)
4. [Interaction Patterns](#interaction-patterns)
5. [Design Patterns](#design-patterns)
6. [Technology Decisions](#technology-decisions)
7. [Scalability Considerations](#scalability-considerations)
8. [Security Architecture](#security-architecture)
9. [Deployment Architecture](#deployment-architecture)

---

## Architecture Overview

### Architectural Style: Layered (N-Tier) Architecture

```
┌─────────────────────────────────────────────────────┐
│            Presentation Layer (API)                 │
│  - HTTP Request Handling (FastAPI)                  │
│  - Input Validation (Pydantic)                      │
│  - Response Formatting                              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         Application Logic Layer (Pipeline)          │
│  - Workflow Orchestration                           │
│  - Component Coordination                           │
│  - Error Handling & Propagation                     │
└────────────────────┬────────────────────────────────┘
                     │
       ┌─────────────┼─────────────────┐
       │             │                 │
┌──────▼────┐  ┌─────▼──────┐  ┌─────▼──────┐
│  Service  │  │  AI Agent  │  │ Processor  │
│   Layer   │  │   Layer    │  │   Layer    │
│(External  │  │ (OpenAI)   │  │(Data       │
│  API)     │  │            │  │ Transform) │
└───────────┘  └────────────┘  └────────────┘
       │             │                │
       └─────────────┼────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│         Configuration & Utilities Layer              │
│  - Environment Variables (settings.py)               │
│  - Logging Configuration                            │
│  - Storage Management                               │
└─────────────────────────────────────────────────────┘
```

### Key Principles

1. **Separation of Concerns**
   - Each layer has a single responsibility
   - Loose coupling between layers
   - High cohesion within layers

2. **Dependency Management**
   - Top-down dependencies (higher layers depend on lower)
   - No circular dependencies
   - Easy to mock for testing

3. **Scalability**
   - Stateless API design
   - Asynchronous processing
   - Background job queue support

4. **Maintainability**
   - Clear module organization
   - Consistent naming conventions
   - Comprehensive documentation

---

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────┐         │
│  │              API Routes (routes.py)                 │         │
│  │  • POST /meetings                                   │         │
│  │  • GET /meetings/{job_id}                          │         │
│  │  • GET /meetings/{job_id}/result                   │         │
│  │  • GET /health                                      │         │
│  └────┬────────────────────────────────────────────────┘         │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────────────────────────────────────┐         │
│  │         MeetingPipeline (meeting_pipeline.py)       │         │
│  │  • Orchestrates complete workflow                   │         │
│  │  • Manages component interaction                    │         │
│  │  • Handles error propagation                        │         │
│  └────┬──────────────┬──────────────┬──────────────────┘         │
│       │              │              │                           │
│       │              │              │                           │
│   ┌───▼──────┐  ┌────▼─────┐  ┌────▼──────┐                     │
│   │RecallAI  │  │OpenAI    │  │Transcript│                     │
│   │Service   │  │Analyzer  │  │Processor │                     │
│   │          │  │          │  │          │                     │
│   │• Create  │  │• Analyze │  │• Clean   │                     │
│   │  Bot     │  │  Transcript  │  Text     │                     │
│   │• Wait    │  │• Extract │  │• Format  │                     │
│   │  Transcript  │  Insights   │  Transcript  │                   │
│   │• Get     │  │• Return  │  │• Structure│                     │
│   │  Status  │  │  JSON    │  │  Output  │                     │
│   └───┬──────┘  └────┬─────┘  └────┬──────┘                     │
│       │              │              │                           │
│       └──────────────┼──────────────┘                           │
│                      │                                          │
│  ┌───────────────────▼──────────────────┐                       │
│  │   JobStore (job_store.py)            │                       │
│  │  • In-memory job state management    │                       │
│  │  • Status tracking                   │                       │
│  │  • Result storage                    │                       │
│  └────────────────────────────────────┘                         │
│                                                                  │
│  ┌──────────────────────────────────────┐                       │
│  │  Settings & Logger (config, utils)   │                       │
│  │  • Environment configuration         │                       │
│  │  • Logging setup                     │                       │
│  └──────────────────────────────────────┘                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
       │                          │
       │                          │
   ┌───▼──────────┐    ┌──────────▼──────┐
   │ Recall.ai    │    │  OpenAI API     │
   │ External     │    │  External       │
   │ API          │    │  API            │
   └──────────────┘    └─────────────────┘
```

---

## Data Flow Architecture

### Request-Response Cycle

```
1. CLIENT REQUEST
   POST /meetings
   {
     "meeting_url": "https://meet.google.com/..."
   }
          │
          ▼
2. REQUEST VALIDATION
   Pydantic validates schema
   URL format checking
          │
          ▼
3. JOB CREATION
   Generate UUID job_id
   Store in job_store with "processing" status
          │
          ▼
4. BACKGROUND TASK SCHEDULING
   Add run_pipeline() to task queue
   Return immediately to client
          │
          ▼
5. CLIENT RECEIVES RESPONSE
   {
     "job_id": "uuid",
     "status": "processing"
   }
```

### Background Processing Cycle

```
1. BOT CREATION PHASE
   RecallService.create_bot(url)
   └─ HTTP POST to Recall.ai
   └─ Returns bot_id
          │
          ▼
2. TRANSCRIPT WAITING PHASE
   RecallService.wait_for_transcript(bot_id)
   └─ Polls Recall.ai every 10-30 seconds
   └─ Returns transcript download URL
          │
          ▼
3. TRANSCRIPT FETCHING PHASE
   requests.get(transcript_url).json()
   └─ Downloads transcript JSON
          │
          ▼
4. TRANSCRIPT FORMATTING PHASE
   TranscriptProcessor.format(json)
   └─ Extracts speaker, words
   └─ Cleans text
   └─ Returns formatted string
          │
          ▼
5. AI ANALYSIS PHASE
   OpenAITranscriptAnalyzer.analyze(formatted)
   └─ Formats prompt
   └─ HTTP POST to OpenAI
   └─ Returns JSON analysis
          │
          ▼
6. RESULT STORAGE
   Store analysis in job_store[job_id]["result"]
   Update job_store[job_id]["status"] = "completed"
          │
          ▼
7. CLIENT RETRIEVES RESULT
   GET /meetings/{job_id}/result
   └─ Returns stored analysis JSON
```

### Data Transformation Pipeline

```
Raw Transcript JSON (from Recall.ai)
    │
    ├─ Block 1: {participant: {name: "Alice"}, words: [{text: "Hello"}]}
    ├─ Block 2: {participant: {name: "Bob"}, words: [{text: "Hi"}]}
    └─ Block N: {...}
    │
    ▼
TranscriptProcessor.format()
    │
    ├─ Extract speaker names
    ├─ Join words into sentences
    ├─ Remove extra whitespace
    └─ Clean punctuation
    │
    ▼
Formatted Transcript String
    │
    ├─ Alice: Hello everyone, welcome to the meeting.
    ├─ Bob: Thanks for having me, great to be here.
    └─ Alice: Let's start with Q2 planning.
    │
    ▼
OpenAITranscriptAnalyzer.analyze()
    │
    ├─ Inject into prompt template
    ├─ Send to GPT-4o-mini with JSON mode
    └─ Receive structured response
    │
    ▼
Structured Analysis JSON
    │
    ├─ cleaned_transcript: [...]
    ├─ summary: "..."
    ├─ key_decisions: [...]
    ├─ action_items: [{task, owner, due_date, ...}]
    └─ risks_blockers: [{item, severity, mitigation}]
```

---

## Interaction Patterns

### 1. Layered Pattern

**API Layer ↔ Pipeline Layer ↔ Service/Processor Layers**

```python
# API calls Pipeline
pipeline = MeetingPipeline()
result = pipeline.run(meeting_url)

# Pipeline calls Services
recall = RecallService()
bot = recall.create_bot(meeting_url)

# Pipeline calls Processors
formatted = TranscriptProcessor.format(transcript_json)
```

### 2. Service Injection Pattern

```python
# Services are initialized where needed
class MeetingPipeline:
    def __init__(self):
        self.recall = RecallService()  # Injected dependency
```

### 3. Job Callback Pattern

```python
# Background task updates job store on completion
def background_task(job_id):
    try:
        result = pipeline.run(url)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["result"] = str(e)
```

### 4. Configuration Singleton Pattern

```python
# Single settings instance used across application
from app.config.settings import settings

# Used in all services
class RecallService:
    def __init__(self):
        self.api_key = settings.RECALL_API_KEY
```

---

## Design Patterns

### 1. **Facade Pattern**
- `MeetingPipeline` provides simplified interface to complex subsystems
- Hides details of bot creation, transcript processing, and AI analysis
- Single entry point for meeting processing workflow

### 2. **Service Locator Pattern**
- Configuration centralized in `settings.py`
- All services access configuration through single source

### 3. **Strategy Pattern**
- `TranscriptProcessor.format()` could be extended with multiple strategies:
  - Verbatim format
  - Cleaned format
  - Summarized format

### 4. **Observer Pattern** (Future)
- Potential implementation for job status updates
- WebSocket notifications when processing completes

### 5. **Retry Pattern**
- `wait_for_transcript()` implements retry logic with exponential backoff
- Could be generalized into reusable decorator

```python
def retry_with_backoff(func, max_retries=3, backoff_factor=2):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            sleep(backoff_factor ** attempt)
```

---

## Technology Decisions

### Why FastAPI?

✅ **Advantages**:
- Built on modern Python (async/await)
- Automatic OpenAPI documentation
- Built-in Pydantic validation
- Fast execution
- Easy to deploy

❌ **Alternatives Considered**:
- Django: Too heavy for this use case
- Flask: Less built-in validation
- Starlette: Lower-level, would need more boilerplate

### Why OpenAI GPT-4o-mini?

✅ **Advantages**:
- Cost-effective for this use case
- Strong performance on text analysis
- JSON mode for structured output
- No hallucination concerns with strict prompts

❌ **Alternatives Considered**:
- GPT-4: Overkill for this task, higher cost
- Local LLMs: Infrastructure overhead, quality trade-offs

### Why Recall.ai?

✅ **Advantages**:
- Supports multiple meeting platforms
- Reliable transcription
- Handles authentication
- Streaming transcript capability

❌ **Alternatives Considered**:
- Direct API calls: Would need to manage meeting authentication
- Manual recording: Not scalable

### Why In-Memory Job Store?

✅ **Advantages for MVP**:
- No database setup needed
- Fast access
- Simple implementation

❌ **Limitations**:
- Data lost on restart
- Not suitable for multi-instance
- Limited to single machine

🔄 **Future**: Migrate to PostgreSQL + Redis

---

## Scalability Considerations

### Current Limitations

1. **Single Instance Only**
   - Job store is in-memory (local to instance)
   - No inter-process communication

2. **Sequential Processing**
   - One job processed at a time
   - Long transcripts tie up resources

3. **No Caching**
   - Same transcript analyzed multiple times = duplicate API calls

4. **No Database**
   - Can't persist job history
   - Can't enable analytics

### Scaling Strategies

#### Strategy 1: Distributed Job Queue

```
Client Request
    │
    ├─ API creates job
    ├─ Adds to Message Queue (Redis, RabbitMQ)
    │
    ▼
Multiple Workers
    ├─ Worker 1: processes job A
    ├─ Worker 2: processes job B
    └─ Worker N: processes job N
    │
    ▼
Shared Database
    └─ Stores results accessible to all workers
```

Implementation:
```python
# Using Celery
from celery import Celery

app = Celery('agentic_assistant')

@app.task
def process_meeting(job_id, meeting_url):
    # Background processing logic
    pass
```

#### Strategy 2: Caching Layer

```
Request for transcript analysis
    │
    ├─ Check Redis cache
    ├─ If cached: return cached result
    └─ If not: process and cache result
```

#### Strategy 3: Database Migration

```
Current: In-Memory Dictionary
    jobs = {}

Future: PostgreSQL
    CREATE TABLE jobs (
        id UUID PRIMARY KEY,
        meeting_url VARCHAR,
        status VARCHAR,
        result JSONB,
        created_at TIMESTAMP,
        completed_at TIMESTAMP
    );
```

#### Strategy 4: API Rate Limiting

```python
from slowapi import Limiter

limiter = Limiter(key_func=get_remote_address)

@app.post("/meetings")
@limiter.limit("100/hour")
def create_meeting(...):
    pass
```

---

## Security Architecture

### Current Security Measures

1. **API Key Management**
   - Keys stored in environment variables
   - Not hardcoded in source
   - Protected in `.gitignore`

2. **Input Validation**
   - Pydantic validates all requests
   - Type checking enforced

3. **Error Handling**
   - No sensitive data in error messages
   - Detailed logging for debugging

### Recommended Security Enhancements

#### 1. API Authentication

```python
from fastapi.security import HTTPBearer, HTTPAuthCredential

security = HTTPBearer()

@app.post("/meetings")
async def create_meeting(
    request: MeetingRequest,
    credentials: HTTPAuthCredential = Depends(security)
):
    # Verify API key
    if credentials.credentials != VALID_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid credentials")
```

#### 2. HTTPS/TLS

```bash
# Production deployment requires HTTPS
# Use Let's Encrypt for free SSL certificates
```

#### 3. Request Signing

```python
import hmac
import hashlib

def verify_request_signature(body: str, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        body.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
```

#### 4. Rate Limiting

```python
from slowapi.errors import RateLimitExceeded

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"}
    )
```

#### 5. CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trusted-domain.com"],  # Be specific
    allow_credentials=True,
    allow_methods=["POST", "GET"],  # Restrict methods
    allow_headers=["Content-Type"]
)
```

---

## Deployment Architecture

### Development Environment

```
Local Machine
├─ Python venv
├─ FastAPI dev server (uvicorn)
├─ .env file with test keys
└─ SQLite (optional)
```

### Production Environment Options

#### Option 1: Cloud Platform (Recommended)

```
┌────────────────────────────────────┐
│       Load Balancer / CDN           │
└────────┬─────────────────────────────┘
         │
┌────────▼──────────────────────────────┐
│     Container Orchestration (K8s)     │
├────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  │ API Pod  │  │ API Pod  │  │ API Pod  │
│  │ (3x)     │  │ (3x)     │  │ (3x)     │
│  └──────────┘  └──────────┘  └──────────┘
│  ┌──────────┐  ┌──────────┐
│  │Worker Pod│  │Worker Pod│
│  └──────────┘  └──────────┘
└────────┬──────────────────────────────┘
         │
┌────────▼──────────────────────────────┐
│   Managed Services                     │
├────────────────────────────────────────┤
│  • PostgreSQL (RDS)                    │
│  • Redis (ElastiCache)                 │
│  • Message Queue (SQS/RabbitMQ)        │
│  • Monitoring (CloudWatch/Datadog)     │
└────────────────────────────────────────┘
```

#### Option 2: VPS Deployment

```
VPS Instance
├─ Nginx (reverse proxy)
├─ Systemd service (uvicorn)
├─ PostgreSQL
├─ Redis
└─ Certbot (SSL)
```

#### Option 3: Serverless (AWS Lambda)

```
Client Request
    │
    ├─ API Gateway
    ├─ Lambda Function (FastAPI ASGI)
    ├─ RDS (database)
    └─ SQS (job queue)
```

### Infrastructure as Code (Terraform)

```hcl
resource "aws_ecs_cluster" "main" {
  name = "agentic-assistant-cluster"
}

resource "aws_ecs_service" "api" {
  name            = "api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 3
}

resource "aws_rds_instance" "postgres" {
  allocated_storage    = 20
  engine               = "postgres"
  instance_class       = "db.t3.micro"
  db_name              = "agentic_db"
}
```

---

## Monitoring & Observability

### Metrics to Track

```
Application Metrics:
├─ Request rate (requests/sec)
├─ Response time (p50, p95, p99)
├─ Error rate (errors/sec)
├─ Job completion rate
└─ Average processing time

Infrastructure Metrics:
├─ CPU usage
├─ Memory usage
├─ Disk I/O
├─ Network I/O
└─ Availability

Business Metrics:
├─ Meetings processed (total, daily)
├─ Analysis accuracy
├─ User satisfaction
└─ Cost per meeting
```

### Logging Strategy

```python
# Structured logging
import json

def log_event(event_type, data):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "data": data
    }
    print(json.dumps(log_entry))

# Usage
log_event("meeting_created", {"job_id": "...", "url": "..."})
log_event("transcript_processing", {"bot_id": "...", "status": "..."})
```

---

**Document Version**: 1.0.0  
**Last Updated**: April 28, 2026

For implementation details, see [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)
