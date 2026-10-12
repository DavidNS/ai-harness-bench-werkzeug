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

Add the new capabilities first (datastructures, then Response.apply_conditions/apply_range), migrate send_file and then SharedDataMiddleware onto them, and only then deprecate make_conditional, is_resource_modified and is_byte_range_valid (so no internal caller emits the warnings). Docs and changelog come last. Datastructures stop importing is_byte_range_valid in the first task so the later deprecation is safe.

## Task T2 (T2_response_methods)

Add Response.apply_conditions and Response.apply_range in wrappers/response.py (make_conditional left untouched for now) with new tests for headers, methods, star ETag, 304 vs 412, and range slicing/clamping/unsatisfiable.

Acceptance criteria:
- ACC4 [behavior]: apply_conditions evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order, for all request methods; failed If-Match/If-Unmodified-Since (and If-None-Match on non-GET/HEAD) raise PreconditionFailed.
- ACC5 [behavior]: A satisfied If-None-Match or If-Modified-Since on GET/HEAD turns the response into 304 with entity headers removed; on other methods it raises PreconditionFailed (412).
- ACC6 [behavior]: A star ETag in If-Match/If-None-Match is evaluated by the exists argument: If-Match * fails when exists=False; If-None-Match * fails/304 when exists=True and passes when exists=False.
- ACC7 [behavior]: apply_conditions sets Accept-Ranges: bytes.
- ACC8 [behavior]: apply_range with a satisfiable bytes Range produces 206, sliced data, correct Content-Length and Content-Range; only the first range is used; too-large stop/suffix is clamped to complete length.
- ACC9 [behavior]: apply_range raises RequestedRangeNotSatisfiable for an unsatisfiable range; non-bytes units are ignored; If-Range not matching (via IfRange.check) skips range handling and leaves a 200.

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- tests/test_wrappers.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index ba2a15fb..105cd9f6 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -722,6 +722,113 @@ class Response(_SansIOResponse):
         self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
         return True
 
