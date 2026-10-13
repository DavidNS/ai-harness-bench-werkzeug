You are reviewing one task of an approved plan, implemented by a different session whose
reasoning you have not seen. You can read the repository (the change is already applied in this
worktree) but not edit it or run commands. The harness has already verified mechanically that the
diff stays within the task's files, that the changed tests fail without the production change and
pass with it, and that the whole suite is green. Do not re-check those. Your job is judgement.

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

Add the new primitives first (IfRange.check and header validation, then apply_conditions/apply_range), migrate send_file and then SharedDataMiddleware onto them, and only then deprecate make_conditional and the http helpers, since pytest treats warnings as errors. Docs and changelog come last. Tests that exercise the deprecated functions move or are removed in the deprecation task.

## Task T6 (t6_docs)

Document apply_conditions/apply_range in the quickstart and add a changelog entry covering new methods, deprecations and send_file/SharedDataMiddleware changes.

Acceptance criteria:
- ACC17 [other]: docs/quickstart.rst documents apply_conditions and apply_range instead of make_conditional, and CHANGES.rst has an entry for the new methods and deprecations.

Files declared for the task:
- docs/quickstart.rst (production)
- CHANGES.rst (production)

Test files of this task that the change modified (existing tests, declared by the plan):
- (none)

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/CHANGES.rst b/CHANGES.rst
index 995b7bf1..a87e4a7f 100644
--- a/CHANGES.rst
+++ b/CHANGES.rst
@@ -89,6 +89,23 @@ Version 3.2.0
     directly instead. :issue:`3275`
 -   The ``header_property`` function is deprecated. Access ``headers`` directly
     instead. :issue:`3280`
+-   Add ``Response.apply_conditions`` and ``Response.apply_range``, which
+    separately and correctly implement conditional requests (``If-Match``,
+    ``If-Unmodified-Since``, ``If-None-Match``, ``If-Modified-Since``) and
+    range requests (``Range``, ``If-Range``) following RFC 9110.
+    ``Response.make_conditional``, ``is_resource_modified``, and
+    ``is_byte_range_valid`` are deprecated. ``Range.from_header``,
+    ``Range.make_content_range``, and ``ContentRange.from_header`` validate
+    their own values, and ``IfRange.check`` is added. :issue:`3291`
+    :pr:`3308`
+-   ``send_file`` uses ``apply_conditions`` and ``apply_range``. It detects the
+    name, size, and modification time of file-like objects, calls ``seek(0)`` on
+    them, no longer includes a hash of the path in the ETag, and defaults to the
+    ``application/octet-stream`` mimetype instead of raising when
+    ``download_name`` is not given.
+-   ``SharedDataMiddleware`` serves files with ``send_file``, so conditional
+    and range requests work. ``cache_timeout`` is no longer set by default. The
+    ``cache`` and ``fallback_mimetype`` parameters are deprecated.
 -   The ``Request`` form parsing interface has been simplified to a single new
     ``_parse_form_data`` method. ``form_data_parser_class``,
     ``make_form_data_parser``, ``want_form_data_parsed``,
diff --git a/docs/quickstart.rst b/docs/quickstart.rst
index c7f5dc44..8e368971 100644
--- a/docs/quickstart.rst
+++ b/docs/quickstart.rst
@@ -293,10 +293,17 @@ response conditional against a request.  Which means that if the request
 can assure that it has the information already, no data besides the headers
 is sent over the network which saves traffic.  For that you should set at
 least an ETag (which is used for comparison) and the date header and then
-call :class:`~Request.make_conditional` with the request object.
+call :meth:`~Response.apply_conditions` with the request object.
 
 The response is modified accordingly (status code changed, response body
-removed, entity headers removed etc.)
+removed, entity headers removed etc.). If a precondition fails, such as
+``If-Match``, :exc:`~werkzeug.exceptions.PreconditionFailed` is raised.
+
+To support range requests, call :meth:`~Response.apply_range` with the request
+object after applying conditions. It sets ``Accept-Ranges: bytes``, and for a
+``GET`` request with a satisfiable ``Range`` header, turns the response into a
+``206 Partial Content`` response. An unsatisfiable range raises
+:exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`.
 
 
 Trusting Data

```

## Answer these questions, one at a time, in this order

1. Which acceptance criterion of this task is not met, or is met only in appearance (hard-coded, special-cased, or untested path)?
2. Which relevant case (boundary, error, empty input, interaction with existing options or state) is not covered by any test of this task?
3. Which existing test was weakened: an assertion removed or loosened, a case deleted, a skip added? Look at the modified declared test files above.
4. Which part of the diff could be removed or simplified without losing behaviour the task requires (dead code, duplicated branches, unnecessary abstraction)?

For each question, report only concrete findings: `file`, `line` (in the new version; 0 if the
finding is not tied to a line), the question number as `pass`, a `severity` and a one-sentence
`text`. `blocking` means the task must not be committed as is: a criterion unmet, a relevant case
untested, an existing test weakened, or a change that does not belong to the task. `advisory`
means worth a comment but not worth another attempt. No finding is a valid answer to a question.

## Coverage map

Then fill `coverage` with one entry per acceptance criterion marked `[behavior]` above. For
each, name the single test of this task's test files whose assertion proves the criterion:
`test` as a pytest node id (`tests/path.py::test_name`), `line` of the decisive assertion,
`status` `covered` when that assertion would fail if the criterion were broken, `partial` when
a test touches the behaviour but would not fail (asserts only the happy path, or a weaker
property), `uncovered` when no test exercises it. Read the test body: do not infer coverage
from a test's name. `partial` and `uncovered` are blocking, so when you mark one, say in
`note` what test would prove it.

`verdict` is `request_changes` if and only if there is at least one `blocking` finding or a
criterion that is not `covered`.
