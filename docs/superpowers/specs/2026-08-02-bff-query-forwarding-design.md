# BFF Query Forwarding Design

## Problem

The Web BFF route at `apps/web/server/api/core/[...path].ts` forwards only the
captured path to the Core API. It drops the incoming query string. As a result,
teacher review filters such as `reason=auto_confirmation` silently become an
unfiltered request, and the Core API's default policy excludes auto-confirmation
tasks.

## Decision

Preserve the request query string when constructing the upstream Core API URL.
The BFF will continue to own authentication and CSRF handling; it will not
inspect, transform, or authorize individual query parameters.

## Data Flow

1. The browser requests `/api/core/v1/review-tasks?reason=auto_confirmation`.
2. The BFF authenticates the session and forwards the same path and query
   string to `/v1/review-tasks?reason=auto_confirmation` on Core API.
3. Core API applies its existing `ReviewReason` filter and returns the task.

## Error Handling and Compatibility

Requests without a query string retain their existing upstream URL. Existing
request-header filtering, bearer-token injection, method forwarding, response
status propagation, and response-header handling are unchanged. The fix is
generic so every existing BFF GET or write endpoint with a query string gains
correct forwarding.

## Testing

Add a route-level regression test that invokes the BFF with
`reason=auto_confirmation` and asserts the upstream `fetch` URL retains that
query parameter. The test must first fail against the current implementation,
then pass after the minimal URL construction change. Run the focused Web test
file and the Web test suite before preparing the change for review.

## Out of Scope

Changing the Core API's review-default policy, modifying review-task data,
altering UI labels, or deploying to production are outside this repair.