+    def apply_conditions(self, request: Request, *, exists: bool = True) -> None:
+        """Evaluate the request's precondition headers against this response's
+        ``etag`` and ``last_modified``, in the order given by RFC 9110:
+        ``If-Match``, ``If-Unmodified-Since``, ``If-None-Match``,
+        ``If-Modified-Since``. Also sets the ``Accept-Ranges`` header.
+
+        A failed precondition raises :exc:`~werkzeug.exceptions.PreconditionFailed`.
+        A satisfied ``If-None-Match`` or ``If-Modified-Since`` on a ``GET`` or
+        ``HEAD`` request changes this response to ``304 Not Modified``.
+
+        :param request: The request to evaluate.
+        :param exists: Whether the resource currently exists. A ``*`` value in
+            ``If-Match`` or ``If-None-Match`` is evaluated by this.
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import PreconditionFailed
+
+        self.accept_ranges = "bytes"
+        etag = self.etag
+        last_modified = self.last_modified
+
+        if last_modified is not None:
+            last_modified = last_modified.replace(microsecond=0)
+
+        if_match = request.if_match
+        if_unmodified_since = request.if_unmodified_since
+
+        if if_match:
+            if if_match.star_tag:
+                if not exists:
+                    raise PreconditionFailed()
+            elif not if_match.contains_strong(etag):
+                raise PreconditionFailed()
+        elif if_unmodified_since is not None:
+            if last_modified is not None and last_modified > if_unmodified_since:
+                raise PreconditionFailed()
+
+        is_get = request.method in {"GET", "HEAD"}
+        if_none_match = request.if_none_match
+        if_modified_since = request.if_modified_since
+
+        if if_none_match:
+            if if_none_match.star_tag:
+                matched = exists
+            else:
+                matched = if_none_match.contains_weak(etag)
+
+            if matched:
+                if not is_get:
+                    raise PreconditionFailed()
+
+                self.status_code = 304
+        elif is_get and if_modified_since is not None:
+            if last_modified is not None and last_modified <= if_modified_since:
+                self.status_code = 304
+
+    def apply_range(self, request: Request) -> None:
+        """Apply the request's ``Range`` header to this response. Call this
+        after :meth:`apply_conditions`. Does nothing unless the request is a
+        ``GET``, the response is still ``200``, the ``Range`` unit is
+        ``bytes``, and any ``If-Range`` condition is met by this response's
+        ``etag`` and ``last_modified``.
+
+        Only the first range is used. A too-large stop or suffix length is
+        clamped to the complete length. A satisfiable range changes this
+        response to ``206 Partial Content`` with a ``Content-Range`` header.
+
+        :raises: :exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable` if
+            the range cannot be satisfied.
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import RequestedRangeNotSatisfiable
+
+        if self.status_code != 200 or request.method != "GET":
+            return
+
+        range_ = request.range
+
+        if range_ is None or range_.units != "bytes":
+            return
+
+        if_range = request.if_range
+
+        if if_range and not if_range.check(self.etag, self.last_modified):
+            return
+
+        complete_length = self.content_length
+
+        if complete_length is None:
+            complete_length = self.calculate_content_length()
+
+        if not complete_length:
+            return
+
+        content_range = range_.make_content_range(complete_length)
+
+        if content_range is None:
+            raise RequestedRangeNotSatisfiable(complete_length)
+
+        content_length = content_range.stop - content_range.start  # type: ignore[operator]
+        self.status_code = 206
+        self.content_range = content_range
+        self.content_length = content_length
+        self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
+
     def make_conditional(
         self,
         request_or_environ: WSGIEnvironment | Request,
diff --git a/tests/test_wrappers.py b/tests/test_wrappers.py
index 0960e588..98a77bc9 100644
--- a/tests/test_wrappers.py
+++ b/tests/test_wrappers.py
@@ -18,6 +18,7 @@ from werkzeug.datastructures import MIMEAccept
 from werkzeug.datastructures import MultiDict
 from werkzeug.datastructures import WWWAuthenticate
 from werkzeug.exceptions import BadRequest
+from werkzeug.exceptions import PreconditionFailed
 from werkzeug.exceptions import RequestedRangeNotSatisfiable
 from werkzeug.exceptions import SecurityError
 from werkzeug.exceptions import UnsupportedMediaType
@@ -681,6 +682,277 @@ def test_invalid_range_request():
         response.make_conditional(env, accept_ranges=True, complete_length=11)
 
 
+_LAST_MODIFIED = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
+_BEFORE = "Mon, 01 Jan 2024 11:00:00 GMT"
+_EXACT = "Mon, 01 Jan 2024 12:00:00 GMT"
+_AFTER = "Mon, 01 Jan 2024 13:00:00 GMT"
+
+
+def _conditional_pair(method="GET", **headers):
+    request = wrappers.Request(create_environ(method=method, headers=headers))
+    response = wrappers.Response("Hello World")
+    response.etag = "abc"
+    response.last_modified = _LAST_MODIFIED
+    return request, response
+
+
+def test_apply_conditions_no_headers():
+    request, response = _conditional_pair()
+    response.apply_conditions(request)
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.data == b"Hello World"
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
+@pytest.mark.parametrize(
+    ("headers", "ok"),
+    [
+        ({"If-Match": '"abc"'}, True),
+        ({"If-Match": '"x", "abc"'}, True),
+        ({"If-Match": '"x"'}, False),
+        ({"If-Match": 'W/"abc"'}, False),
+        ({"If-Unmodified-Since": _EXACT}, True),
+        ({"If-Unmodified-Since": _AFTER}, True),
+        ({"If-Unmodified-Since": _BEFORE}, False),
+        # If-Match takes precedence over If-Unmodified-Since.
+        ({"If-Match": '"abc"', "If-Unmodified-Since": _BEFORE}, True),
+        ({"If-Match": '"x"', "If-Unmodified-Since": _AFTER}, False),
+    ],
+)
+def test_apply_conditions_if_match(method, headers, ok):
+    request, response = _conditional_pair(method, **headers)
+
+    if ok:
+        response.apply_conditions(request)
+        assert response.status_code == 200
+    else:
+        with pytest.raises(PreconditionFailed):
+            response.apply_conditions(request)
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD"])
+@pytest.mark.parametrize(
+    ("headers", "not_modified"),
+    [
+        ({"If-None-Match": '"abc"'}, True),
+        ({"If-None-Match": 'W/"abc"'}, True),
+        ({"If-None-Match": '"x"'}, False),
+        ({"If-Modified-Since": _EXACT}, True),
+        ({"If-Modified-Since": _AFTER}, True),
+        ({"If-Modified-Since": _BEFORE}, False),
+        # If-None-Match takes precedence over If-Modified-Since.
+        ({"If-None-Match": '"x"', "If-Modified-Since": _AFTER}, False),
+        ({"If-None-Match": '"abc"', "If-Modified-Since": _BEFORE}, True),
+    ],
+)
+def test_apply_conditions_not_modified(method, headers, not_modified):
+    request, response = _conditional_pair(method, **headers)
+    response.apply_conditions(request)
+    assert response.status_code == (304 if not_modified else 200)
+    assert response.headers["Accept-Ranges"] == "bytes"
+
+    if not_modified:
+        # entity headers are removed from the 304 response
+        _, status, headers_out = run_wsgi_app(response, create_environ(method=method))
+        assert status.startswith("304")
+        assert "Last-Modified" not in headers_out
+        assert "Content-Length" not in headers_out
+
+
+@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
+def test_apply_conditions_if_none_match_other_methods(method):
+    request, response = _conditional_pair(method, **{"If-None-Match": '"abc"'})
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(request)
+
+    request, response = _conditional_pair(method, **{"If-None-Match": '"x"'})
+    response.apply_conditions(request)
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
+def test_apply_conditions_if_modified_since_other_methods(method):
+    request, response = _conditional_pair(method, **{"If-Modified-Since": _AFTER})
+    response.apply_conditions(request)
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["GET", "POST"])
+def test_apply_conditions_star_if_match(method):
+    request, response = _conditional_pair(method, **{"If-Match": "*"})
+    response.apply_conditions(request, exists=True)
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(request, exists=False)
+
+
+def test_apply_conditions_star_if_none_match_get():
+    request, response = _conditional_pair(**{"If-None-Match": "*"})
+    response.apply_conditions(request, exists=True)
+    assert response.status_code == 304
+
+    request, response = _conditional_pair(**{"If-None-Match": "*"})
+    response.apply_conditions(request, exists=False)
+    assert response.status_code == 200
+
+
+def test_apply_conditions_star_if_none_match_put():
+    request, response = _conditional_pair("PUT", **{"If-None-Match": "*"})
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(request, exists=True)
+
+    response.apply_conditions(request, exists=False)
+    assert response.status_code == 200
+
+
+def test_apply_conditions_without_response_validators():
+    request = wrappers.Request(
+        create_environ(headers={"If-Match": '"abc"', "If-Modified-Since": _AFTER})
+    )
+    response = wrappers.Response("Hello World")
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(request)
+
+    request = wrappers.Request(create_environ(headers={"If-Modified-Since": _AFTER}))
+    response.apply_conditions(request)
+    assert response.status_code == 200
+
+
+def _range_pair(range_header, method="GET", **headers):
+    headers["Range"] = range_header
+    request = wrappers.Request(create_environ(method=method, headers=headers))
+    return request, wrappers.Response("Hello World")
+
+
+def test_apply_range_basic():
+    request, response = _range_pair("bytes=0-4")
+    response.apply_range(request)
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-4/11"
+    assert response.headers["Content-Length"] == "5"
+    assert response.data == b"Hello"
+
+
+@pytest.mark.parametrize(
+    ("value", "expect_range", "expect_data"),
+    [
+        ("bytes=6-666", "bytes 6-10/11", b"World"),
+        ("bytes=0-666", "bytes 0-10/11", b"Hello World"),
+        ("bytes=-5", "bytes 6-10/11", b"World"),
+        ("bytes=-666", "bytes 0-10/11", b"Hello World"),
+        ("bytes=6-", "bytes 6-10/11", b"World"),
+        ("bytes=0-0,6-10", "bytes 0-0/11", b"H"),
+    ],
+)
+def test_apply_range_clamp_and_first_only(value, expect_range, expect_data):
+    request, response = _range_pair(value)
+    response.apply_range(request)
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == expect_range
+    assert response.headers["Content-Length"] == str(len(expect_data))
+    assert response.data == expect_data
+
+
+@pytest.mark.parametrize("value", ["bytes=11-", "bytes=20-30", "bytes=11-12"])
+def test_apply_range_unsatisfiable(value):
+    request, response = _range_pair(value)
+
+    with pytest.raises(RequestedRangeNotSatisfiable) as exc_info:
+        response.apply_range(request)
+
+    assert exc_info.value.length == 11
+
+
+@pytest.mark.parametrize("value", ["items=0-4", "bytes=-", "nonsense"])
+def test_apply_range_ignored(value):
+    request, response = _range_pair(value)
+    response.apply_range(request)
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_no_header():
+    request = wrappers.Request(create_environ())
+    response = wrappers.Response("Hello World")
+    response.apply_range(request)
+    assert response.status_code == 200
+
+
+def test_apply_range_empty_body():
+    request, response = _range_pair("bytes=0-4")
+    response.set_data(b"")
+    response.apply_range(request)
+    assert response.status_code == 200
+
+
+def test_apply_range_if_range():
+    request, response = _range_pair("bytes=0-4", **{"If-Range": '"abc"'})
+    response.etag = "abc"
+    response.apply_range(request)
+    assert response.status_code == 206
+    assert response.data == b"Hello"
+
+    request, response = _range_pair("bytes=0-4", **{"If-Range": '"abc"'})
+    response.etag = "other"
+    response.apply_range(request)
+    assert response.status_code == 200
+    assert response.data == b"Hello World"
+
+    request, response = _range_pair("bytes=0-4", **{"If-Range": _EXACT})
+    response.last_modified = _LAST_MODIFIED
+    response.apply_range(request)
+    assert response.status_code == 206
+
+    request, response = _range_pair("bytes=0-4", **{"If-Range": _BEFORE})
+    response.last_modified = _LAST_MODIFIED
+    response.apply_range(request)
+    assert response.status_code == 200
+
+
+def test_apply_range_skipped_when_not_200():
+    # a response already turned into 304 by apply_conditions is left alone,
+    # even if the range would be unsatisfiable
+    request, response = _range_pair("bytes=0-4")
+    response.status_code = 304
+    response.apply_range(request)
+    assert response.status_code == 304
+    assert "Content-Range" not in response.headers
+
+    request, response = _range_pair("bytes=20-30")
+    response.status_code = 404
+    response.apply_range(request)
+    assert response.status_code == 404
+
+
+@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT"])
+def test_apply_range_skipped_for_other_methods(method):
+    request, response = _range_pair("bytes=0-4", method)
+    response.apply_range(request)
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+    assert response.data == b"Hello World"
+
+    # not even an unsatisfiable range raises
+    request, response = _range_pair("bytes=20-30", method)
+    response.apply_range(request)
+    assert response.status_code == 200
+
+
+def test_apply_conditions_then_range_not_modified():
+    request, response = _range_pair("bytes=0-4", **{"If-None-Match": '"abc"'})
+    response.etag = "abc"
+    response.apply_conditions(request)
+    response.apply_range(request)
+    assert response.status_code == 304
+    assert "Content-Range" not in response.headers
+
+
 def test_etag_response_freezing():
     response = wrappers.Response("Hello World")
     response.freeze()

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
