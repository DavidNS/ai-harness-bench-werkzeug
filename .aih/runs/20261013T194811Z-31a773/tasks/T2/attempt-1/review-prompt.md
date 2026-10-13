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

## Task T2 (t2_response_methods)

Add Response.apply_conditions and Response.apply_range (using IfRange.check) alongside the existing, still non-deprecated make_conditional, and add tests for them.

Acceptance criteria:
- ACC4 [behavior]: apply_conditions evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods, and sets Accept-Ranges: bytes.
- ACC5 [behavior]: Failed preconditions raise PreconditionFailed; a satisfied If-None-Match/If-Modified-Since on GET/HEAD yields 304 with entity headers removed.
- ACC6 [behavior]: A star ETag in If-Match/If-None-Match is evaluated according to the exists argument (exists True/False give different outcomes).
- ACC7 [behavior]: apply_range always sets Accept-Ranges: bytes, and leaves the response unchanged (no 206/416) for non-GET methods, non-200 status, or unknown/zero Content-Length, and for non-bytes units.
- ACC8 [behavior]: apply_range uses only the first range, clamps too-large stop/suffix, raises RequestedRangeNotSatisfiable when unsatisfiable, and otherwise produces 206 with sliced data, correct Content-Length and Content-Range.
- ACC9 [behavior]: With If-Range, apply_range applies the range only when the ETag (strong comparison) or Last-Modified matches the response.

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- tests/test_wrappers.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index ba2a15fb..b3eadf38 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -722,6 +722,99 @@ class Response(_SansIOResponse):
         self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
         return True
 
