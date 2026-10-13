## Split `Response.make_conditional` into two correct, separate methods and refactor `send_file` and

### Plan

Add the new primitives first (IfRange.check and header validation, then apply_conditions/apply_range), migrate send_file and then SharedDataMiddleware onto them, and only then deprecate make_conditional and the http helpers, since pytest treats warnings as errors. Docs and changelog come last. Tests that exercise the deprecated functions move or are removed in the deprecation task.

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

- `INTENT1` Add Response.apply_conditions(request, *, exists=True) in wrappers/response.py that evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, treats a star ETag according to `exists`, raises PreconditionFailed on failure, turns satisfied If-None-Match/If-Modified-Since on GET/HEAD into a 304 with entity headers removed, and sets Accept-Ranges: bytes. (change)
- `INTENT2` Add Response.apply_range(request) that always sets Accept-Ranges: bytes, applies Range only for GET with a 200 response and known non-zero Content-Length (otherwise leaves the response unchanged), supports only bytes, clamps too-large stop/suffix, uses only the first range, raises RequestedRangeNotSatisfiable when unsatisfiable, otherwise returns a 206 with sliced data and Content-Range, and honors If-Range. (change)
- `INTENT3` Add IfRange.check(etag, last_modified) -> bool in datastructures/range.py that is true for a strong ETag equal to etag or a date equal to last_modified, and use it from apply_range. (change)
- `INTENT4` Keep Response.make_conditional working but emit a DeprecationWarning, implemented via apply_conditions and apply_range; deprecate werkzeug.http.is_resource_modified and is_byte_range_valid the same way. (change)
- `INTENT5` Make Range.from_header, Range.make_content_range and ContentRange.from_header validate their own values; make_content_range clamps too-large stop/suffix values and uses the first range when several are given; ETagSet.from_header discards invalid unquoted values. (change)
- `INTENT6` Refactor send_file in utils.py to use the new methods, detect name/size/mtime from file-like objects when possible, call seek(0) on file-like objects, drop the path hash from the ETag, and default to application/octet-stream instead of raising when download_name is not passed. (change)
- `INTENT7` Make SharedDataMiddleware serve files through send_file, stop setting cache_timeout by default, and deprecate (still accept, with DeprecationWarning) its cache and fallback_mimetype parameters. (change)
- `INTENT8` Document the new methods in the quickstart docs and add a changelog entry. (change)
- `INTENT9` Add tests for apply_conditions (each header, method coverage, star ETag with/without resource, 304 vs 412) and apply_range (first range only, clamping, unsatisfiable, 206 with correct Content-Range); update send_file tests for detection, seek, ETag and mimetype behaviour; move or remove tests of the deprecated functions; the suite `pytest -m "not dev_server"` must stay green. (change)

### Criteria, tests and results

| Criterion | Kind | Task | Test(s) | Result |
|---|---|---|---|---|
| ACC1 | behavior | T1 | `tests/test_datastructures.py::test_if_range_check` (covered) | committed |
| ACC2 | behavior | T1 | `tests/test_datastructures.py::test_range_make_content_range` (covered) | committed |
| ACC3 | behavior | T1 | `tests/test_datastructures.py::test_etag_set_discards_invalid_unquoted` (covered) | committed |
| ACC4 | behavior | T2 | `tests/test_wrappers.py::test_apply_conditions_if_none_match_takes_precedence_over_modified_since` (covered) | committed |
| ACC5 | behavior | T2 | `tests/test_wrappers.py::test_apply_conditions_if_none_match_unsafe_412` (covered) | committed |
| ACC6 | behavior | T2 | `tests/test_wrappers.py::test_apply_conditions_if_none_match_star` (covered) | committed |
| ACC7 | behavior | T2 | `tests/test_wrappers.py::test_apply_range_unknown_or_zero_length` (covered) | committed |
| ACC8 | behavior | T2 | `tests/test_wrappers.py::test_apply_range_first_only` (covered) | committed |
| ACC9 | behavior | T2 | `tests/test_wrappers.py::test_apply_range_if_range_etag` (covered) | committed |
| ACC10 | behavior | T3 | `tests/test_send_file.py::test_object_seeks_to_start` (covered) | committed |
| ACC11 | behavior | T3 | `tests/test_send_file.py::test_etag` (covered) | committed |
| ACC12 | behavior | T3 | `tests/test_send_file.py::test_object_without_mimetype` (covered) | committed |
| ACC13 | behavior | T4 | `tests/middleware/test_shared_data.py::test_conditional_304` (covered) | committed |
| ACC14 | behavior | T4 | `tests/middleware/test_shared_data.py::test_fallback_mimetype_deprecated_and_used` (covered) | committed |
| ACC15 | behavior | T5 | `tests/test_wrappers.py::test_make_conditional_deprecated` (covered) | committed |
| ACC16 | behavior | T5 | `tests/test_http.py::TestHTTPUtility::test_is_byte_range_valid_deprecated` (covered) | committed |
| ACC17 | other | T6 | - | committed |
| ACC18 | behavior | T5 | `tests/test_http.py::TestHTTPUtility::test_is_resource_modified` (covered) | committed |

