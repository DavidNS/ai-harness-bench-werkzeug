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

Add the new datastructure helpers first, then the two new Response methods, migrate send_file and SharedDataMiddleware onto them, and only then deprecate make_conditional and the http helpers (warnings are errors in the test config). Docs and changelog come last.

## Task T6 (T6)

Document apply_conditions/apply_range in the quickstart and add a changelog entry.

Acceptance criteria:
- ACC13 [other]: docs/quickstart.rst documents apply_conditions and apply_range; CHANGES.rst has an entry for the change.

Files declared for the task:
- docs/quickstart.rst (production)
- docs/http.rst (production)
- CHANGES.rst (production)

Test files of this task that the change modified (existing tests, declared by the plan):
- (none)

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/CHANGES.rst b/CHANGES.rst
index 995b7bf1..ab8d5a47 100644
--- a/CHANGES.rst
+++ b/CHANGES.rst
@@ -40,6 +40,19 @@ Version 3.2.0
     setting or deleting ``response.content_range``.
 -   ``Range.range_for_length`` and ``to_content_range_header`` are deprecated.
     Use ``make_content_range`` instead.
+-   Add ``Response.apply_conditions`` and ``apply_range``, which evaluate
+    conditional and range request headers as specified by RFC 9110.
+    ``Response.make_conditional``, ``http.is_resource_modified``, and
+    ``http.is_byte_range_valid`` are deprecated. Add ``IfRange.check``.
+    ``Range.make_content_range`` clamps too-large values and uses the first
+    range. :issue:`3291` :pr:`3308`
+-   ``send_file`` uses ``apply_conditions`` and ``apply_range``. It detects the
+    name, size, and modification time of file-like objects, calls ``seek(0)``
+    on them, no longer includes a hash of the path in the ETag, and defaults to
+    the ``application/octet-stream`` mimetype instead of raising.
+-   ``SharedDataMiddleware`` serves files with ``send_file``. ``cache_timeout``
+    is no longer set by default so that conditional caching works. The
+    ``cache`` and ``fallback_mimetype`` parameters are deprecated.
 -   All ``Response`` header properties behave consistently and document their
     get/set types. They can be set to ``None`` or use ``del`` to unset the
     header. They will not set empty header values. Structured header classes are
diff --git a/docs/http.rst b/docs/http.rst
index ee36ac35..e2a55270 100644
--- a/docs/http.rst
+++ b/docs/http.rst
@@ -108,6 +108,10 @@ For conditional responses the following functions might be useful:
 
 .. autofunction:: is_resource_modified
 
+See also :meth:`~werkzeug.wrappers.Response.apply_conditions` and
+:meth:`~werkzeug.wrappers.Response.apply_range`, which replace the deprecated
+``is_resource_modified`` and ``is_byte_range_valid``.
+
 Constants
 =========
 
diff --git a/docs/quickstart.rst b/docs/quickstart.rst
index c7f5dc44..8599192f 100644
--- a/docs/quickstart.rst
+++ b/docs/quickstart.rst
@@ -293,10 +293,21 @@ response conditional against a request.  Which means that if the request
 can assure that it has the information already, no data besides the headers
 is sent over the network which saves traffic.  For that you should set at
 least an ETag (which is used for comparison) and the date header and then
-call :class:`~Request.make_conditional` with the request object.
+call :meth:`~werkzeug.wrappers.Response.apply_conditions` with the request
+object.
 
 The response is modified accordingly (status code changed, response body
-removed, entity headers removed etc.)
+removed, entity headers removed etc.) A failed ``If-Match`` or
+``If-Unmodified-Since`` precondition raises
+:exc:`~werkzeug.exceptions.PreconditionFailed`.
+
+To support partial requests, call
+:meth:`~werkzeug.wrappers.Response.apply_range` after ``apply_conditions``.
+It applies the request's ``Range`` header, turning the response into a
+``206 Partial Content`` response with a ``Content-Range`` header, or raising
+:exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`.
+
+``Response.make_conditional`` is deprecated in favor of these two methods.
 
 
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

`verdict` is `request_changes` if and only if there is at least one `blocking` finding.
