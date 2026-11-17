# RescueAI Project Specification

## Project Name

RescueAI

## Technology Stack

- **Backend:** Python + FastAPI
- **Task processing:** Celery + Redis
- **Database:** PostgreSQL
- **AI:** OpenAI API
- **Frontend:** React (to be developed after the backend)
- **Local environment:** Docker Compose
- **Testing:** Pytest

# MASTER PROMPT — RescueAI: AI-Powered Failure Recovery System

Act as a senior Python backend engineer, distributed systems architect, AI engineer, and technical mentor. Help me build a production-inspired portfolio project called **RescueAI**, an AI-powered job failure detection, diagnosis, and recovery platform.

## 1. Project objective

Build a backend platform that accepts background jobs, executes them asynchronously, detects failures, records execution history, applies safe retry policies, and uses an LLM to analyze failures and recommend corrective actions.

The system must demonstrate practical backend engineering, asynchronous processing, database design, distributed task processing, reliability engineering, AI integration, automated testing, and deployment practices.

The project should be suitable for a software engineering portfolio and backend/SDE interviews.

## 2. Technology stack

Use the following technologies:

- Python 3.12
- FastAPI for REST APIs
- Pydantic for request validation and structured AI responses
- PostgreSQL as the durable source of truth
- SQLAlchemy 2.x for ORM and database access
- Alembic for schema migrations
- Redis as the Celery broker and for appropriate short-lived coordination data
- Celery for background job execution and asynchronous AI analysis
- OpenAI API for failure classification and root-cause analysis
- Pytest for automated testing
- Docker and Docker Compose for local development
- Ruff for linting and formatting
- GitHub Actions for CI after the application works
- React with TypeScript for an optional frontend, implemented only after the backend is stable

Choose mutually compatible stable dependency versions and pin them appropriately. Explain any compatibility decisions.

## 3. Core functionality

### Job management
- Submit jobs with a job type, validated payload, and optional idempotency key.
- Retrieve jobs by ID and list them with pagination and filters.
- Track job status, attempt count, creation time, execution duration, and completion time.
- Support manual retry and cancellation requests.
- Provide sample jobs that simulate API calls, ETL processing, and report generation.

### Failure tracking
- Persist every execution attempt in PostgreSQL.
- Capture error type, sanitized error message, relevant stack trace, timestamps, and duration.
- Maintain a clear and valid job state machine.
- Distinguish retryable failures from permanent failures.
- Move exhausted jobs to a dead-letter state while retaining their history.

### Automatic recovery
- Implement configurable maximum attempts, exponential backoff, and jitter.
- Handle network timeouts, transient failures, permanent validation errors, and task timeouts appropriately.
- Prevent concurrent or duplicate execution where possible.
- Make business operations idempotent.
- Handle worker crashes and interrupted jobs through a documented recovery mechanism.
- Never retry every exception indiscriminately.

### AI failure analysis
- Create a separate AI service module.
- Send sanitized error context, relevant logs, and attempt history to the OpenAI API.
- Return structured analysis containing:
  - Failure category
  - Probable root cause
  - Supporting evidence
  - Recommended recovery action
  - Confidence estimate
  - Whether human approval is required
- Validate AI output using Pydantic.
- Store analyses, model metadata, and analysis timestamps in PostgreSQL.
- Allow analysis to run asynchronously.
- Handle AI timeouts, rate limits, invalid responses, and service outages.
- Provide a deterministic fallback when AI is unavailable.
- Never allow the LLM to directly execute arbitrary SQL, shell commands, or production modifications.

### Monitoring
- Provide job status summaries, failure counts, retry counts, recovery rates, and execution durations.
- Implement health checks for the API, database, and Redis connectivity.
- Use structured logging and correlation IDs.
- Provide enough diagnostic information to investigate failures without exposing secrets.

## 4. Architecture and design requirements

Use a modular monolith with separate API and worker processes.

Organize the application into:
- API routers
- Configuration and security
- Database models and session management
- Pydantic schemas
- Repository/data access layer
- Job management services
- Recovery policy engine
- AI analysis service
- Celery application and task definitions
- Automated tests

PostgreSQL must remain the durable source of truth. Redis must not be the only place where job state or failure history is stored.

Use database transactions for consistent state changes. Explicitly address the gap between committing a job to PostgreSQL and publishing a task to Redis. Explain and, when appropriate, implement the transactional outbox pattern.

