## Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and

### Plan

One PR: add Response.apply_conditions/apply_range and IfRange.check, validate in the http datastructures, deprecate make_conditional/is_resource_modified/is_byte_range_valid, rebuild send_file and SharedDataMiddleware on them, with docs, changelog and tests. Docs and changelog are required by INTENT8. A single task fits because the pieces depend on each other and ship together.

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

### Intents

- `INTENT1` Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py that evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, treats a star ETag according to `exists`, raises PreconditionFailed on failure, turns satisfied If-None-Match/If-Modified-Since on GET/HEAD into 304 with entity headers removed, and sets Accept-Ranges: bytes. (change)
- `INTENT2` Add Response.apply_range(request) that always sets Accept-Ranges: bytes, applies Range only for GET with a 200 response and known non-zero Content-Length (otherwise leaves the response unchanged), supports only bytes, clamps too-large stop/suffix, uses only the first range, raises RequestedRangeNotSatisfiable when unsatisfiable, returns 206 with sliced data and Content-Range, and honors If-Range. (change)
- `INTENT3` Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py, true for a strong ETag equal to etag or a date equal to last_modified, and use it in apply_range. (change)
- `INTENT4` Keep Response.make_conditional working but deprecated with DeprecationWarning, implemented via apply_conditions and apply_range, and deprecate werkzeug.http.is_resource_modified and is_byte_range_valid the same way. (change)
- `INTENT5` Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix and uses the first range when several are given; ETagSet.from_header discards invalid unquoted values. (change)
- `INTENT6` Refactor send_file in utils.py to use the new methods, detect name/size/mtime from file-like objects when possible, call seek(0) on file-like objects, drop the path hash from the ETag, and default to application/octet-stream when download_name is not passed instead of raising. (change)
- `INTENT7` Make SharedDataMiddleware serve files through send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) its cache and fallback_mimetype parameters. (change)
- `INTENT8` Document the new methods in the quickstart docs and add a changelog entry. (change)
- `INTENT9` Add tests for apply_conditions (each header, method coverage, star ETag with/without resource, 304 vs 412) and apply_range (first range only, clamping, unsatisfiable, 206 with correct Content-Range); update send_file tests for detection, seek, ETag and mimetype behaviour; move or remove tests of the deprecated functions; suite must pass with pytest -m "not dev_server". (change)

### Criteria, tests and results

| Criterion | Kind | Task | Test(s) | Result |
|---|---|---|---|---|
| ACC1 | behavior | T1 | `tests/test_wrappers.py::test_apply_conditions` (covered) | committed |
| ACC2 | behavior | T1 | `tests/test_wrappers.py::test_apply_conditions_star_etag_exists` (covered) | committed |
| ACC3 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_ignored` (covered) | committed |
| ACC4 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_clamp_first` (covered) | committed |
| ACC5 | behavior | T1 | `tests/test_datastructures.py::test_if_range_check_etag` (covered) | committed |
| ACC6 | behavior | T1 | `tests/test_http.py::TestHTTPUtility::test_is_byte_range_valid_deprecated` (covered) | committed |
| ACC7 | behavior | T1 | `tests/test_datastructures.py::test_make_content_range` (covered) | committed |
| ACC8 | behavior | T1 | `tests/test_send_file.py::test_object_seeks_to_start` (covered) | committed |
| ACC9 | behavior | T1 | `tests/middleware/test_shared_data.py::test_conditional_request` (covered) | committed |
| ACC10 | other | T1 | tests/middleware/test_shared_data.py, tests/test_datastructures.py, tests/test_http.py, tests/test_send_file.py, tests/test_wrappers.py | committed |
| ACC11 | behavior | T1 | `tests/test_wrappers.py::test_apply_conditions` (covered) | committed |

### Tasks

- `T1` Order of work: (1) add IfRange.check and the validation/clamping in range.py and ETagSet.from_header; (2) add apply_conditions and apply_range to Response; (3) move send_file and SharedDataMiddleware onto them and update their tests; (4) last, deprecate make_conditional (reimplemented on the new methods), is_resource_modified and is_byte_range_valid, and drop internal callers of the deprecated functions. Then update the docs and changelog, and move or remove the old tests or wrap them in pytest.warns, since the suite may turn warnings into errors. (1 attempt(s), commit `465ff3533a`)
  - reviewer note [pass 2] `tests/test_datastructures.py:1080`: No test passes a timezone-naive `last_modified` to `IfRange.check` when the `If-Range` date is aware. The `==` comparison would raise TypeError for that input.
  - reviewer note [pass 2] `tests/test_wrappers.py:900`: No `apply_range` test sends `If-Range` with a weak response ETag, or `If-Range` with a matching date plus a mismatched ETag.
  - reviewer note [pass 3] `tests/test_http.py:406`: The detailed `is_resource_modified` tests, including the `If-Range` cases, were replaced by two smoke tests. This is allowed by the task, but the behaviour of the deprecated function is now barely checked.
  - reviewer note [pass 4] `src/werkzeug/wrappers/response.py:840`: The deprecated `make_conditional` carries a long special-case block that re-implements the malformed-Range check, plus nested `if complete_length` branches. This could be simplified.
  - reviewer note [pass 4] `src/werkzeug/middleware/shared_data.py:315`: Mutating `rv.cache_control.no_cache`/`public` after `send_file` for the deprecated `cache=False` path is a hack. The `cache=False` path could instead be built from the `send_file` arguments.

### Gate failures along the way

- review.approved (T1, attempt 1): review.changes_requested

### Cost (client-side estimate)

- sessions: 6; turns: 128; USD: 3.60; attempts: 1

_Generated by aih run `20261014T122746Z-dfb176`._
