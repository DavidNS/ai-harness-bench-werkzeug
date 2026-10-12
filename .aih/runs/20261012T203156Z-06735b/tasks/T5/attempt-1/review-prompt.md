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

## Task T5 (T5)

With all internal callers migrated, reimplement make_conditional through the new methods and deprecate it, and deprecate http.is_resource_modified/is_byte_range_valid; wrap existing tests in deprecated_call or move to new-method tests.

Acceptance criteria:
- ACC11 [behavior]: Response.make_conditional emits DeprecationWarning and still behaves as before for GET/HEAD conditional and range cases via apply_conditions/apply_range.
- ACC12 [behavior]: http.is_resource_modified and http.is_byte_range_valid emit DeprecationWarning and still return the same results.
- ACC14 [behavior]: Full suite passes with pytest -m "not dev_server".

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- src/werkzeug/http.py (production)
- src/werkzeug/sansio/http.py (production)
- tests/test_wrappers.py (test)
- tests/test_http.py (test)
- tests/sansio/test_utils.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_http.py
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/http.py b/src/werkzeug/http.py
index da7fba49..863ed57a 100644
--- a/src/werkzeug/http.py
+++ b/src/werkzeug/http.py
@@ -1166,9 +1166,21 @@ def is_resource_modified(
                             account.
     :return: `True` if the resource was modified, otherwise `False`.
 
+    .. deprecated:: 3.2
+        Will be removed in Werkzeug 4.0. Use
+        :meth:`.Response.apply_conditions` instead.
+
     .. versionchanged:: 1.0
         The check is run for methods other than ``GET`` and ``HEAD``.
     """
+    import warnings
+
+    warnings.warn(
+        "'is_resource_modified' is deprecated and will be removed in Werkzeug 4.0."
+        " Use 'Response.apply_conditions' instead.",
+        DeprecationWarning,
+        stacklevel=2,
+    )
     return _sansio_http.is_resource_modified(
         http_range=environ.get("HTTP_RANGE"),
         http_if_range=environ.get("HTTP_IF_RANGE"),
@@ -1461,8 +1473,21 @@ def is_byte_range_valid(
 ) -> bool:
     """Checks if a given byte content range is valid for the given length.
 
+    .. deprecated:: 3.2
+        Will be removed in Werkzeug 4.0. :class:`.Range` and
+        :class:`.ContentRange` validate their own values.
+
     .. versionadded:: 0.7
     """
+    import warnings
+
+    warnings.warn(
+        "'is_byte_range_valid' is deprecated and will be removed in Werkzeug 4.0."
+        " 'Range' and 'ContentRange' validate their own values.",
+        DeprecationWarning,
+        stacklevel=2,
+    )
+
     if (start is None) != (stop is None):
         return False
     elif start is None:
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index 9978e657..1223e4f6 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -8,12 +8,9 @@ from urllib.parse import urljoin
 
 from .._internal import _dt_as_utc
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
@@ -656,73 +653,6 @@ class Response(_SansIOResponse):
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
@@ -883,7 +813,11 @@ class Response(_SansIOResponse):
         :raises: :class:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`
                  if `Range` header could not be parsed or satisfied.
 
-        .. versionchangedd: 3.2
+        .. deprecated:: 3.2
+            Will be removed in Werkzeug 4.0. Use :meth:`apply_conditions` and
+            :meth:`apply_range` instead.
+
+        .. versionchanged:: 3.2
             Adds the ``Accept-Ranges`` header if ``accept_ranges`` is passed,
             even if this is not a satisfiable range request.
 
@@ -891,6 +825,18 @@ class Response(_SansIOResponse):
             Range processing is skipped if length is 0 instead of
             raising a 416 Range Not Satisfiable error.
         """
+        import warnings
+
+        from ..exceptions import PreconditionFailed
+        from ..exceptions import RequestedRangeNotSatisfiable
+        from .request import Request
+
+        warnings.warn(
+            "'make_conditional' is deprecated and will be removed in Werkzeug 4.0."
+            " Use 'apply_conditions' and 'apply_range' instead.",
+            DeprecationWarning,
+            stacklevel=2,
+        )
         environ = _get_environ(request_or_environ)
         if environ["REQUEST_METHOD"] in ("GET", "HEAD"):
             # if the date is not in the headers, add it now.  We however
@@ -899,16 +845,38 @@ class Response(_SansIOResponse):
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
+            request = Request(environ)
+            old_accept_ranges = self.headers.get("Accept-Ranges")
+
+            try:
+                self.apply_conditions(request)
+            except PreconditionFailed:
+                self.status_code = 412
+
+            if accept_ranges:
+                self.accept_ranges = (
+                    "bytes" if accept_ranges is True else accept_ranges
+                )
+            elif old_accept_ranges is None:
+                self.headers.pop("Accept-Ranges", None)
+            else:
+                self.headers["Accept-Ranges"] = old_accept_ranges
+
+            if accept_ranges and complete_length and self.status_code == 200:
+                if "HTTP_RANGE" in environ and request.range is None:
+                    raise RequestedRangeNotSatisfiable(complete_length)
+
+                old_length = self.headers.get("Content-Length")
+                self.content_length = complete_length
+                self.apply_range(request)
+
+                if self.status_code != 206:
+                    if old_length is None:
+                        self.headers.pop("Content-Length", None)
+                    else:
+                        self.headers["Content-Length"] = old_length
+
             if (
                 self.automatically_set_content_length
                 and "Content-Length" not in self.headers
diff --git a/tests/test_http.py b/tests/test_http.py
index d0bf0e85..150ff997 100644
--- a/tests/test_http.py
+++ b/tests/test_http.py
@@ -403,6 +403,27 @@ class TestHTTPUtility:
         assert http.dump_header({"foo": "bar"}) == "foo=bar"
         assert http.dump_header({"foo*": "UTF-8''bar"}) == "foo*=UTF-8''bar"
 
+    def test_is_resource_modified_deprecated(self):
+        with pytest.deprecated_call():
+            assert http.is_resource_modified(create_environ())
+
+    def test_is_byte_range_valid_deprecated(self):
+        with pytest.deprecated_call():
+            assert http.is_byte_range_valid(0, 5, 10)
+
+        with pytest.deprecated_call():
+            assert not http.is_byte_range_valid(5, 5, 10)
+
+        with pytest.deprecated_call():
+            assert not http.is_byte_range_valid(None, 5, 10)
+
+        with pytest.deprecated_call():
+            assert http.is_byte_range_valid(None, None, None)
+
+        with pytest.deprecated_call():
+            assert http.is_byte_range_valid(1, 3, None)
+
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified(self):
         env = create_environ()
 
@@ -428,6 +449,7 @@ class TestHTTPUtility:
             env, last_modified=datetime(2008, 1, 1, 13, 00)
         )
 
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified_for_range_requests(self):
         env = create_environ()
 
diff --git a/tests/test_wrappers.py b/tests/test_wrappers.py
index 87861e2b..9ea6e77c 100644
--- a/tests/test_wrappers.py
+++ b/tests/test_wrappers.py
@@ -510,6 +510,11 @@ def test_get_data_method_parsing_caching_behavior():
     assert req.form["foo"] == "Hello World"
 
 
+def _make_conditional(response, *args, **kwargs):
+    with pytest.deprecated_call():
+        return response.make_conditional(*args, **kwargs)
+
+
 def test_etag_response():
     response = wrappers.Response("Hello World")
     assert response.etag is None
@@ -529,7 +534,7 @@ def test_etag_response():
     env.update(
         {"REQUEST_METHOD": "GET", "HTTP_IF_NONE_MATCH": response.headers["ETag"]}
     )
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert "Date" in response.headers
 
     # after the thing is invoked by the server as wsgi application
@@ -543,13 +548,13 @@ def test_etag_response():
     response = wrappers.Response("Hello World")
     response.date = 1337
     d = response.date
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert response.date == d
 
     # make sure content length is only set if missing
     response = wrappers.Response("Hello World")
     response.content_length = 999
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert response.content_length == 999
 
 
@@ -570,7 +575,7 @@ def test_etag_response_412():
     assert "Date" not in response.headers
     env = create_environ()
     env.update({"REQUEST_METHOD": "GET", "HTTP_IF_MATCH": '"xyz"'})
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert "Date" in response.headers
 
     # after the thing is invoked by the server as wsgi application
@@ -585,20 +590,20 @@ def test_etag_response_412():
     response = wrappers.Response("Hello World")
     response.date = 1337
     d = response.date
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert response.date == d
 
     # make sure content length is only set if missing
     response = wrappers.Response("Hello World")
     response.content_length = 999
-    response.make_conditional(env)
+    _make_conditional(response, env)
     assert response.content_length == 999
 
 
 def test_advertise_accept_ranges() -> None:
     env = create_environ()
     response = wrappers.Response()
-    response.make_conditional(env, accept_ranges=True)
+    _make_conditional(response, env, accept_ranges=True)
     assert response.status_code == 200
     assert response.headers["Accept-Ranges"] == "bytes"
     assert "Content-Range" not in response.headers
@@ -608,7 +613,7 @@ def test_range_request_basic():
     env = create_environ()
     response = wrappers.Response("Hello World")
     env["HTTP_RANGE"] = "bytes=0-4"
-    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    _make_conditional(response, env, accept_ranges=True, complete_length=11)
     assert response.status_code == 206
     assert response.headers["Accept-Ranges"] == "bytes"
     assert response.headers["Content-Range"] == "bytes 0-4/11"
@@ -620,7 +625,7 @@ def test_range_request_out_of_bound():
     env = create_environ()
     response = wrappers.Response("Hello World")
     env["HTTP_RANGE"] = "bytes=6-666"
-    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    _make_conditional(response, env, accept_ranges=True, complete_length=11)
     assert response.status_code == 206
     assert response.headers["Accept-Ranges"] == "bytes"
     assert response.headers["Content-Range"] == "bytes 6-10/11"
@@ -637,8 +642,8 @@ def test_range_request_with_file():
     with open(fname, "rb") as f:
         response = wrappers.Response(f)
         env["HTTP_RANGE"] = "bytes=0-0"
-        response.make_conditional(
-            env, accept_ranges=True, complete_length=len(fcontent)
+        _make_conditional(
+            response, env, accept_ranges=True, complete_length=len(fcontent)
         )
         assert response.status_code == 206
         assert response.headers["Accept-Ranges"] == "bytes"
@@ -657,7 +662,7 @@ def test_range_request_with_complete_file():
         fsize = os.path.getsize(fname)
         response = wrappers.Response(f)
         env["HTTP_RANGE"] = f"bytes=0-{fsize - 1}"
-        response.make_conditional(env, accept_ranges=True, complete_length=fsize)
+        _make_conditional(response, env, accept_ranges=True, complete_length=fsize)
         assert response.status_code == 206
         assert response.headers["Accept-Ranges"] == "bytes"
         assert response.headers["Content-Range"] == f"bytes 0-{fsize - 1}/{fsize}"
@@ -669,7 +674,7 @@ def test_range_request_with_complete_file():
 def test_range_request_without_complete_length(value):
     env = create_environ(headers={"Range": "bytes=0-10"})
     response = wrappers.Response("Hello World")
-    response.make_conditional(env, accept_ranges=True, complete_length=value)
+    _make_conditional(response, env, accept_ranges=True, complete_length=value)
     assert response.status_code == 200
     assert response.data == b"Hello World"
 
@@ -679,7 +684,53 @@ def test_invalid_range_request():
     response = wrappers.Response("Hello World")
     env["HTTP_RANGE"] = "bytes=-"
     with pytest.raises(RequestedRangeNotSatisfiable):
-        response.make_conditional(env, accept_ranges=True, complete_length=11)
+        _make_conditional(response, env, accept_ranges=True, complete_length=11)
+
+
+def test_make_conditional_deprecated():
+    response = wrappers.Response("Hello World")
+
+    with pytest.deprecated_call():
+        response.make_conditional(create_environ())
+
+
+def test_make_conditional_if_range_mismatch():
+    env = create_environ(headers={"Range": "bytes=0-4", "If-Range": '"other"'})
+    response = wrappers.Response("Hello World")
+    response.etag = ETag("abc")
+    _make_conditional(response, env, accept_ranges=True, complete_length=11)
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.headers["Content-Length"] == "11"
+
+    # no length known beforehand, the response is still served in full
+    response = wrappers.Response(iter([b"Hello World"]))
+    response.etag = ETag("abc")
+    _make_conditional(response, env, accept_ranges=True, complete_length=11)
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+    assert response.get_data() == b"Hello World"
+
+
+def test_make_conditional_range_after_etag_match():
+    # a satisfied If-None-Match takes precedence over Range
+    env = create_environ(headers={"Range": "bytes=0-4", "If-None-Match": '"abc"'})
+    response = wrappers.Response("Hello World")
+    response.etag = ETag("abc")
+    _make_conditional(response, env, accept_ranges="bytes", complete_length=11)
+    assert response.status_code == 304
+
+
+def test_make_conditional_restores_accept_ranges():
+    env = create_environ()
+    response = wrappers.Response("Hello World")
+    response.headers["Accept-Ranges"] = "none"
+    _make_conditional(response, env)
+    assert response.headers["Accept-Ranges"] == "none"
+
+    response = wrappers.Response("Hello World")
+    _make_conditional(response, env)
+    assert "Accept-Ranges" not in response.headers
 
 
 _LM = datetime(2026, 1, 1, 12, 0, 0, 500, tzinfo=timezone.utc)
@@ -1374,7 +1425,7 @@ def test_stream_content_length():
     assert resp.get_wsgi_headers({})["Content-Length"] == "9"
 
     resp = wrappers.Response()
-    resp.make_conditional({"REQUEST_METHOD": "GET"})
+    _make_conditional(resp, {"REQUEST_METHOD": "GET"})
     resp.stream.writelines(["foo", "bar", "baz"])
     assert resp.get_wsgi_headers({})["Content-Length"] == "9"
 
@@ -1395,7 +1446,7 @@ def test_disabled_auto_content_length():
     assert "Content-Length" not in resp.get_wsgi_headers({})
 
     resp = MyResponse()
-    resp.make_conditional({"REQUEST_METHOD": "GET"})
+    _make_conditional(resp, {"REQUEST_METHOD": "GET"})
     assert resp.content_length is None
     assert "Content-Length" not in resp.get_wsgi_headers({})
 

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