Document the difference between task delivery guarantees and exactly-once business execution. Do not claim exactly-once execution merely because a queue or idempotency key exists.

Define valid job state transitions and enforce them through application logic and appropriate database constraints.

## 5. API requirements

Design versioned endpoints under `/api/v1`, including:

- POST `/jobs`
- GET `/jobs`
- GET `/jobs/{job_id}`
- GET `/jobs/{job_id}/attempts`
- POST `/jobs/{job_id}/retry`
- POST `/jobs/{job_id}/cancel`
- GET `/jobs/{job_id}/analysis`
- POST `/jobs/{job_id}/analyze`
- GET `/metrics/summary`
- GET `/health`

Use correct HTTP status codes, validation, pagination, and consistent error responses. Return HTTP 202 when accepting asynchronous work.

Add authentication and authorization before exposing manual recovery or administrative actions beyond local development.

## 6. Security and reliability

- Keep secrets in environment variables.
- Provide `.env.example` containing placeholders only.
- Never commit API keys or credentials.
- Sanitize logs before sending them to the AI service.
- Validate job types and payloads.
- Add request timeouts and bounded retry policies.
- Protect manual retry endpoints against repeated submissions.
- Include appropriate concurrency controls.
- Avoid logging sensitive payload contents.
- Document limitations and failure scenarios.

## 7. Testing requirements

Write tests for:
- Job creation and retrieval
- Request validation
- Successful execution
- Retryable failures
- Permanent failures
- Maximum retry exhaustion
- Backoff policy
- Duplicate submissions
- Concurrent retry requests
- AI response validation
- AI service failures
- Database transaction failures
- Worker interruption and recovery
- API health checks

Use mocks for external API calls and the OpenAI API. Include integration tests using real PostgreSQL and Redis containers where appropriate.

Do not rely solely on mocked tests to claim that the distributed system works.

## 8. Development rules

Build this project incrementally.

Before implementing each phase:
1. Inspect the existing repository and previous implementation.
2. Summarize the relevant architecture and files.
3. Identify dependencies and assumptions.
4. State the implementation plan.

Then implement only the requested phase.

After implementing:
1. Run relevant tests, linting, and type checks if configured.
2. Show the commands used and their actual results.
3. Fix failures caused by your changes.
4. Explain which files were created or modified.
5. Explain important design decisions and trade-offs.
6. Give exact commands to run the application and verify the feature.
7. List any unresolved issues honestly.

Never claim tests passed without running them. Never replace working code with a fresh scaffold without justification. Do not silently change architecture, dependency versions, database schemas, or public API contracts.

If a requirement is ambiguous, ask a focused question or state a reasonable assumption before proceeding.

Avoid unnecessary abstractions, premature microservices, and features that are not needed for the current phase.

## 9. Mentoring requirements

I want to understand the implementation, not just receive generated code.

Explain:
- Why each component exists
- How requests flow through the system
- How jobs move from FastAPI to Redis, Celery, and PostgreSQL
- What happens when each component fails
- Why transactions, retries, and idempotency matter
- How the AI service differs from the deterministic recovery engine
- How to debug common errors

Use practical examples and concise explanations. Point out relevant interview questions when appropriate.

## 10. Definition of done

The completed project should:
- Run locally using Docker Compose.
- Accept and execute sample background jobs.
- Simulate and record failures.
- Retry eligible failures safely within configured limits.
- Retain full attempt history.
- Analyze failures through an LLM when configured.
- Continue deterministic recovery if AI is unavailable.
- Expose useful REST APIs and monitoring metrics.
- Include automated tests, CI, migrations, documentation, and example configuration.
- Have a clear architecture diagram and demo scenarios.
- Be explainable by me in a backend engineering interview.

## Initial instruction

Do not write application code yet.

First, inspect the existing repository if one exists. Then provide:
1. A concise architecture overview.
2. A proposed directory structure.
3. The database entity relationships.
4. The job state machine.
5. A phased implementation plan with acceptance criteria.
6. The most important reliability risks and how to address them.
7. Prerequisites and exact setup commands for my operating system.

Wait for me to approve the plan before implementing Phase 1.

## Implementation prompts

After the coding assistant returns its architecture plan, use the prompts below one at a time. Don't paste all of them together.

Each prompt has a specific purpose and a checkpoint. If a checkpoint fails, fix it before advancing.

### Phase sequence

0. **Planning and architecture**  
   **Before implementation:** Use the master prompt above. Review and approve the architecture before coding.
