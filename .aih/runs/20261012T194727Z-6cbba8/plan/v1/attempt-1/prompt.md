You are planning a change in this repository. You can read files but not edit them or run
commands. Another session will implement your plan, one task at a time, in a fresh context, and a
harness will check the result against it mechanically. Explore the repository as you see fit;
only your final JSON answer is used.

## Request

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

## Intents (use these ids exactly)

- `INTENT1` (apply-conditions): Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py that evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, treats a star ETag according to `exists`, raises PreconditionFailed on failure, converts satisfied If-None-Match/If-Modified-Since on GET/HEAD to 304 with entity headers removed, and sets Accept-Ranges: bytes.
- `INTENT2` (apply-range): Add Response.apply_range(request) that applies the Range header after conditions: bytes only, clamps too-large stop/suffix, uses only the first range, raises RequestedRangeNotSatisfiable when unsatisfiable, otherwise produces 206 with sliced data and Content-Range, honoring If-Range via IfRange.check.
- `INTENT3` (deprecate-make-conditional): Keep Response.make_conditional working but deprecated (DeprecationWarning), implemented via apply_conditions and apply_range; deprecate werkzeug.http.is_resource_modified and is_byte_range_valid the same way.
- `INTENT4` (http-datastructure-validation): Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix and uses the first range when several are given.
- `INTENT5` (ifrange-check): Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py, true when a strong ETag equals etag or the date equals last_modified.
- `INTENT6` (etagset-invalid): Make ETagSet.from_header discard invalid unquoted values.
- `INTENT7` (send-file-refactor): Refactor send_file in utils.py to use apply_conditions/apply_range, detect name, size and mtime from file-like objects when possible, call seek(0) on file-like objects, drop the path hash from the ETag, and default to application/octet-stream when download_name is not given instead of raising.
- `INTENT8` (shared-data-refactor): Make SharedDataMiddleware serve files through send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) the cache and fallback_mimetype parameters.
- `INTENT9` (docs-changelog): Document the new methods in the quickstart docs and add a changelog entry.
- `INTENT10` (tests): Add tests for apply_conditions (each header, methods, star ETag with/without resource, 304 vs 412) and apply_range (first range only, clamping, unsatisfiable, 206 with correct Content-Range); update send_file tests for detection, seek, ETag and mimetype changes; move or remove tests of deprecated functions so `pytest -m "not dev_server"` stays green.

## Constraints

- Keep public import paths unchanged
- Leave everything not listed in the request unchanged
- Test suite must pass with pytest -m "not dev_server"

## Repository facts

- Test files are those matching: tests/**/*.py
- Tests are run by the harness, not by the implementer.


## What the plan must contain

Return JSON matching the schema you were given.

- `intents`: every intent id above, exactly once, with a `resolution`:
  - `change`: something must change. `evidence` is optional but welcome.
  - `already_satisfied`: the repository already does it. Requires `evidence` that proves it.
  - `out_of_scope`: you propose not doing it. Requires a `rationale`; a human will decide.
- `evidence`: `path` relative to the repository root, `start`/`end` line numbers (1-based,
  inclusive) and a short `quote` that appears literally within those lines. The harness checks
  the file, the range and the quote; a wrong quote fails the plan.
- `criteria`: acceptance criteria, each tied to an `intent`. `kind` is `behavior` when a test
  can prove it, `other` otherwise (documentation, naming). Write them so that a test can be
  named for each `behavior` criterion.
- `tasks`: the units of work. Each task must fit a single short session with a fresh context:
  - `files`: every file the task may touch, with `role` (`test` if it matches the test globs,
    `production` otherwise) and `action`. The implementer is blocked from touching anything
    else. Declaring a file you will not need is cheap; forgetting one costs a replan.
  - `tests`: the test files (existing or to be created) that prove this task's criteria. Every
    `behavior` criterion must be covered by at least one task with at least one test. **Every
    path in `tests` must also appear in that task's `files`** (with `role: test`); a test path
    missing from `files` fails the plan.
  - `criteria`: the criteria keys this task satisfies.
  - `depends_on`: keys of tasks that must be committed first. No cycles.
  - Split the work into tasks along real dependencies: a change that several other changes build
    on (a signature, a new method, a data structure) goes first as its own task, and the tasks that
    rely on it declare it in `depends_on`. Two tasks may touch the same production file only when
    one depends on the other; independent tasks must not share a production file. A small change
    that fits one session stays one task; do not split for the sake of splitting.
  - Order by dependency, not by topic: a deprecation, removal or behaviour change of something
    that other code still calls must come **after** the tasks that migrate those callers (and
    their tests), or the suite goes red (many suites turn warnings into errors). Add the new
    thing first, migrate its users next, deprecate the old thing last.
  - Existing tests that assert the old behaviour must be listed in the `files` (role `test`) and
    `tests` of the task that changes that behaviour; the implementer is blocked from touching any
    test file the task does not declare.
- `summary` on the plan and on each task: one or two sentences for a human reviewer.

Do not include anything the user did not ask for (docs, refactors, extra features) unless an
intent requires it; if you think it is needed, say so in the plan summary instead.
