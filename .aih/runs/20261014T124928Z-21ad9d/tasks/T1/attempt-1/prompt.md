You are implementing one task of an approved plan inside an isolated worktree. You can read and
edit files. The only command you can run is `aih check <test files...>`, which runs those tests
(or `aih check --build`, which only compiles, when the project has a build step): use it as often
as you need; every other shell command is rejected. When you try to finish, the harness runs the
task's tests again and gives you the result. Edits outside the files listed for this task are
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
   It always advertises `Accept-Ranges: bytes` on the response, even when no range is applied.
   Ranges are applied only to `GET` requests with a `200` response and a known, non-zero complete
   length (`Content-Length`); for any other method, status or an unknown/zero length the response
   is left unchanged (no `206`, no `416`). Only the `bytes` unit is supported; a too-large `stop`
   or suffix length is clamped to the complete length; when several ranges are given only the
   first is used; an unsatisfiable range raises `RequestedRangeNotSatisfiable`; a satisfiable one
   produces a `206 Partial Content` response with the sliced data and a `Content-Range` header.
   If the request carries `If-Range`, the range is applied only when the condition matches the
   response's ETag (strong comparison) or `Last-Modified`.
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



## Your task: T1 (T1)

Add apply_conditions/apply_range and IfRange.check, fix Range/ETagSet validation, then migrate send_file and SharedDataMiddleware and their tests, and deprecate make_conditional/is_resource_modified/is_byte_range_valid last (internal callers must stop using them first since warnings may be errors). Update docs and changelog.

Acceptance criteria this task must satisfy:
- ACC1 [behavior]: apply_conditions raises PreconditionFailed for failed If-Match/If-Unmodified-Since on any method, and for If-None-Match matches on non-GET/HEAD; evaluates in RFC order; star ETag honors exists.
- ACC2 [behavior]: apply_conditions turns the response into 304 with entity headers removed when If-None-Match/If-Modified-Since is satisfied on GET/HEAD, and sets Accept-Ranges: bytes.
- ACC3 [behavior]: apply_range always sets Accept-Ranges: bytes; leaves response unchanged for non-GET, non-200, or unknown/zero Content-Length.
- ACC4 [behavior]: apply_range uses only the first range, clamps too-large stop/suffix, raises RequestedRangeNotSatisfiable when unsatisfiable, else 206 with sliced data and correct Content-Range; ignores non-bytes units.
- ACC5 [behavior]: apply_range honors If-Range by strong ETag or Last-Modified match, otherwise returns the full response.
- ACC6 [behavior]: make_conditional, is_resource_modified and is_byte_range_valid emit DeprecationWarning and still work.
- ACC7 [behavior]: Range.make_content_range clamps too-large stop and suffix, uses first range, validates without is_byte_range_valid; from_header methods reject invalid values; ETagSet.from_header discards unquoted values.
- ACC8 [behavior]: IfRange.check returns True for matching strong ETag or equal date, False otherwise.
- ACC9 [behavior]: send_file detects name/size/mtime from file-likes, seeks to 0, ETag has no path hash, and defaults to application/octet-stream without download_name.
- ACC10 [behavior]: SharedDataMiddleware serves via send_file, sets no max-age by default, supports conditional and range requests, and warns when cache or fallback_mimetype is passed.
- ACC11 [other]: Quickstart documents apply_conditions and apply_range; CHANGES.rst has an entry.
- ACC12 [behavior]: New tests cover apply_conditions and apply_range; send_file tests updated; deprecated-function tests moved/removed; pytest -m 'not dev_server' passes.

Files you may edit (anything else is blocked):
- src/werkzeug/wrappers/response.py (production, modify)
- src/werkzeug/http.py (production, modify)
- src/werkzeug/sansio/http.py (production, modify)
- src/werkzeug/datastructures/range.py (production, modify)
- src/werkzeug/datastructures/etag.py (production, modify)
- src/werkzeug/utils.py (production, modify)
- src/werkzeug/middleware/shared_data.py (production, modify)
- docs/quickstart.rst (production, modify)
- docs/http.rst (production, modify)
- CHANGES.rst (production, modify)
- tests/test_wrappers.py (test, modify)
- tests/test_http.py (test, modify)
- tests/test_send_file.py (test, modify)
- tests/middleware/test_shared_data.py (test, modify)
- tests/test_datastructures.py (test, modify)

Tests that must pass when you finish: tests/test_wrappers.py, tests/test_http.py, tests/test_send_file.py, tests/middleware/test_shared_data.py, tests/test_datastructures.py

## Rules

- Write or update the tests listed above so that they fail without your production change and
  pass with it. The harness verifies this against the base commit: a test that also passes
  without the change does not count.
- Every branch you add (a new `if`/`else`, an `except`, an early return, a new error status)
  must be exercised by a test in this task's test files before you finish. An independent
  reviewer blocks the task for each new branch without a test; write them first.
- Do not modify existing tests other than the ones listed for this task.
- Do not add features, docs or refactors the task does not ask for.
- If the task cannot be done without touching a file that is not listed, or a criterion is
  impossible as written, do not improvise: stop and return `replan_request` with the reason and the
  files you need. That re-plans instead of failing you.

## Final answer

Return JSON matching the schema you were given: a short `summary`, one `criteria_notes` entry per
criterion with the test that proves it, and `replan_request` (`null` unless you need a re-plan).