1. **Environment and project scaffold** — Create the repository structure, Docker Compose setup, configuration, and initial application.  
   **Checkpoint:** API, PostgreSQL, and Redis start successfully.
2. **Database and job APIs** — Implement models, migrations, repositories, validation, and job CRUD.  
   **Checkpoint:** Jobs can be created and retrieved from PostgreSQL.
3. **Celery and recovery engine** — Implement execution, attempts, retries, backoff, idempotency, and dead-letter handling.  
   **Checkpoint:** Deliberately failing jobs recover correctly.
4. **AI diagnosis** — Add structured LLM analysis, failure categorization, and safe recommendations.  
   **Checkpoint:** Valid analysis is stored, and AI outages don't break recovery.
5. **Reliability and integration testing** — Test duplicate deliveries, worker crashes, outbox processing, and concurrent retries.  
   **Checkpoint:** Failure scenarios have reproducible tests.
6. **Monitoring and frontend** — Add metrics and a dashboard showing jobs, errors, analyses, and recovery history.  
   **Checkpoint:** Demonstrate the full lifecycle through the UI or API.
7. **Final polish and deployment** — Add CI, security checks, setup documentation, architecture diagrams, and demo instructions.  
   **Checkpoint:** A clean clone can be set up and tested by someone else.

## Prompt 1 — Set up the development environment

Use after approving the architecture.

Implement Phase 1 of RescueAI: project scaffolding and local development environment.

First inspect the approved architecture and the current repository. Preserve existing files that are correct.

### Tasks

1. Create the agreed Python package structure.
2. Configure Python 3.12, a virtual environment, dependency management, and pinned compatible dependencies.
3. Add FastAPI with a minimal application entry point.
4. Add SQLAlchemy configuration, PostgreSQL connection settings, Redis configuration, and Celery configuration placeholders.
5. Create Docker Compose services for PostgreSQL, Redis, and the FastAPI application.
6. Add environment-based configuration using Pydantic Settings.
7. Create `.env.example`, `.gitignore`, and a basic README.
8. Add Ruff configuration and a minimal pytest setup.
9. Add an API health endpoint and appropriate container health checks.
10. Ensure services depend on healthy infrastructure where practical, and implement application connection retries or clear startup failure behavior as appropriate.

Do not implement job recovery or AI analysis yet.

### Acceptance criteria

- The API starts locally.
- PostgreSQL and Redis are reachable from the application container.
- Configuration and secrets are not hardcoded.
- A health endpoint responds successfully.
- The repository has clear setup instructions.
- Basic tests and linting run successfully.

Show exact commands to build and start the stack, verify each service, run tests, and troubleshoot common errors. Report actual command results and any remaining limitations.

## Prompt 2 — Database models and REST APIs

Use only after Prompt 1 passes its checkpoint.

Implement Phase 2 of RescueAI: database persistence and job management APIs.

Inspect the existing project before modifying it. Reuse the current configuration and preserve working functionality.

### Implementation requirements

1. SQLAlchemy 2.x models for jobs, job attempts, failure analyses, recovery actions, audit events, and an outbox table if the approved design includes it.
2. UUID primary keys, UTC timestamps, JSONB payloads where appropriate, foreign keys, indexes, uniqueness constraints, and useful database constraints.
3. Alembic migrations for all implemented schema changes.
4. Pydantic request and response schemas with strict job-type validation.
5. A repository layer for database operations.
6. Service-layer functions for creating and retrieving jobs.
7. REST endpoints for creating jobs, listing jobs with pagination and filters, retrieving job details, and retrieving attempt history.
8. Consistent API error responses and correct HTTP status codes.
9. Unit and integration tests using PostgreSQL where appropriate.

New jobs should initially be persisted without requiring a working background execution flow. Do not implement retry behavior or AI calls yet.

### Acceptance criteria

- Migrations can be applied to a fresh database.
- Job records persist across API restarts.
- API responses do not expose sensitive internal fields.
- Invalid payloads are rejected.
- Duplicate idempotency keys are handled safely.
- Pagination, filtering, and database constraints are tested.
- All existing tests continue to pass.

Explain the entity relationships, indexes, transactions, and migration commands. Show actual test results.

## Prompt 3 — Celery worker and recovery engine

Use after jobs can be created and retrieved from PostgreSQL.

Implement Phase 3 of RescueAI: asynchronous job execution and deterministic failure recovery.

First inspect the existing models, repositories, API contracts, and configuration. Do not replace the existing architecture.

