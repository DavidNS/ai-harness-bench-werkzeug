You are implementing one task of an approved plan, in a fresh session, inside an isolated
worktree. You can read and edit files but not run commands: the harness runs the tests for you
when you try to finish and gives you the result. Edits outside the files listed for this task are
rejected by a hook; do not work around it.

## Original request

Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and
`SharedDataMiddleware` on top of them, as upstream did in pallets/werkzeug PR #3308 (closes #3291).

Requirements:

1. `Response.apply_conditions(request, *, exists: bool = True) -> None` in
   `src/werkzeug/wrappers/response.py`: evaluate the request's precondition headers against the
   response's `etag` and `last_modified`, for all request methods, in the order and with the
   comparisons RFC 9110 specifies (`If-Match`, `If-Unmodified-Since`, `If-None-Match`,
   `If-Modified-Since`). A star ETag (`*`) is evaluated according to whether the resource exists
   (`exists`). A failed precondition raises `werkzeug.exceptions.PreconditionFailed`; a satisfied
   `If-None-Match` / `If-Modified-Since` on GET/HEAD turns the response into `304 Not Modified`
   with the entity headers removed as today. The method also sets `Accept-Ranges: bytes`.
2. `Response.apply_range(request) -> None`: apply the request's `Range` header after conditions.
   Only the `bytes` unit is supported; a too-large `stop` or suffix length is clamped to the
   complete length; when several ranges are given only the first is used; an unsatisfiable range
   raises `RequestedRangeNotSatisfiable`; a satisfiable one produces a `206 Partial Content`
   response with the sliced data and a `Content-Range` header.
3. `Response.make_conditional` keeps working but is deprecated (emits a `DeprecationWarning`)
   and is implemented through the two new methods. `werkzeug.http.is_resource_modified` and
   `is_byte_range_valid` are deprecated the same way; `Range.from_header`,
   `Range.make_content_range` and `ContentRange.from_header` validate their own values.
   `Range.make_content_range` clamps too-large `stop`/suffix values and uses the first range when
   several are given. Add `IfRange.check(etag, last_modified) -> bool` to the existing `IfRange`
   datastructure in `src/werkzeug/datastructures/range.py`: true when the request's `If-Range`
   condition is met by the response's values (a strong ETag equal to `etag`, or a date equal to
   `last_modified`), used by `apply_range` to decide whether a range may be applied.
   `ETagSet.from_header` discards invalid unquoted values.
4. `send_file` (`src/werkzeug/utils.py`) uses the new methods. It detects the name, size and
   modification time from file-like objects when possible, calls `seek(0)` on file-like objects so
   range responses report correct complete and content lengths (and sending an already-read file
   works), no longer includes a hash of the path in the ETag, and defaults to the
   `application/octet-stream` mimetype when `download_name` is not passed instead of raising.
5. `SharedDataMiddleware` (`src/werkzeug/middleware/shared_data.py`) serves files through
   `send_file`. `cache_timeout` is no longer set by default so conditional caching works. Its
   `cache` and `fallback_mimetype` parameters are deprecated (still accepted, with a
   `DeprecationWarning`).
6. Document the new methods in the quickstart docs and add a changelog entry; keep the public
   import paths and everything not listed above unchanged.

Tests: add tests for `apply_conditions` (each precondition header, method coverage, star ETag with
and without an existing resource, 304 vs 412) and `apply_range` (first range only, clamping,
unsatisfiable, 206 with correct `Content-Range`); update the `send_file` tests for the new
detection, seek, ETag and mimetype behaviour; move or remove the existing tests of the deprecated
functions accordingly. The suite runs with `pytest -m "not dev_server"` and must stay green.

## Plan summary

Add the new capabilities first (datastructures, then Response.apply_conditions/apply_range), migrate send_file and then SharedDataMiddleware onto them, and only then deprecate make_conditional, is_resource_modified and is_byte_range_valid (so no internal caller emits the warnings). Docs and changelog come last. Datastructures stop importing is_byte_range_valid in the first task so the later deprecation is safe.

## Your task: T2 (T2_response_methods)

Add Response.apply_conditions and Response.apply_range in wrappers/response.py (make_conditional left untouched for now) with new tests for headers, methods, star ETag, 304 vs 412, and range slicing/clamping/unsatisfiable.

Acceptance criteria this task must satisfy:
- ACC4 [behavior]: apply_conditions evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order, for all request methods; failed If-Match/If-Unmodified-Since (and If-None-Match on non-GET/HEAD) raise PreconditionFailed.
- ACC5 [behavior]: A satisfied If-None-Match or If-Modified-Since on GET/HEAD turns the response into 304 with entity headers removed; on other methods it raises PreconditionFailed (412).
- ACC6 [behavior]: A star ETag in If-Match/If-None-Match is evaluated by the exists argument: If-Match * fails when exists=False; If-None-Match * fails/304 when exists=True and passes when exists=False.
- ACC7 [behavior]: apply_conditions sets Accept-Ranges: bytes.
- ACC8 [behavior]: apply_range with a satisfiable bytes Range produces 206, sliced data, correct Content-Length and Content-Range; only the first range is used; too-large stop/suffix is clamped to complete length.
- ACC9 [behavior]: apply_range raises RequestedRangeNotSatisfiable for an unsatisfiable range; non-bytes units are ignored; If-Range not matching (via IfRange.check) skips range handling and leaves a 200.

Files you may edit (anything else is blocked):
- src/werkzeug/wrappers/response.py (production, modify)
- tests/test_wrappers.py (test, modify)

Tests that must pass when you finish: tests/test_wrappers.py

## Rules

- Write or update the tests listed above so that they fail without your production change and
  pass with it. The harness verifies this against the base commit: a test that also passes
  without the change does not count.
- Do not modify existing tests other than the ones listed for this task.
- Do not add features, docs or refactors the task does not ask for.
- If the task cannot be done without touching a file that is not listed, or a criterion is
  impossible as written, do not improvise: stop and return `replan_request` with the reason and the
  files you need. That re-plans instead of failing you.


## Final answer

Return JSON matching the schema you were given: a short `summary`, one `criteria_notes` entry per
criterion with the test that proves it, and `replan_request` (`null` unless you need a re-plan).