### Tasks

- `T1` Add IfRange.check, make Range.make_content_range self-validating with clamping and first-range-only (no is_byte_range_valid), tighten Range/ContentRange.from_header validation and ETagSet.from_header invalid unquoted values. (1 attempt(s), commit `6bae41f7fc`)
  - reviewer note [pass 2] `tests/test_datastructures.py:1139`: IfRange.check is not tested with a naive last_modified or an If-Range holding a weak ETag, but neither is a required behaviour.
  - reviewer note [pass 4] `tests/test_datastructures.py:1105`: ETagSet.from_header already discarded invalid unquoted values, and etag.py is unchanged, so this test only locks in existing behaviour.
- `T2` Add Response.apply_conditions and Response.apply_range (using IfRange.check) alongside the existing, still non-deprecated make_conditional, and add tests for them. (1 attempt(s), commit `114df77af4`)
  - reviewer note [pass 2] `tests/test_wrappers.py:710`: No test covers If-Match (or a star If-Match) when the response has no ETag, nor a failing If-Match combined with If-None-Match, so the ordering of the 412 check before the 304 check is unproven.
  - reviewer note [pass 4] `tests/test_wrappers.py:688`: `_cond_response(**kwargs)` accepts kwargs it never uses.
  - reviewer note [pass 4] `src/werkzeug/wrappers/response.py:800`: The `if_none_match.star_tag` and `if_match.star_tag` branches could be folded into a small helper, but this is cosmetic.
- `T3` Refactor send_file onto apply_conditions/apply_range: detect name/size/mtime from file objects, seek(0), drop path hash from ETag, default to octet-stream; update send_file tests. (1 attempt(s), commit `624fcf44c1`)
  - reviewer note [pass 2] `tests/test_send_file.py:67`: mtime detection from a file object is only asserted as `last_modified is not None`; no test checks the value equals the file's mtime or that an ETag is generated for a file object, and no test checks that an explicit download_name overrides a named file's name.
  - reviewer note [pass 4] `src/werkzeug/utils.py:424`: The `path_name` temporary can be folded into one expression, e.g. `if download_name is None and isinstance(name, str): download_name = os.path.basename(name)`.
- `T4` Serve files in SharedDataMiddleware through send_file, drop the default cache_timeout, deprecate cache and fallback_mimetype params; update middleware tests. (1 attempt(s), commit `5549979983`)
  - reviewer note [pass 2] `tests/middleware/test_shared_data.py:0`: No test covers If-Range, HEAD, or a Range request combined with a conditional header through the middleware; these are exercised only indirectly via send_file tests.
  - reviewer note [pass 4] `src/werkzeug/middleware/shared_data.py:248`: generate_etag (and its adler32 import) is no longer used by __call__; it is kept as a public method, so removal is optional.
  - reviewer note [pass 3] `tests/middleware/test_shared_data.py:0`: No existing test was weakened; the diff only adds tests.
- `T5` Deprecate Response.make_conditional (reimplemented via the new methods) and http.is_resource_modified/is_byte_range_valid; migrate remaining internal callers and move/remove their old tests (expect DeprecationWarning where kept). (1 attempt(s), commit `aff5eae8a8`)
  - reviewer note [pass 4] `tests/test_wrappers.py:764`: `_LM =datetime(...)` lost the space after `=`. This is an unrelated formatting regression that `ruff format` will flag; restore `_LM = datetime(...)`.
  - reviewer note [pass 3] `tests/test_wrappers.py:725`: `test_invalid_range_request` was changed from `bytes=-` to `bytes=20-30`. The new `test_malformed_range_request_ignored` covers the old input with the new behaviour, so no case is lost, but the behaviour change (416 to 200) is only documented in a comment.
  - reviewer note [pass 1] `src/werkzeug/wrappers/response.py:825`: `make_conditional` now sets `content_length = complete_length` whenever `complete_length` is truthy, even with no range. The old code set it only for a 206. This is tested, but it is a silent behaviour change for a deprecated method.
- `T6` Document apply_conditions/apply_range in the quickstart and add a changelog entry covering new methods, deprecations and send_file/SharedDataMiddleware changes. (1 attempt(s), commit `8cfb9173af`)
  - reviewer note [pass 2] `CHANGES.rst:92`: Changelog omits that ETagSet.from_header now discards invalid unquoted values, a behaviour change from the plan.

### Gate failures along the way

- review.approved (T5, attempt 1): review.changes_requested

### Cost (client-side estimate)

- sessions: 17; turns: 164; USD: 2.62; attempts: 6

_Generated by aih run `20261013T194811Z-31a773`._
