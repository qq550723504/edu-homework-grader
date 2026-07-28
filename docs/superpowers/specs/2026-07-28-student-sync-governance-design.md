# Student Answer Sync Governance

**Issue:** #32
**Status:** Approved design
**Scope:** Student assignment answer synchronization only

## Goal

Keep a student's answer safe across a network interruption and page reload without
turning the browser into a second draft-management system.  The server remains
the authoritative answer store.  The existing tenant- and user-scoped IndexedDB
buffer is retained only for unsent answers and safe conflict display.

## Current root cause

The assignment page maps every save failure other than HTTP 409 to `offline`.
Consequently authorization, validation, rate-limit, and server failures can be
shown as a network outage and replayed without a valid recovery path.  It also
registers anonymous `online`, `offline`, and `visibilitychange` handlers, so it
cannot remove them when the page unmounts.

## Selected design

### Minimal local buffer

Keep the existing Dexie draft/outbox records keyed by tenant, user, attempt, and
item.  They retain the latest answer only so offline work survives a reload and
a 409 can show both versions.  Do not add a background worker, a durable retry
schedule, a draft browser UI, or new client dependencies.

The outbox result type gains stable categories for `offline`, `session_expired`,
`processing_blocked`, `validation_error`, `rate_limited`, `server_error`, and
`conflict`.  Only the durable answer and conflict counterpart are stored. Retry
countdown and in-flight request ownership stay in the mounted page's memory.

### Error handling and user interface

The page maps HTTP failures before calling the outbox:

- Network/no-response errors become `offline`; the latest answer remains queued
  and a later browser `online` event retries it.
- A 401 reloads `/api/auth/session` once. A renewed session retries the write;
  otherwise the page sends the student to the existing BFF login route while
  retaining the local buffer.
- A 403 stops processing and disables writes with a short instruction to contact
  the teacher or administrator.
- A 422 stops processing, shows only the stable public code or field message for
  the current item, and permits a subsequent edit to enqueue a replacement.
- A 429 honors `Retry-After` when present; otherwise it schedules bounded,
  jittered exponential retry in memory.
- A 5xx uses the same bounded in-memory retry. Exhaustion keeps the local answer
  and exposes one manual retry control.
- A 409 preserves the local answer and server answer/version, then presents two
  simple actions: use the server answer, or resend the local answer against the
  current server version. No automatic merge is attempted.

The normal UI remains one compact sync-status line. Extra controls appear only
for a blocked, exhausted, or conflict state; full answer contents are never
written to logs or telemetry.

### Lifecycle safety

Use named `online`, `offline`, and `visibilitychange` handlers. Register them on
mount and remove all three on unmount. Each mounted assignment page owns one
abort signal and retry timer; unmount clears the timer and aborts an in-flight
write so an old route cannot mutate the state of a new assignment page.

## Alternatives considered

1. Put all classification and retries directly in the Vue page. Rejected because
   the policy would be difficult to unit-test and easy to duplicate.
2. Use a Service Worker or full offline-sync library. Rejected because it expands
   cache, authentication, and lifecycle ownership beyond #32.
3. Persist a rich retry and draft state machine. Rejected because the user wants
   a simple frontend and the server is authoritative.

## Verification

Test first with Vitest:

- each HTTP/network category and its queue behavior;
- Retry-After and capped retry behavior without durable retry metadata;
- 401 renewed-session and failed-session paths;
- local/server conflict choices;
- listener removal and request cancellation on unmount.

Add focused Playwright coverage for offline recovery, 422 correction, 403
blocking, and leave/re-enter lifecycle behavior.  The test fixtures use only
synthetic answers and do not assert logging of student data.

## Non-goals

- No server API redesign or token-refresh endpoint;
- no three-way answer merge;
- no Service Worker, persistent retry scheduler, or draft-management screen;
- no automatic submission when a blocking category remains unresolved.
