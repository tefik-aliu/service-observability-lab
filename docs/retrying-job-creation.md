# A saved job, a lost response

A client sends a job creation request. The database commits, then the network
drops the response. Retrying a normal POST creates a second job. This API lets
the client identify the operation so a retry can recover the creation receipt.

## API contract

```sh
curl http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: report-request-1' \
  -d '{"title":"Generate weekly report"}'
```

Repeat the command: both responses are 201 with the same JSON body and job ID.
`Idempotency-Replayed: true` identifies the retry; the first response says
`false`. Only the first request increments the jobs-created counter.

- Keys accept 1–128 ASCII letters, digits, underscores or hyphens. Generate a
  new random key for each new operation. Never include personal data in keys.
- The same key and normalized title replay the original creation receipt.
  Titles are trimmed; unknown body fields are rejected.
- The same key with a different title returns 409 without inserting a job.
- Invalid input returns 422 without reserving the key.
- The header is optional for existing API clients. Without it, each POST
  intentionally creates a new job, even when titles match.

## Database boundary

The `job_requests` table reserves the key using a primary-key constraint. The
reservation, job and JSON receipt commit in one transaction. Competing requests
are arbitrated by the database, not a process-local lock. After a duplicate-key
failure, the session rolls back and reads the committed receipt. Other database
errors propagate; they are not silently treated as replays.

Startup adds the new table through `create_all`; existing job columns and rows
are unchanged. This is an additive change, not a general migration framework.
Receipts persist across app restarts and job changes. They are intentionally
retained after deletion: a retry returns the historical creation response and
never resurrects the job. Use GET `/api/jobs` for current state.

## Browser behaviour

The form retains its operation key after an uncertain response and offers
**Retry save**. No automatic retry is performed. An unchanged title uses the
same key; another title starts a new operation and explains the uncertainty.
The form disables submission during an active request and only clears after a
successful JSON response. Job titles are rendered with `textContent`.

The key is kept in memory only. Reloading or closing the page loses the pending
operation; inspect the job list before creating it again. API integrations
should persist their own keys across retries. This is a single-workspace demo:
keys have no user/tenant scope and receipts have no expiry or cleanup policy.
Adding authentication, retention and operational limits is necessary before
using this design in a real service. The application stores job states; it does
not execute background work or guarantee exactly-once external side effects.

## Reproduce the checks

```sh
python -m pytest
npm run typecheck
BASE_URL=http://localhost:8000 npm run test:e2e
```

`tests/test_idempotency.py` covers races, conflicting payloads, rollback,
restart, update/deletion, old clients, validation and existing databases.
By default it uses file-backed SQLite. Set `TEST_POSTGRES_URL` to a test
PostgreSQL instance to run the same contract there. Each test creates and drops
only its own random schema. CI runs this against PostgreSQL 16.

`qa/service.spec.ts` lets the server commit a browser request, discards its
response, then checks that an explicit retry uses the same key and leaves one
job. Another check ensures HTML-looking titles remain inert text on mobile.
