## Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and

### Plan

Add the new datastructure helpers first, then the two new Response methods, migrate send_file and SharedDataMiddleware onto them, and only then deprecate make_conditional and the http helpers (warnings are errors in the test config). Docs and changelog come last.

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

- `INTENT1` Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py evaluating If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, with star ETag depending on `exists`, raising PreconditionFailed on failure, producing 304 (entity headers removed) for satisfied If-None-Match/If-Modified-Since on GET/HEAD, and setting Accept-Ranges: bytes. (change)
- `INTENT2` Add Response.apply_range(request) applying only the bytes Range after conditions (honouring If-Range via IfRange.check), clamping too-large stop/suffix, using only the first range, raising RequestedRangeNotSatisfiable when unsatisfiable, else a 206 with sliced data and Content-Range. (change)
- `INTENT3` Keep Response.make_conditional working but emit DeprecationWarning, implemented via apply_conditions and apply_range. (change)
- `INTENT4` Deprecate werkzeug.http.is_resource_modified and is_byte_range_valid with DeprecationWarning. (change)
- `INTENT5` Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix and uses the first range when several are given. (change)
- `INTENT6` Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py, true for a strong ETag equal to etag or a date equal to last_modified. (change)
- `INTENT7` Make ETagSet.from_header discard invalid unquoted values. (change)
- `INTENT8` Refactor send_file in utils.py to use the new methods: detect name/size/mtime from file-like objects when possible, seek(0) file-likes, drop the path hash from the ETag, and default mimetype to application/octet-stream when download_name is absent instead of raising. (change)
- `INTENT9` Make SharedDataMiddleware serve files through send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) the cache and fallback_mimetype parameters. (change)
- `INTENT10` Document the new methods in the quickstart docs and add a changelog entry. (change)
- `INTENT11` Add tests for apply_conditions (each header, methods, star ETag with/without resource, 304 vs 412) and apply_range (first range only, clamping, unsatisfiable, 206 Content-Range); update send_file tests for new behaviour; move/remove tests of deprecated functions; suite `pytest -m "not dev_server"` stays green. (change)

### Criteria, tests and results

| Criterion | Kind | Task | Test(s) | Result |
|---|---|---|---|---|
| ACC1 | behavior | T1 | tests/test_datastructures.py | committed |
| ACC2 | behavior | T1 | tests/test_datastructures.py | committed |
| ACC3 | behavior | T1 | tests/test_datastructures.py | committed |
| ACC4 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC5 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC6 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC7 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC8 | behavior | T2 | tests/test_wrappers.py | committed |
| ACC9 | behavior | T3 | tests/test_send_file.py | committed |
| ACC10 | behavior | T4 | tests/middleware/test_shared_data.py | committed |
| ACC11 | behavior | T5 | tests/test_http.py, tests/test_wrappers.py | committed |
| ACC12 | behavior | T5 | tests/test_http.py, tests/test_wrappers.py | committed |
| ACC13 | other | T6 | - | committed |
| ACC14 | behavior | T5 | tests/test_http.py, tests/test_wrappers.py | committed |

### Tasks

- `T1` Add IfRange.check, make Range/ContentRange validate themselves without http.is_byte_range_valid (clamping, first range), and make ETagSet.from_header drop invalid unquoted values. (1 attempt(s), commit `b90dee1ca0`)
  - reviewer note [pass 2] `tests/test_datastructures.py:1159`: ACC2 says Range.from_header and ContentRange.from_header validate their own values, but this task adds no test for that (for example a ContentRange with stop >= length, or a Range with begin >= end); they may be covered elsewhere.
  - reviewer note [pass 1] `src/werkzeug/datastructures/etag.py:301`: ACC3 required no production change, because ETagSet.from_header already discards invalid items. The new test only locks in that existing behavior, and the declared etag.py is untouched.
- `T2` Add Response.apply_conditions and Response.apply_range (leave make_conditional untouched for now), with tests. (1 attempt(s), commit `23f5685d75`)
  - reviewer note [pass 2] `tests/test_wrappers.py:790`: No test covers If-Match or If-None-Match against a response with no etag set, or an If-None-Match list with several tags.
  - reviewer note [pass 2] `tests/test_wrappers.py:956`: apply_range tests for a zero-length body and for a direct_passthrough iterable with a known Content-Length only assert headers, not that the sliced body data is correct.
- `T3` Refactor send_file onto apply_conditions/apply_range with file-like detection, seek(0), no path hash in ETag, octet-stream default; update send_file tests. (1 attempt(s), commit `9323dd3c17`)
  - reviewer note [pass 2] `tests/test_send_file.py:0`: No test sends a real file with a `Range` header and an `If-Range` header, or a file-like with a mtime and `If-Modified-Since`. Also untested: a non-seekable file-like, where the new unconditional `file.seek(0)` now raises instead of sending the stream.
  - reviewer note [pass 4] `src/werkzeug/utils.py:536`: `except Exception` is broader than the old `except RequestedRangeNotSatisfiable`. It is needed to close the file on `PreconditionFailed`, but it also covers unrelated errors; `except BaseException` or a `try/finally` would be the more conventional choice.
- `T4` Serve SharedDataMiddleware files through send_file, drop default cache_timeout, deprecate cache and fallback_mimetype params; update its tests. (1 attempt(s), commit `84689c09db`)
  - reviewer note [pass 2] `tests/middleware/test_shared_data.py:0`: No test sends If-Modified-Since or a HEAD request, and none checks that cache=False ignores conditional headers (no 304 even with a matching If-None-Match); only the If-None-Match 304 path is covered.
- `T5` With all internal callers migrated, reimplement make_conditional through the new methods and deprecate it, and deprecate http.is_resource_modified/is_byte_range_valid; wrap existing tests in deprecated_call or move to new-method tests. (1 attempt(s), commit `e22bee1c18`)
  - reviewer note [pass 1] `src/werkzeug/wrappers/response.py:866`: make_conditional now raises 416 for an unparseable Range header before the If-Range check, whereas the old code skipped range handling when If-Range did not match, so "behaves as before" does not hold for that combination.
  - reviewer note [pass 2] `tests/test_wrappers.py:687`: No test covers an invalid or non-bytes Range header together with a mismatching If-Range via make_conditional, which is the case where the new ordering differs from the old.
  - reviewer note [pass 4] `src/werkzeug/wrappers/response.py:850`: The save and restore of Accept-Ranges and Content-Length around apply_conditions/apply_range is verbose; it exists only to keep the old make_conditional behaviour, so a short comment saying so would help.
- `T6` Document apply_conditions/apply_range in the quickstart and add a changelog entry. (1 attempt(s), commit `a4b8278231`)

### Gate failures along the way

- review.approved (T2, attempt 1): review.changes_requested

### Cost (client-side estimate)

- sessions: 18; turns: 174; USD: 3.01; attempts: 6

_Generated by aih run `20261012T203156Z-06735b`._