### Implementation requirements

1. A Celery application using Redis as the broker.
2. Separate worker startup instructions and Docker Compose configuration.
3. At least three simulated job types: API synchronization, ETL processing, and report generation.
4. Test scenarios that deliberately succeed, fail transiently, fail permanently, and exceed time limits.
5. A persistent execution-attempt lifecycle in PostgreSQL.
6. A validated job state machine with documented transitions.
7. Retry policies with maximum attempts, exponential backoff, jitter, and configurable limits.
8. Manual retry and cancellation request endpoints.
9. Idempotency protections for submissions and business operations.
10. Dead-letter handling for exhausted or non-retryable jobs.
11. A recovery mechanism for jobs left in an ambiguous or running state after worker interruption.
12. Structured logs containing job IDs and attempt identifiers.

Keep durable job state in PostgreSQL. Treat Redis/Celery delivery as potentially duplicated. Do not claim exactly-once execution.

Where the existing design needs atomic publication of database changes and queue messages, implement the transactional outbox pattern or document a justified incremental alternative. Never silently assume a database transaction can atomically commit a Redis enqueue.

### Acceptance criteria

- A successful job reaches SUCCEEDED.
- A transient failure is retried according to policy.
- A permanent failure is not retried indefinitely.
- Exhausted jobs reach the configured terminal failure state.
- Attempt history is durable.
- Repeated submissions and retry requests do not create unintended duplicate business effects.
- Worker crashes and recovery behavior are tested as far as practical.
- AI integration is not required for this phase.

Show the exact commands for starting the worker, submitting test jobs, observing retries, and verifying results in PostgreSQL. Run and report relevant tests.

## Prompt 4 — Integrate AI failure diagnosis

This is where the project becomes AI-powered. Use it after deterministic recovery is working.

Implement Phase 4 of RescueAI: AI-powered failure classification and root-cause analysis.

Inspect the existing recovery engine and database schema. Integrate AI without moving retry-policy enforcement into the LLM.

### Requirements

1. Create a dedicated AI service that calls the OpenAI API using the official supported Python SDK.
2. Read the API key and model configuration from environment variables.
3. Define Pydantic schemas for structured analysis containing failure category, probable cause, evidence, recommended action, confidence estimate, and human-approval requirement.
4. Send only sanitized, relevant error information, stack traces, and attempt history.
5. Enqueue AI analysis as a separate asynchronous task so it cannot block normal job processing.
6. Persist analysis results, timestamps, model metadata, and prompt version in PostgreSQL.
7. Handle timeouts, rate limits, malformed responses, unavailable services, and token or cost limits.
8. Add an API endpoint to request analysis and another to retrieve existing analysis.
9. Implement a deterministic fallback when AI is unavailable.
10. Allow developers or authorized users to provide feedback on a diagnosis.
11. Record whether a recommended recovery action was attempted and whether the job ultimately recovered.
12. Test the service using mocked AI responses, including invalid and malicious model output.

### Safety requirements

- The LLM must not execute arbitrary code, SQL, shell commands, or unrestricted remediation.
- Retry limits, permissions, idempotency checks, and allowed actions must be enforced by application code.
- AI confidence must not be presented as a calibrated probability without validation.
- Never expose secrets or sensitive customer information to the model.

### Acceptance criteria

- A failed job can receive a structured AI analysis.
- Analysis is stored and retrievable through the API.
- Invalid AI output is rejected safely.
- AI service outages do not prevent deterministic recovery.
- Tests verify that AI recommendations cannot bypass recovery policies.

Document the end-to-end data flow and explain which decisions are made by the LLM versus the deterministic recovery engine. Run and report the relevant tests.

## Prompt 5 — Reliability, integration testing, and edge cases

Use after the AI integration works. This is a particularly important phase for backend interviews.

Implement Phase 5 of RescueAI: reliability hardening and integration testing.

Audit the actual codebase first. Identify reliability gaps before changing code. Prioritize concrete bugs and failure modes over adding new features.

### Investigate and test

1. A worker crashes before executing a job.
2. A worker crashes while executing a job.
3. A job completes its external side effect but crashes before acknowledging completion.
4. A database commit succeeds but Redis publication fails.
5. A Redis message is delivered more than once.
6. Two clients request retry simultaneously.
7. A job remains RUNNING beyond its execution deadline.
8. PostgreSQL becomes temporarily unavailable.
9. Redis becomes temporarily unavailable.
10. The OpenAI API times out or returns invalid output.
11. A permanent error incorrectly appears retryable.
12. A job exhausts its retry budget.

