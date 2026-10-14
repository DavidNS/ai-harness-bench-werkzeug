## Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and

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

- `INTENT1` Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py evaluating If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since per RFC 9110 order/comparisons for all methods, star ETag per `exists`, raising PreconditionFailed on failure, converting to 304 (entity headers removed) for satisfied If-None-Match/If-Modified-Since on GET/HEAD, and setting Accept-Ranges: bytes. (change)
- `INTENT2` Add Response.apply_range(request) that always sets Accept-Ranges: bytes, applies Range only for GET with 200 and known non-zero Content-Length (bytes unit only, clamp stop/suffix, first range only, RequestedRangeNotSatisfiable if unsatisfiable, else 206 with sliced data and Content-Range), and honors If-Range via ETag strong comparison or Last-Modified. (change)
- `INTENT3` Keep Response.make_conditional working but emit DeprecationWarning, implemented via apply_conditions and apply_range; deprecate werkzeug.http.is_resource_modified and is_byte_range_valid the same way. (change)
- `INTENT4` Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix and uses the first range; ETagSet.from_header discards invalid unquoted values. (change)
- `INTENT5` Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py, true for a strong ETag equal to etag or a date equal to last_modified, used by apply_range. (change)
- `INTENT6` Refactor send_file in utils.py to use the new methods, detect name/size/mtime from file-like objects when possible, seek(0) file-like objects, drop the path hash from the ETag, and default to application/octet-stream when download_name is absent instead of raising. (change)
- `INTENT7` Refactor SharedDataMiddleware to serve via send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) the cache and fallback_mimetype parameters. (change)
- `INTENT8` Document apply_conditions and apply_range in the quickstart docs and add a changelog entry. (change)
- `INTENT9` Add tests for apply_conditions (each header, methods, star ETag with/without resource, 304 vs 412) and apply_range (first range, clamping, unsatisfiable, 206 Content-Range); update send_file tests for detection, seek, ETag and mimetype; move/remove tests of the deprecated functions; suite `pytest -m "not dev_server"` stays green. (change)

### Criteria, tests and results

| Criterion | Kind | Task | Test(s) | Result |
|---|---|---|---|---|
| ACC1 | behavior | T1 | `tests/test_wrappers.py::test_apply_conditions_if_match_failed_before_if_none_match` (covered) | committed |
| ACC2 | behavior | T1 | `tests/test_wrappers.py::test_etag_response` (covered) | committed |
| ACC3 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_only_get` (covered) | committed |
| ACC4 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_clamped` (covered) | committed |
| ACC5 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_if_range_etag` (covered) | committed |
| ACC6 | behavior | T1 | `tests/test_wrappers.py::test_make_conditional_deprecated` (covered) | committed |
| ACC7 | behavior | T1 | `tests/test_datastructures.py::test_make_content_range` (covered) | committed |
| ACC8 | behavior | T1 | `tests/test_datastructures.py::test_if_range_check` (covered) | committed |
| ACC9 | behavior | T1 | `tests/test_send_file.py::test_object_detects_name_size_mtime` (covered) | committed |
| ACC10 | behavior | T1 | `tests/middleware/test_shared_data.py::test_deprecated_parameters` (covered) | committed |
| ACC11 | other | T1 | tests/middleware/test_shared_data.py, tests/test_datastructures.py, tests/test_http.py, tests/test_send_file.py, tests/test_wrappers.py | committed |
| ACC12 | behavior | T1 | `tests/test_wrappers.py::test_apply_range_basic` (covered) | committed |

### Tasks

- `T1` Add apply_conditions/apply_range and IfRange.check, fix Range/ETagSet validation, then migrate send_file and SharedDataMiddleware and their tests, and deprecate make_conditional/is_resource_modified/is_byte_range_valid last (internal callers must stop using them first since warnings may be errors). Update docs and changelog. (1 attempt(s), commit `42d2d8dc7c`)
  - reviewer note [pass 3] `tests/test_wrappers.py:525`: The deleted test_etag_response_412 asserted that a 412 response from make_conditional still has a body ('Make sure there is a body still'). The new deprecated-path test only checks status_code == 412.
  - reviewer note [pass 2] `tests/test_send_file.py:1`: No test combines If-Range with send_file, or checks that apply_conditions's 304 keeps working with a Range header present. Both are interactions between the new methods and send_file.
  - reviewer note [pass 4] `src/werkzeug/wrappers/response.py:835`: The old_accept_ranges save and restore in make_conditional is a workaround for apply_conditions always setting Accept-Ranges. It is only needed to keep the deprecated method's legacy behaviour of not advertising ranges when accept_ranges is falsy.

### Cost (client-side estimate)

- sessions: 4; turns: 122; USD: 1.82; attempts: 1

_Generated by aih run `20261014T124928Z-21ad9d`._
