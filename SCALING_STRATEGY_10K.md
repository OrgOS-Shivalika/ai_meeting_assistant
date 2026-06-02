# Scaling Strategy: 10,000 Concurrent Users

This document outlines the architectural and infrastructure roadmap required to scale the Agentic Meeting Assistant to support **10,000 active concurrent users** and their real-time meeting streams.

## 1. Current State vs. Target State

### Current State
*   **Web Server**: Single/Few FastAPI instances handling both REST API and WebSocket connections.
*   **Background Processing**: Single Celery worker processing meeting summaries, embeddings, and graph extraction sequentially.
*   **Database**: Single PostgreSQL instance handling relational data and pgvector.
*   **Live Stream**: In-memory `StreamManager` maintaining rolling context and state per worker.
*   **AI Integration**: Direct synchronous (or threaded) calls to OpenAI APIs.

### Target State (10k Users)
*   **Web Tier**: Horizontally scaled, stateless FastAPI pods behind a robust load balancer (e.g., Nginx, AWS ALB).
*   **WebSocket Tier**: Dedicated WebSocket fleet using Redis Pub/Sub for cross-node broadcasting.
*   **Processing Tier**: Autoscaling Celery fleets partitioned by queue (e.g., `high_priority_live`, `batch_embedding`, `graph_extraction`).
*   **Data Tier**: High-availability PostgreSQL cluster with read replicas, dedicated vector DB (e.g., Pinecone or distributed pgvector), and Redis for ephemeral state.
*   **AI Integration**: Async, batched, and rate-limit-aware LLM gateways, potentially utilizing dedicated provisioned throughput or multi-region routing.

---

## 2. Decoupling and Statelessness

### The "Stateful" Live Stream Problem
Currently, the `StreamManager` and `MeetingStateStore` hold live task data and buffers in the memory of a single Python process. If that pod restarts, or if a webhook hits a different pod, the state is lost.

**Solution: Externalize State**
*   Move `thought_buffer`, `speaker_buffer`, and `active_tasks` to **Redis**.
*   When a webhook arrives, the worker fetches the current context from Redis, processes the chunk, updates Redis, and emits the event.
*   This makes every FastAPI pod completely **stateless**, allowing infinite horizontal scaling.

---

## 3. WebSocket Infrastructure (The "C10K" Problem)

Handling 10,000 concurrent WebSockets requires specialized architecture.

**Solution: Redis Pub/Sub Backplane**
*   **Current Issue**: `manager.broadcast` only sends messages to users connected to *that specific server*.
*   **Target**: Implement a Redis Pub/Sub backplane (e.g., using `broadcaster` or `fastapi-socketio`).
*   When the `LiveEventBus` emits an event, it publishes to a Redis channel (`meeting:{id}:events`).
*   All WebSocket servers subscribe to Redis. Whichever server holds the user's connection will receive the message from Redis and push it down the socket.

---

## 4. Scaling the Cognitive Engine (LLMs)

10,000 users generating live tasks means massive LLM API volume.

**Solution: Rate Limit Management & Batching**
*   **Provisioned Throughput**: Transition from Pay-As-You-Go OpenAI tiers to Provisioned Throughput (PTUs) on Azure OpenAI or AWS Bedrock to guarantee latency.
*   **Semantic Batching Optimization**: Increase the `WORD_THRESHOLD` dynamically based on system load. Under heavy load, buffer larger chunks before calling the LLM.
*   **Fallback Models**: For simple deduplication or classification, route requests to faster, cheaper models (e.g., GPT-4o-mini, Claude 3 Haiku, or self-hosted open-source models like Llama 3 8B) while reserving GPT-4-class models for complex Narrative Synthesis.
*   **Circuit Breakers**: Implement robust exponential backoff and circuit breakers to prevent cascading failures if the LLM provider experiences degraded performance.

---

## 5. Database Architecture

PostgreSQL handling relational data, JSONB, and dense vector embeddings simultaneously will become a bottleneck.

**Solution: Read/Write Splitting & Vector Offloading**
*   **Connection Pooling**: Implement PgBouncer or AWS RDS Proxy to manage the thousands of concurrent database connections from the scaled FastAPI pods.
*   **Read Replicas**: Route all non-critical `GET` requests (e.g., fetching old transcripts, dashboard analytics) to read replicas.
*   **Dedicated Vector DB**: Migrate the `document_chunks` and `meeting_chunks` embeddings from `pgvector` to a purpose-built distributed vector database (e.g., Pinecone, Qdrant, Milvus) for sub-millisecond retrieval at scale.

---

## 6. Asynchronous Processing (Celery Fleet)

The post-meeting synthesis (Phase 10) and graph extraction are computationally heavy.

**Solution: Dedicated Auto-Scaling Queues**
*   **Queue Partitioning**: Split tasks into separate RabbitMQ/Redis queues:
    *   `live_tasks`: High priority, fast execution (Task detection).
    *   `synthesis`: Medium priority (Post-meeting summarization).
    *   `embedding_graph`: Low priority, compute-heavy (Vectorization and Knowledge Graph extraction).
*   **Worker Autoscaling**: Use Kubernetes Event-driven Autoscaling (KEDA) to scale Celery worker pods based on queue depth. If 500 meetings end at 3:00 PM, KEDA should instantly spin up 50 extra `synthesis` workers.

---

## 7. Infrastructure & Deployment

*   **Container Orchestration**: Deploy entirely on Kubernetes (EKS/GKE).
*   **Ingress Controller**: Use a high-performance ingress controller (e.g., Nginx Ingress or Traefik) configured specifically for WebSocket timeout and connection retention.
*   **CDN / Edge Caching**: Serve the React frontend and static assets via Cloudflare or AWS CloudFront to reduce load on the origin servers.

---

## 8. Observability & Telemetry

At 10k scale, silent failures are deadly.

*   **Distributed Tracing**: Implement OpenTelemetry (Jaeger/DataDog) to trace a request from the Recall.ai Webhook → Redis → Celery → OpenAI → WebSocket → Client.
*   **Metrics**: Expose Prometheus metrics for:
    *   LLM token usage per minute.
    *   Live Task extraction latency.
    *   WebSocket concurrent connections.
    *   Celery queue processing time.
*   **Alerting**: PagerDuty alerts for API rate limits nearing thresholds, elevated 500 errors, or sudden drops in WebSocket connections.

---

## Conclusion
The path to 10k users requires moving from a tightly coupled, in-memory monolith to a distributed, stateless, and queue-driven micro-architecture. The immediate first steps are **externalizing the StreamSession state to Redis** and **implementing a Pub/Sub backplane for WebSockets**.