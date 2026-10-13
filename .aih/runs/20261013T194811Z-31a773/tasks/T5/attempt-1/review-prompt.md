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

## Task T5 (t5_deprecations)

Deprecate Response.make_conditional (reimplemented via the new methods) and http.is_resource_modified/is_byte_range_valid; migrate remaining internal callers and move/remove their old tests (expect DeprecationWarning where kept).

Acceptance criteria:
- ACC15 [behavior]: Response.make_conditional emits DeprecationWarning and still works, implemented via apply_conditions and apply_range.
- ACC16 [behavior]: werkzeug.http.is_resource_modified and is_byte_range_valid emit DeprecationWarning and still return the same results.
- ACC18 [behavior]: Tests for the deprecated functions are moved or removed, and the whole suite passes with pytest -m 'not dev_server'.

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- src/werkzeug/http.py (production)
- tests/test_wrappers.py (test)
- tests/test_http.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_http.py
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/http.py b/src/werkzeug/http.py
index da7fba49..eaaca49b 100644
--- a/src/werkzeug/http.py
+++ b/src/werkzeug/http.py
@@ -1166,9 +1166,19 @@ def is_resource_modified(
                             account.
     :return: `True` if the resource was modified, otherwise `False`.
 
+    .. deprecated:: 3.2
+        Will be removed in Werkzeug 3.3. Use
+        :meth:`.Response.apply_conditions` instead.
+
     .. versionchanged:: 1.0
         The check is run for methods other than ``GET`` and ``HEAD``.
     """
+    warnings.warn(
+        "'is_resource_modified' is deprecated and will be removed in Werkzeug 3.3."
+        " Use 'Response.apply_conditions' instead.",
+        DeprecationWarning,
+        stacklevel=2,
+    )
     return _sansio_http.is_resource_modified(
         http_range=environ.get("HTTP_RANGE"),
         http_if_range=environ.get("HTTP_IF_RANGE"),
@@ -1461,8 +1471,19 @@ def is_byte_range_valid(
 ) -> bool:
     """Checks if a given byte content range is valid for the given length.
 
+    .. deprecated:: 3.2
+        Will be removed in Werkzeug 3.3. :meth:`.Range.make_content_range`
+        validates its own values.
+
     .. versionadded:: 0.7
     """
+    warnings.warn(
+        "'is_byte_range_valid' is deprecated and will be removed in Werkzeug 3.3."
+        " 'Range.make_content_range' validates its own values.",
+        DeprecationWarning,
+        stacklevel=2,
+    )
+
     if (start is None) != (stop is None):
         return False
     elif start is None:
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index b3eadf38..a6f349df 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -2,17 +2,15 @@ from __future__ import annotations
 
 import json
 import typing as t
+import warnings
 from http import HTTPStatus
 from types import TracebackType
 from urllib.parse import urljoin
 
 from .._internal import _get_environ
-from ..datastructures.etag import ETagSet
 from ..datastructures.headers import Headers
-from ..datastructures.range import Range
 from ..http import generate_etag
 from ..http import http_date
-from ..http import is_resource_modified
 from ..http import remove_entity_headers
 from ..sansio.response import Response as _SansIOResponse
 from ..urls import iri_to_uri
@@ -491,8 +489,6 @@ class Response(_SansIOResponse):
             location = iri_to_uri(location)
 
             if self.autocorrect_location_header:
-                import warnings
-
                 warnings.warn(
                     "Setting 'Response.autocorrect_location_header' is deprecated"
                     " and will be removed in Werkzeug 4.0. Set 'response.location'"
@@ -655,73 +651,6 @@ class Response(_SansIOResponse):
         if self.status_code == 206:
             self.response = _RangeWrapper(self.response, start, length)  # type: ignore[arg-type]
 
-    def _is_range_request_processable(self, environ: WSGIEnvironment) -> bool:
-        """Return ``True`` if `Range` header is present and if underlying
-        resource is considered unchanged when compared with `If-Range` header.
-        """
-        return "HTTP_RANGE" in environ and (
-            "HTTP_IF_RANGE" not in environ
-            or not is_resource_modified(
-                environ,
-                self.headers.get("ETag"),
-                last_modified=self.headers.get("Last-Modified"),
-                ignore_if_range=False,
-            )
-        )
-
-    def _process_range_request(
-        self,
-        environ: WSGIEnvironment,
-        complete_length: int | None,
-        accept_ranges: bool | str,
-    ) -> bool:
-        """Handle Range Request related headers (RFC7233).  If `Accept-Ranges`
-        header is valid, and Range Request is processable, we set the headers
-        as described by the RFC, and wrap the underlying response in a
-        RangeWrapper.
-
-        Returns ``True`` if Range Request can be fulfilled, ``False`` otherwise.
-
-        :raises: :class:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`
-                 if `Range` header could not be parsed or satisfied.
-
-        .. versionchanged:: 3.2
-            Adds the ``Accept-Ranges`` header if ``accept_ranges`` is passed,
-            even if this is not a satisfiable range request.
-
-        .. versionchanged:: 2.0
-            Returns ``False`` if the length is 0.
-        """
-        from ..exceptions import RequestedRangeNotSatisfiable
-
-        if not accept_ranges:
-            return False
-
-        if accept_ranges is True:
-            accept_ranges = "bytes"
-
-        self.accept_ranges = accept_ranges
-
-        if not (complete_length and self._is_range_request_processable(environ)):
-            return False
-
-        parsed_range = Range.from_header(environ.get("HTTP_RANGE"))
-
-        if parsed_range is None:
-            raise RequestedRangeNotSatisfiable(complete_length)
-
-        content_range = parsed_range.make_content_range(complete_length)
-
-        if content_range is None:
-            raise RequestedRangeNotSatisfiable(complete_length)
-
-        content_length = content_range.stop - content_range.start  # type: ignore[operator]
-        self.content_length = content_length
-        self.content_range = content_range
-        self.status_code = 206
-        self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
-        return True
-
     def apply_conditions(self, request: Request, *, exists: bool = True) -> None:
         """Evaluate the request's precondition headers against this response's
         ``etag`` and ``last_modified``, in the order given by RFC 9110:
@@ -864,24 +793,45 @@ class Response(_SansIOResponse):
             Range processing is skipped if length is 0 instead of
             raising a 416 Range Not Satisfiable error.
         """
+        warnings.warn(
+            "'make_conditional' is deprecated and will be removed in Werkzeug 3.3."
+            " Use 'apply_conditions' and 'apply_range' instead.",
+            DeprecationWarning,
+            stacklevel=2,
+        )
+        from ..exceptions import PreconditionFailed
+        from .request import Request
+
         environ = _get_environ(request_or_environ)
+
         if environ["REQUEST_METHOD"] in ("GET", "HEAD"):
+            if isinstance(request_or_environ, Request):
+                request = request_or_environ
+            else:
+                request = Request(environ)
+
             # if the date is not in the headers, add it now.  We however
             # will not override an already existing header.  Unfortunately
             # this header will be overridden by many WSGI servers including
             # wsgiref.
             if "Date" not in self.headers:
                 self.headers["Date"] = http_date()
-            is206 = self._process_range_request(environ, complete_length, accept_ranges)
-            if not is206 and not is_resource_modified(
-                environ,
-                self.headers.get("ETag"),
-                last_modified=self.headers.get("Last-Modified"),
-            ):
-                if ETagSet.from_header(environ.get("HTTP_IF_MATCH")):
-                    self.status_code = 412
-                else:
-                    self.status_code = 304
+
+            try:
+                self.apply_conditions(request)
+            except PreconditionFailed:
+                self.status_code = 412
+
+            if not accept_ranges:
+                self.headers.remove("Accept-Ranges")
+            else:
+                if accept_ranges is not True:
+                    self.accept_ranges = accept_ranges
+
+                if complete_length:
+                    self.content_length = complete_length
+                    self.apply_range(request)
+
             if (
                 self.automatically_set_content_length
                 and "Content-Length" not in self.headers
diff --git a/tests/test_http.py b/tests/test_http.py
index d0bf0e85..988e4425 100644
--- a/tests/test_http.py
+++ b/tests/test_http.py
@@ -403,6 +403,30 @@ class TestHTTPUtility:
         assert http.dump_header({"foo": "bar"}) == "foo=bar"
         assert http.dump_header({"foo*": "UTF-8''bar"}) == "foo*=UTF-8''bar"
 
+    def test_is_resource_modified_deprecated(self):
+        env = create_environ()
+
+        with pytest.deprecated_call(match="is_resource_modified"):
+            assert http.is_resource_modified(env)
+
+    @pytest.mark.parametrize(
+        ("start", "stop", "length", "expect"),
+        [
+            (None, None, None, True),
+            (None, None, 5, True),
+            (None, 3, 5, False),
+            (0, 3, None, True),
+            (3, 3, None, False),
+            (3, 3, 10, False),
+            (0, 3, 10, True),
+            (10, 12, 10, False),
+        ],
+    )
+    def test_is_byte_range_valid_deprecated(self, start, stop, length, expect):
+        with pytest.deprecated_call(match="is_byte_range_valid"):
+            assert http.is_byte_range_valid(start, stop, length) is expect
+
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified(self):
         env = create_environ()
 
@@ -428,6 +452,7 @@ class TestHTTPUtility:
             env, last_modified=datetime(2008, 1, 1, 13, 00)
         )
 
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified_for_range_requests(self):
         env = create_environ()
 
diff --git a/tests/test_wrappers.py b/tests/test_wrappers.py
index 261d2501..6541c89c 100644
--- a/tests/test_wrappers.py
+++ b/tests/test_wrappers.py
@@ -510,6 +510,47 @@ def test_get_data_method_parsing_caching_behavior():
     assert req.form["foo"] == "Hello World"
 
 
+_MC = pytest.mark.filterwarnings("ignore:'make_conditional':DeprecationWarning")
+
+
+def test_make_conditional_deprecated():
+    response = wrappers.Response("Hello World")
+
+    with pytest.deprecated_call(match="make_conditional"):
+        response.make_conditional(create_environ())
+
+    assert "Accept-Ranges" not in response.headers
+
+
+@_MC
+def test_make_conditional_accept_ranges_string():
+    response = wrappers.Response("Hello World")
+    response.make_conditional(create_environ(), accept_ranges="custom")
+    assert response.headers["Accept-Ranges"] == "custom"
+
+
+@_MC
+def test_make_conditional_request_object_and_post():
+    request = wrappers.Request.from_values(
+        headers={"If-None-Match": '"abc"', "Range": "bytes=0-4"}
+    )
+    response = wrappers.Response("Hello World")
+    response.etag = "abc"
+    response.make_conditional(request, accept_ranges=True, complete_length=11)
+    assert response.status_code == 304
+
+    # other methods are left untouched
+    response = wrappers.Response("Hello World")
+    response.make_conditional(
+        create_environ(method="POST", headers={"If-None-Match": "*"}),
+        accept_ranges=True,
+    )
+    assert response.status_code == 200
+    assert "Accept-Ranges" not in response.headers
+    assert "Date" not in response.headers
+
+
+@_MC
 def test_etag_response():
     response = wrappers.Response("Hello World")
     assert response.etag is None
@@ -553,6 +594,7 @@ def test_etag_response():
     assert response.content_length == 999
 
 
+@_MC
 def test_etag_response_412():
     response = wrappers.Response("Hello World")
     assert response.etag is None
@@ -595,6 +637,7 @@ def test_etag_response_412():
     assert response.content_length == 999
 
 
+@_MC
 def test_advertise_accept_ranges() -> None:
     env = create_environ()
     response = wrappers.Response()
@@ -604,6 +647,7 @@ def test_advertise_accept_ranges() -> None:
     assert "Content-Range" not in response.headers
 
 
+@_MC
 def test_range_request_basic():
     env = create_environ()
     response = wrappers.Response("Hello World")
@@ -616,6 +660,7 @@ def test_range_request_basic():
     assert response.data == b"Hello"
 
 
+@_MC
 def test_range_request_out_of_bound():
     env = create_environ()
     response = wrappers.Response("Hello World")
@@ -628,6 +673,7 @@ def test_range_request_out_of_bound():
     assert response.data == b"World"
 
 
+@_MC
 def test_range_request_with_file():
     env = create_environ()
     resources = os.path.join(os.path.dirname(__file__), "res")
@@ -647,6 +693,7 @@ def test_range_request_with_file():
         assert response.data == fcontent[:1]
 
 
+@_MC
 def test_range_request_with_complete_file():
     env = create_environ()
     resources = os.path.join(os.path.dirname(__file__), "res")
@@ -665,6 +712,7 @@ def test_range_request_with_complete_file():
         assert response.data == fcontent
 
 
+@_MC
 @pytest.mark.parametrize("value", [None, 0])
 def test_range_request_without_complete_length(value):
     env = create_environ(headers={"Range": "bytes=0-10"})
@@ -674,15 +722,46 @@ def test_range_request_without_complete_length(value):
     assert response.data == b"Hello World"
 
 
+@_MC
 def test_invalid_range_request():
     env = create_environ()
     response = wrappers.Response("Hello World")
-    env["HTTP_RANGE"] = "bytes=-"
+    env["HTTP_RANGE"] = "bytes=20-30"
     with pytest.raises(RequestedRangeNotSatisfiable):
         response.make_conditional(env, accept_ranges=True, complete_length=11)
 
 
-_LM = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
+@_MC
+def test_malformed_range_request_ignored():
+    # previously a 416, now the malformed header is ignored
+    env = create_environ()
+    response = wrappers.Response("Hello World")
+    env["HTTP_RANGE"] = "bytes=-"
+    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
+    assert response.data == b"Hello World"
+
+
+@_MC
+def test_make_conditional_complete_length_without_range():
+    # complete_length is used as Content-Length for a non-range response
+    response = wrappers.Response(iter([b"Hello World"]))
+    response.make_conditional(create_environ(), accept_ranges=True, complete_length=11)
+    assert response.status_code == 200
+    assert response.headers["Content-Length"] == "11"
+
+    # and for a 304 response it is only stripped when the WSGI headers are built
+    response = wrappers.Response(iter([b"Hello World"]))
+    response.etag = "abc"
+    env = create_environ(headers={"If-None-Match": '"abc"'})
+    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    assert response.status_code == 304
+    assert "Content-Length" not in response.get_wsgi_headers(env)
+
+
+_LM =datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
 _LM_HEADER = "Mon, 01 Jan 2024 12:00:00 GMT"
 _EARLIER_HEADER = "Sun, 31 Dec 2023 12:00:00 GMT"
 _LATER_HEADER = "Tue, 02 Jan 2024 12:00:00 GMT"
@@ -1389,6 +1468,7 @@ def test_auto_content_length():
     assert resp.get_wsgi_headers({})["Content-Length"] == "12"
 
 
+@_MC
 def test_stream_content_length():
     resp = wrappers.Response()
     resp.stream.writelines(["foo", "bar", "baz"])
@@ -1404,6 +1484,7 @@ def test_stream_content_length():
     assert resp.get_wsgi_headers({})["Content-Length"] == "9"
 
 
+@_MC
 def test_disabled_auto_content_length():
     class MyResponse(wrappers.Response):
         automatically_set_content_length = False

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
