## Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and

> **Run ABORTED.** This branch holds what was committed before the run stopped, plus the run's artifacts. It is evidence, not a finished change.
>
> `run.aborted`: review.changes_requested: the reviewer requests changes:

### Plan

Add the new capabilities first (datastructures, then Response.apply_conditions/apply_range), migrate send_file and then SharedDataMiddleware onto them, and only then deprecate make_conditional, is_resource_modified and is_byte_range_valid (so no internal caller emits the warnings). Docs and changelog come last. Datastructures stop importing is_byte_range_valid in the first task so the later deprecation is safe.

### Request

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

### Intents

- `INTENT1` Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py that evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, treats a star ETag according to `exists`, raises PreconditionFailed on failure, converts satisfied If-None-Match/If-Modified-Since on GET/HEAD to 304 with entity headers removed, and sets Accept-Ranges: bytes. (change)
- `INTENT2` Add Response.apply_range(request) that applies the Range header after conditions: bytes only, clamps too-large stop/suffix, uses only the first range, raises RequestedRangeNotSatisfiable when unsatisfiable, otherwise produces 206 with sliced data and Content-Range, honoring If-Range via IfRange.check. (change)
- `INTENT3` Keep Response.make_conditional working but deprecated (DeprecationWarning), implemented via apply_conditions and apply_range; deprecate werkzeug.http.is_resource_modified and is_byte_range_valid the same way. (change)
- `INTENT4` Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix and uses the first range when several are given. (change)
- `INTENT5` Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py, true when a strong ETag equals etag or the date equals last_modified. (change)
- `INTENT6` Make ETagSet.from_header discard invalid unquoted values. (change)
- `INTENT7` Refactor send_file in utils.py to use apply_conditions/apply_range, detect name, size and mtime from file-like objects when possible, call seek(0) on file-like objects, drop the path hash from the ETag, and default to application/octet-stream when download_name is not given instead of raising. (change)
- `INTENT8` Make SharedDataMiddleware serve files through send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) the cache and fallback_mimetype parameters. (change)
- `INTENT9` Document the new methods in the quickstart docs and add a changelog entry. (change)
- `INTENT10` Add tests for apply_conditions (each header, methods, star ETag with/without resource, 304 vs 412) and apply_range (first range only, clamping, unsatisfiable, 206 with correct Content-Range); update send_file tests for detection, seek, ETag and mimetype changes; move or remove tests of deprecated functions so `pytest -m "not dev_server"` stays green. (change)

### Criteria, tests and results

| Criterion | Kind | Task | Test(s) | Result |
|---|---|---|---|---|
| ACC1 | behavior | T1 | tests/test_datastructures.py, tests/test_http.py | committed |
| ACC2 | behavior | T1 | tests/test_datastructures.py, tests/test_http.py | committed |
| ACC3 | behavior | T1 | tests/test_datastructures.py, tests/test_http.py | committed |
| ACC4 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC5 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC6 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC7 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC8 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC9 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC10 | behavior | T5 | tests/test_http.py, tests/test_wrappers.py | pending |
| ACC11 | behavior | T3 | tests/test_send_file.py | committed |
| ACC12 | behavior | T3 | tests/test_send_file.py | committed |
| ACC13 | behavior | T4 | tests/middleware/test_shared_data.py | pending |
| ACC14 | behavior | T4 | tests/middleware/test_shared_data.py | pending |
| ACC15 | other | T6 | - | pending |

### Tasks

- `T1` Add IfRange.check, make Range/ContentRange parsing and make_content_range self-validating with clamping and first-range use (no longer importing is_byte_range_valid), and make ETagSet.from_header discard invalid unquoted values. Add tests. (2 attempt(s), commit `6896bf8a82`)
  - reviewer note [pass 4] `tests/test_http.py:825`: The `test_content_range_invalid_int` parametrize line was rewritten without a space after a comma (`"*/🯱🯲🯳","1-+2/3"`), which is formatting noise that `ruff format` would reject; restore the original line.
  - reviewer note [pass 2] `tests/test_datastructures.py:1`: No test covers `IfRange.check` with a naive `last_modified` datetime (assumed UTC) or with a non-bytes unit passed to `make_content_range`.
- `T2` Add Response.apply_conditions and Response.apply_range in wrappers/response.py (make_conditional left untouched for now) with new tests for headers, methods, star ETag, 304 vs 412, and range slicing/clamping/unsatisfiable. (2 attempt(s), commit `bb7c6287d6`)
  - reviewer note [pass 2] `tests/test_wrappers.py:930`: No test runs apply_range on a streamed response whose length is unknown, or on a file-wrapper or direct_passthrough response, which is the path send_file will use. The `calculate_content_length()` returning None branch is untested.
  - reviewer note [pass 2] `tests/test_wrappers.py:790`: Several edge cases have no test: a weak ETag in If-Range, a last_modified with microseconds (the `replace(microsecond=0)` normalisation), and malformed date headers.
- `T3` Refactor send_file to use apply_conditions/apply_range, detect name/size/mtime from file-like objects, seek(0), drop path hash from the ETag, and default to application/octet-stream. Update send_file tests. (2 attempt(s), commit `4d4b28a357`)
  - reviewer note [pass 4] `src/werkzeug/utils.py:455`: The `size = None` in the except branch of the seek-to-end fallback is redundant if `size` is already initialised to None earlier in the function. The size-detection ladder could also be a small helper.
  - reviewer note [pass 2] `tests/test_send_file.py:0`: No test covers a file-like object that has a `fileno` but is not a regular file, such as a pipe. The `S_ISREG` guard and the seek-based size fallback are therefore unexercised for it.
- `T4` Serve SharedDataMiddleware files through send_file, drop the default cache_timeout, and deprecate the cache and fallback_mimetype parameters. Update middleware tests. (2 attempt(s), commit ``)
  - reviewer note [pass 2] `tests/middleware/test_shared_data.py:43`: There is no test for If-Modified-Since / Last-Modified revalidation, for HEAD requests, or for a file served from a package loader (`generate_etag` and the BytesIO opener). Only the filesystem If-None-Match path is covered.
  - reviewer note [pass 1] `src/werkzeug/middleware/shared_data.py:293`: With `cache=False`, `etag=False` still lets send_file set Last-Modified and apply conditions. The old code sent only `Cache-Control: public` and never returned 304. The new behavior is arguably fine for a deprecated option, but it is untested.
- `T5` Deprecate Response.make_conditional (reimplemented via apply_conditions/apply_range), http.is_resource_modified and is_byte_range_valid; move or remove their old tests and migrate remaining make_conditional uses in tests to expect the warning. (0 attempt(s), commit ``)
- `T6` Document apply_conditions/apply_range in the quickstart and add a changelog entry. (0 attempt(s), commit ``)

### Gate failures along the way

- tests.red_proven (T1, attempt 1): tests.red_not_proven
- review.approved (T2, attempt 1): review.changes_requested
- review.approved (T3, attempt 1): review.changes_requested
- review.approved (T4, attempt 1): review.changes_requested
- review.approved (T4, attempt 2): review.changes_requested

### Cost (client-side estimate)

- sessions: 20; turns: 193; USD: 3.05; attempts: 8

_Generated by aih run `20261012T194727Z-6cbba8`._