+    def apply_conditions(self, request: Request, *, exists: bool = True) -> None:
+        """Evaluate the request's precondition headers against this response's
+        ``etag`` and ``last_modified``, in the order given by RFC 9110:
+        ``If-Match``, ``If-Unmodified-Since``, ``If-None-Match``,
+        ``If-Modified-Since``. Also sets ``Accept-Ranges: bytes``.
+
+        A failed precondition raises :exc:`~werkzeug.exceptions.PreconditionFailed`.
+        A satisfied ``If-None-Match`` or ``If-Modified-Since`` on a ``GET`` or
+        ``HEAD`` request changes this response to ``304 Not Modified``.
+
+        :param request: The request to evaluate.
+        :param exists: Whether the resource exists. Used to evaluate a ``*``
+            ETag.
+        :raises: :exc:`~werkzeug.exceptions.PreconditionFailed`
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import PreconditionFailed
+
+        self.accept_ranges = "bytes"
+        etag = self.etag
+        last_modified = self.last_modified
+        safe_method = request.method in {"GET", "HEAD"}
+
+        if if_match := request.if_match:
+            if if_match.star_tag:
+                if not exists:
+                    raise PreconditionFailed()
+            elif not if_match.contains_strong(etag):
+                raise PreconditionFailed()
+        elif (date := request.if_unmodified_since) is not None:
+            if last_modified is not None and last_modified.replace(microsecond=0) > date:
+                raise PreconditionFailed()
+
+        if if_none_match := request.if_none_match:
+            if if_none_match.star_tag:
+                matched = exists
+            else:
+                matched = if_none_match.contains_weak(etag)
+
+            if matched:
+                if not safe_method:
+                    raise PreconditionFailed()
+
+                self.status_code = 304
+        elif safe_method and (date := request.if_modified_since) is not None:
+            if last_modified is not None and last_modified.replace(microsecond=0) <= date:
+                self.status_code = 304
+
+    def apply_range(self, request: Request) -> None:
+        """Apply the request's ``Range`` header, after conditions have been
+        applied. Always sets ``Accept-Ranges: bytes``.
+
+        The range is only applied to ``GET`` requests with a ``200`` response
+        and a known, non-zero ``Content-Length``. Only the ``bytes`` unit is
+        supported. If there are multiple ranges, only the first is used. If the
+        request has an ``If-Range`` header, the range is only applied if it
+        matches this response's ``etag`` or ``last_modified``.
+
+        :param request: The request to read the range from.
+        :raises: :exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import RequestedRangeNotSatisfiable
+
+        self.accept_ranges = "bytes"
+
+        if request.method != "GET" or self.status_code != 200:
+            return
+
+        length = self.content_length
+
+        if not length:
+            return
+
+        if (range := request.range) is None or range.units != "bytes":
+            return
+
+        if (if_range := request.if_range) and not if_range.check(
+            self.etag, self.last_modified
+        ):
+            return
+
+        if (content_range := range.make_content_range(length)) is None:
+            raise RequestedRangeNotSatisfiable(length)
+
+        content_length = content_range.stop - content_range.start  # type: ignore[operator]
+        self.content_length = content_length
+        self.content_range = content_range
+        self.status_code = 206
+        self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
+
     def make_conditional(
         self,
         request_or_environ: WSGIEnvironment | Request,
diff --git a/tests/test_wrappers.py b/tests/test_wrappers.py
index 0960e588..261d2501 100644
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
@@ -681,6 +682,324 @@ def test_invalid_range_request():
         response.make_conditional(env, accept_ranges=True, complete_length=11)
 
 
+_LM = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
+_LM_HEADER = "Mon, 01 Jan 2024 12:00:00 GMT"
+_EARLIER_HEADER = "Sun, 31 Dec 2023 12:00:00 GMT"
+_LATER_HEADER = "Tue, 02 Jan 2024 12:00:00 GMT"
+
+
+def _cond_response(**kwargs):
+    response = wrappers.Response("Hello World")
+    response.etag = "abc"
+    response.last_modified = _LM
+    return response
+
+
+def _cond_request(method="GET", **headers):
+    return wrappers.Request.from_values(method=method, headers=headers)
+
+
+def test_apply_conditions_no_headers():
+    response = _cond_response()
+    response.apply_conditions(_cond_request())
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
+def test_apply_conditions_if_match(method):
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-Match": '"abc"'}))
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(method, **{"If-Match": '"xyz"'}))
+
+
+def test_apply_conditions_if_match_weak_fails():
+    response = _cond_response()
+    response.etag = ETag("abc", weak=True)
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(**{"If-Match": 'W/"abc"'}))
+
+
+def test_apply_conditions_if_match_star():
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-Match": "*"}), exists=True)
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(**{"If-Match": "*"}), exists=False)
+
+
+def test_apply_conditions_if_unmodified_since():
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-Unmodified-Since": _LM_HEADER}))
+    response.apply_conditions(_cond_request(**{"If-Unmodified-Since": _LATER_HEADER}))
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _cond_request("PUT", **{"If-Unmodified-Since": _EARLIER_HEADER})
+        )
+
+    # Ignored without a Last-Modified.
+    response = wrappers.Response("Hello World")
+    response.apply_conditions(_cond_request(**{"If-Unmodified-Since": _EARLIER_HEADER}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_match_takes_precedence_over_unmodified_since():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(**{"If-Match": '"abc"', "If-Unmodified-Since": _EARLIER_HEADER})
+    )
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD"])
+def test_apply_conditions_if_none_match_304(method):
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-None-Match": '"abc"'}))
+    assert response.status_code == 304
+
+    # Weak comparison.
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-None-Match": 'W/"abc"'}))
+    assert response.status_code == 304
+
+
+def test_apply_conditions_304_removes_entity_headers():
+    response = _cond_response()
+    response.headers["Content-Type"] = "text/plain"
+    response.apply_conditions(_cond_request(**{"If-None-Match": '"abc"'}))
+    environ = create_environ()
+    headers = response.get_wsgi_headers(environ)
+    assert "Content-Type" not in headers
+    assert "Content-Length" not in headers
+
+
+def test_apply_conditions_if_none_match_no_match():
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-None-Match": '"xyz"'}))
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
+def test_apply_conditions_if_none_match_unsafe_412(method):
+    response = _cond_response()
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(method, **{"If-None-Match": '"abc"'}))
+
+    response.apply_conditions(_cond_request(method, **{"If-None-Match": '"xyz"'}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_none_match_star():
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-None-Match": "*"}), exists=True)
+    assert response.status_code == 304
+
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-None-Match": "*"}), exists=False)
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        _cond_response().apply_conditions(
+            _cond_request("PUT", **{"If-None-Match": "*"}), exists=True
+        )
+
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request("PUT", **{"If-None-Match": "*"}), exists=False
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_modified_since():
+    for value in (_LM_HEADER, _LATER_HEADER):
+        response = _cond_response()
+        response.apply_conditions(_cond_request(**{"If-Modified-Since": value}))
+        assert response.status_code == 304
+
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-Modified-Since": _EARLIER_HEADER}))
+    assert response.status_code == 200
+
+    # Ignored without a Last-Modified.
+    response = wrappers.Response("Hello World")
+    response.apply_conditions(_cond_request(**{"If-Modified-Since": _LATER_HEADER}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_modified_since_ignored_for_unsafe_method():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request("POST", **{"If-Modified-Since": _LATER_HEADER})
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_none_match_takes_precedence_over_modified_since():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(**{"If-None-Match": '"xyz"', "If-Modified-Since": _LATER_HEADER})
+    )
+    assert response.status_code == 200
+
+
+def _range_request(value, method="GET", **headers):
+    return _cond_request(method, Range=value, **headers)
+
+
+def test_apply_range_basic():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=0-4"))
+    assert response.status_code == 206
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.headers["Content-Range"] == "bytes 0-4/11"
+    assert response.headers["Content-Length"] == "5"
+    assert response.data == b"Hello"
+
+
+def test_apply_range_no_range_header():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_cond_request())
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_invalid_header_ignored():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=-"))
+    assert response.status_code == 200
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_first_only():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=0-1,4-5"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-1/11"
+    assert response.data == b"He"
+
+
+def test_apply_range_clamps_stop():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=6-666"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 6-10/11"
+    assert response.headers["Content-Length"] == "5"
+    assert response.data == b"World"
+
+
+def test_apply_range_suffix():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=-5"))
+    assert response.headers["Content-Range"] == "bytes 6-10/11"
+    assert response.data == b"World"
+
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=-666"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-10/11"
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_unsatisfiable():
+    response = wrappers.Response("Hello World")
+
+    with pytest.raises(RequestedRangeNotSatisfiable):
+        response.apply_range(_range_request("bytes=11-20"))
+
+
+@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT"])
+def test_apply_range_only_get(method):
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("bytes=0-4", method))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_only_200():
+    response = wrappers.Response("Hello World", status=404)
+    response.apply_range(_range_request("bytes=0-4"))
+    assert response.status_code == 404
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.data == b"Hello World"
+
+
+@pytest.mark.parametrize("length", [None, 0])
+def test_apply_range_unknown_or_zero_length(length):
+    response = wrappers.Response("Hello World")
+
+    if length is None:
+        del response.headers["Content-Length"]
+    else:
+        response.content_length = length
+
+    response.apply_range(_range_request("bytes=0-4"))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_other_units():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_range_request("items=0-4"))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_with_file():
+    path = os.path.join(os.path.dirname(__file__), "res", "test.txt")
+    size = os.path.getsize(path)
+
+    with open(path, "rb") as f:
+        response = wrappers.Response(f)
+        response.content_length = size
+        response.apply_range(_range_request("bytes=0-0"))
+        assert response.status_code == 206
+        assert response.headers["Content-Range"] == f"bytes 0-0/{size}"
+        assert response.headers["Content-Length"] == "1"
+        assert len(response.data) == 1
+
+
+def test_apply_range_if_range_etag():
+    response = _cond_response()
+    response.apply_range(_range_request("bytes=0-4", **{"If-Range": '"abc"'}))
+    assert response.status_code == 206
+    assert response.data == b"Hello"
+
+    # Different value, and weak values, never match.
+    response = _cond_response()
+    response.apply_range(_range_request("bytes=0-4", **{"If-Range": '"xyz"'}))
+    assert response.status_code == 200
+    assert response.data == b"Hello World"
+
+    response = _cond_response()
+    response.etag = ETag("abc", weak=True)
+    response.apply_range(_range_request("bytes=0-4", **{"If-Range": '"abc"'}))
+    assert response.status_code == 200
+
+
+def test_apply_range_if_range_date():
+    response = _cond_response()
+    response.apply_range(_range_request("bytes=0-4", **{"If-Range": _LM_HEADER}))
+    assert response.status_code == 206
+
+    response = _cond_response()
+    response.apply_range(_range_request("bytes=0-4", **{"If-Range": _EARLIER_HEADER}))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
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