### Potential fixes

- Transactional outbox processing and safe redelivery.
- Unique constraints and idempotency keys.
- Atomic state transitions and optimistic concurrency controls.
- Bounded retry policies, task time limits, and dead-letter handling.
- Recovery of stale jobs.
- Circuit breakers or rate limits where justified.
- Sanitized structured logs and correlation IDs.

Create integration tests that use real PostgreSQL and Redis services. Use controlled fault injection where practical. Do not depend only on mocked Celery calls.

For each scenario, document:

- Initial state.
- Failure point.
- Expected behavior.
- Observed behavior.
- Recovery mechanism.
- Remaining limitations.

### Acceptance criteria

- The system recovers or fails safely according to documented policy.
- Duplicate delivery does not produce unintended duplicate business effects for supported job types.
- Queue publication failures are recoverable.
- Concurrent retry requests are handled safely.
- All critical failure scenarios have reproducible tests.

Do not claim exactly-once execution. Explain the difference between at-least-once task delivery, idempotent business operations, and durable state transitions.

Run all relevant tests and report actual results.

## Prompt 6 — Metrics, dashboard, and user interface

Use once the backend and its core reliability tests are stable.

Implement Phase 6 of RescueAI: monitoring, metrics, and a frontend dashboard.

First inspect the existing API contracts and test suite. Do not change established API behavior without justification.

### Backend requirements

1. Add a metrics summary endpoint.
2. Provide job counts by status, retry counts, failure categories, recovery rate, and execution-duration summaries.
3. Define metric calculations precisely, including the observation window and denominator for recovery rate.
4. Add service health checks for FastAPI, PostgreSQL, and Redis.
5. Add structured logging and request/job correlation identifiers.
6. Avoid exposing sensitive payloads or secrets through metrics and logs.

### Frontend requirements

1. Build a React and TypeScript dashboard.
2. Show job totals, running jobs, failures, retrying jobs, and successful recoveries.
3. Provide a searchable, filterable job table.
4. Create a job detail page with attempt history and error information.
5. Display AI diagnosis, supporting evidence, recommended actions, and approval status.
6. Provide authorized manual retry and cancellation controls.
7. Show loading states, empty states, validation errors, and API failures.
8. Use a clear, professional interface suitable for a developer operations tool.

Use the existing backend rather than duplicating business logic in the frontend. Add or update tests for important frontend interactions and backend metrics.

### Acceptance criteria

- The dashboard displays actual API data.
- Filters and pagination work.
- Job details and attempt history are accurate.
- Manual actions handle errors without misleading success messages.
- Metrics are calculated consistently and documented.

Provide commands to start the frontend and backend and demonstrate a complete job lifecycle.

## Prompt 7 — Final polish, CI/CD, and GitHub readiness

Use after the complete application works locally.

Implement Phase 7 of RescueAI: final quality checks, CI/CD, security review, and portfolio documentation.

Inspect the full repository and run the available checks before making changes.

### Tasks

1. Review dependency versions and document supported runtime requirements.
2. Ensure configuration uses environment variables and provide a safe `.env.example`.
3. Verify secrets, local database files, and generated artifacts are excluded from Git.
4. Add or finalize GitHub Actions for linting, tests, and required checks.
5. Configure CI services or containers for PostgreSQL and Redis integration tests.
6. Run database migrations in the documented deployment process.
7. Add Docker build instructions and health checks.
8. Add appropriate authentication and authorization for privileged operations.
9. Review input validation, log redaction, retry limits, and API error handling.
10. Document local development, architecture, API endpoints, database entities, environment variables, and troubleshooting.
11. Create a Mermaid architecture diagram and a sequence diagram for failure recovery.
12. Provide sample API requests, expected responses, and demo scenarios.
13. Document known limitations, security considerations, and future improvements.
14. Provide a concise interview explanation of the architecture, key trade-offs, and failure scenarios.

### Acceptance criteria

- A new developer can clone the repository and follow the README to run the project.
- CI executes the required checks and reports failures correctly.
- Database migrations work on a clean environment.
- The complete demo can be reproduced from documented steps.
- All test and lint results are reported honestly.
- The repository contains no real secrets.
- The documentation distinguishes implemented features from planned features.

Do not claim deployment or production readiness unless it has actually been tested. Finish with a prioritized list of remaining issues and a checklist for publishing the repository.