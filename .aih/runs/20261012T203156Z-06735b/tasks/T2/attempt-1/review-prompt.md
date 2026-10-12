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

## Task T2 (T2)

Add Response.apply_conditions and Response.apply_range (leave make_conditional untouched for now), with tests.

Acceptance criteria:
- ACC4 [behavior]: apply_conditions evaluates If-Match, If-Unmodified-Since, If-None-Match, If-Modified-Since in RFC 9110 order for all methods; failed preconditions raise PreconditionFailed (412).
- ACC5 [behavior]: apply_conditions on GET/HEAD with satisfied If-None-Match/If-Modified-Since yields 304 with entity headers removed; on other methods If-None-Match failure raises 412; Accept-Ranges: bytes is set.
- ACC6 [behavior]: A star ETag in If-Match/If-None-Match is evaluated by the exists argument (exists=True vs False give different outcomes).
- ACC7 [behavior]: apply_range with a satisfiable bytes Range gives 206, sliced data, correct Content-Range and Content-Length; only the first range is used; too-large stop/suffix is clamped; If-Range mismatch skips the range.
- ACC8 [behavior]: apply_range raises RequestedRangeNotSatisfiable for an unsatisfiable range and ignores non-bytes units.

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- tests/test_wrappers.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index ba2a15fb..9978e657 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -6,6 +6,7 @@ from http import HTTPStatus
 from types import TracebackType
 from urllib.parse import urljoin
 
+from .._internal import _dt_as_utc
 from .._internal import _get_environ
 from ..datastructures.etag import ETagSet
 from ..datastructures.headers import Headers
@@ -722,6 +723,125 @@ class Response(_SansIOResponse):
         self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
         return True
 
+    def apply_conditions(self, request: Request, *, exists: bool = True) -> None:
+        """Evaluate the request's precondition headers against this response's
+        ``etag`` and ``last_modified``, in the order given by RFC 9110:
+        ``If-Match``, ``If-Unmodified-Since``, ``If-None-Match``,
+        ``If-Modified-Since``. Also sets ``Accept-Ranges: bytes``.
+
+        A failed precondition raises :exc:`~werkzeug.exceptions.PreconditionFailed`.
+        A satisfied ``If-None-Match`` or ``If-Modified-Since`` on a GET or HEAD
+        request changes the response to ``304 Not Modified`` and removes the
+        entity headers. For other methods, a satisfied ``If-None-Match`` raises
+        ``PreconditionFailed``.
+
+        :param request: The request to evaluate.
+        :param exists: Whether the resource exists. Used to evaluate a ``*``
+            ETag in ``If-Match`` and ``If-None-Match``.
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import PreconditionFailed
+
+        self.accept_ranges = "bytes"
+        etag = self.etag
+        last_modified = self.last_modified
+
+        # HTTP dates have no microseconds, avoid false comparisons.
+        if last_modified is not None:
+            last_modified = _dt_as_utc(last_modified.replace(microsecond=0))
+
+        if_match = request.if_match
+
+        if if_match:
+            # Strong comparison. A star matches if the resource exists.
+            if if_match.star_tag:
+                matched = exists
+            else:
+                matched = if_match.contains_strong(etag)
+
+            if not matched:
+                raise PreconditionFailed()
+        elif (unmodified_since := request.if_unmodified_since) is not None:
+            if last_modified is not None and last_modified > unmodified_since:
+                raise PreconditionFailed()
+
+        is_get = request.method in {"GET", "HEAD"}
+        not_modified = False
+        if_none_match = request.if_none_match
+
+        if if_none_match:
+            # Weak comparison. A star matches if the resource exists.
+            if if_none_match.star_tag:
+                not_modified = exists
+            else:
+                not_modified = if_none_match.contains_weak(etag)
+
+            if not_modified and not is_get:
+                raise PreconditionFailed()
+        elif is_get and (modified_since := request.if_modified_since) is not None:
+            not_modified = last_modified is not None and last_modified <= modified_since
+
+        if not_modified:
+            self.status_code = 304
+            remove_entity_headers(self.headers)
+
+    def apply_range(self, request: Request) -> None:
+        """Apply the request's ``Range`` header to this response. Call this
+        after :meth:`apply_conditions`. Only the ``bytes`` unit is supported,
+        other units are ignored. If the request has an ``If-Range`` header that
+        doesn't match this response's ``etag`` or ``last_modified``, the range
+        is ignored.
+
+        Only the first range is used. A ``stop`` or suffix length that is too
+        large is clamped to the complete length. An unsatisfiable range raises
+        :exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`. Otherwise the
+        response becomes ``206 Partial Content`` with a ``Content-Range`` header.
+
+        The complete length is taken from ``Content-Length`` if set, otherwise
+        calculated from the data. If it can't be determined, the range is
+        ignored.
+
+        :param request: The request to evaluate.
+
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import RequestedRangeNotSatisfiable
+
+        # A 304 from apply_conditions, or any other non-200 status, has no
+        # range to apply.
+        if self.status_code != 200:
+            return
+
+        parsed_range = request.range
+
+        if parsed_range is None or parsed_range.units != "bytes":
+            return
+
+        if_range = request.if_range
+
+        if if_range and not if_range.check(self.etag, self.last_modified):
+            return
+
+        length = self.content_length
+
+        if length is None:
+            length = self.calculate_content_length()
+
+            if length is None:
+                return
+
+        content_range = parsed_range.make_content_range(length)
+
+        if content_range is None:
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
index 0960e588..87861e2b 100644
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
@@ -681,6 +682,303 @@ def test_invalid_range_request():
         response.make_conditional(env, accept_ranges=True, complete_length=11)
 
 
+_LM = datetime(2026, 1, 1, 12, 0, 0, 500, tzinfo=timezone.utc)
+_LM_HEADER = "Thu, 01 Jan 2026 12:00:00 GMT"
+_BEFORE = "Wed, 31 Dec 2025 12:00:00 GMT"
+_AFTER = "Fri, 02 Jan 2026 12:00:00 GMT"
+
+
+def _cond_response():
+    response = wrappers.Response("Hello World")
+    response.etag = ETag("abc")
+    response.last_modified = _LM
+    return response
+
+
+def _cond_request(method="GET", **headers):
+    return wrappers.Request(create_environ(method=method, headers=headers))
+
+
+def test_apply_conditions_no_headers():
+    response = _cond_response()
+    response.apply_conditions(_cond_request())
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.data == b"Hello World"
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
+def test_apply_conditions_if_match(method):
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-Match": '"abc"'}))
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(method, **{"If-Match": '"other"'}))
+
+
+def test_apply_conditions_if_match_strong_only():
+    response = _cond_response()
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(**{"If-Match": 'W/"abc"'}))
+
+
+def test_apply_conditions_if_match_star():
+    response = _cond_response()
+    request = _cond_request(**{"If-Match": "*"})
+    response.apply_conditions(request, exists=True)
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(request, exists=False)
+
+
+@pytest.mark.parametrize("method", ["GET", "POST"])
+def test_apply_conditions_if_unmodified_since(method):
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(method, **{"If-Unmodified-Since": _LM_HEADER})
+    )
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _cond_request(method, **{"If-Unmodified-Since": _BEFORE})
+        )
+
+
+def test_apply_conditions_if_unmodified_since_no_last_modified():
+    response = wrappers.Response("Hello World")
+    response.apply_conditions(_cond_request(**{"If-Unmodified-Since": _BEFORE}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_match_overrides_if_unmodified_since():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(**{"If-Match": '"abc"', "If-Unmodified-Since": _BEFORE})
+    )
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD"])
+def test_apply_conditions_if_none_match_304(method):
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-None-Match": 'W/"abc"'}))
+    assert response.status_code == 304
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Type" not in response.headers
+    assert "Content-Length" not in response.headers
+
+
+def test_apply_conditions_if_none_match_no_match():
+    response = _cond_response()
+    response.apply_conditions(_cond_request(**{"If-None-Match": '"other"'}))
+    assert response.status_code == 200
+    assert "Content-Type" in response.headers
+
+
+@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
+def test_apply_conditions_if_none_match_other_methods(method):
+    response = _cond_response()
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_cond_request(method, **{"If-None-Match": '"abc"'}))
+
+    response.apply_conditions(_cond_request(method, **{"If-None-Match": '"other"'}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_none_match_star():
+    response = _cond_response()
+    request = _cond_request(**{"If-None-Match": "*"})
+    response.apply_conditions(request, exists=False)
+    assert response.status_code == 200
+    response.apply_conditions(request, exists=True)
+    assert response.status_code == 304
+
+    response = _cond_response()
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _cond_request("PUT", **{"If-None-Match": "*"}), exists=True
+        )
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD"])
+def test_apply_conditions_if_modified_since(method):
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(method, **{"If-Modified-Since": _LM_HEADER})
+    )
+    assert response.status_code == 304
+    assert "Content-Type" not in response.headers
+
+    response = _cond_response()
+    response.apply_conditions(_cond_request(method, **{"If-Modified-Since": _BEFORE}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_modified_since_other_method_ignored():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request("POST", **{"If-Modified-Since": _AFTER})
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_modified_since_no_last_modified():
+    response = wrappers.Response("Hello World")
+    response.apply_conditions(_cond_request(**{"If-Modified-Since": _AFTER}))
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_none_match_overrides_if_modified_since():
+    response = _cond_response()
+    response.apply_conditions(
+        _cond_request(**{"If-None-Match": '"other"', "If-Modified-Since": _AFTER})
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_order():
+    # If-Match failure is raised even though If-None-Match would give 304.
+    response = _cond_response()
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _cond_request(**{"If-Match": '"other"', "If-None-Match": '"abc"'})
+        )
+
+
+def _range_response(data=b"0123456789"):
+    response = wrappers.Response(data)
+    response.etag = ETag("abc")
+    response.last_modified = _LM
+    return response
+
+
+def test_apply_range_basic():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=2-4"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 2-4/10"
+    assert response.headers["Content-Length"] == "3"
+    assert response.data == b"234"
+
+
+def test_apply_range_skipped_after_304():
+    response = _range_response()
+    request = _cond_request(Range="bytes=0-1", **{"If-None-Match": '"abc"'})
+    response.apply_conditions(request)
+    assert response.status_code == 304
+    response.apply_range(request)
+    assert response.status_code == 304
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_no_range():
+    response = _range_response()
+    response.apply_range(_cond_request())
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_invalid_header_ignored():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=-"))
+    assert response.status_code == 200
+
+
+def test_apply_range_other_units_ignored():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="items=2-4"))
+    assert response.status_code == 200
+    assert response.data == b"0123456789"
+
+
+def test_apply_range_first_range_only():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=0-1,5-6"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-1/10"
+    assert response.data == b"01"
+
+
+def test_apply_range_clamps_stop():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=6-666"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 6-9/10"
+    assert response.headers["Content-Length"] == "4"
+    assert response.data == b"6789"
+
+
+def test_apply_range_clamps_suffix():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=-666"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-9/10"
+    assert response.data == b"0123456789"
+
+
+def test_apply_range_suffix():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=-3"))
+    assert response.headers["Content-Range"] == "bytes 7-9/10"
+    assert response.data == b"789"
+
+
+def test_apply_range_unsatisfiable():
+    response = _range_response()
+
+    with pytest.raises(RequestedRangeNotSatisfiable) as exc_info:
+        response.apply_range(_cond_request(Range="bytes=10-20"))
+
+    assert exc_info.value.length == 10
+    assert response.status_code == 200
+
+
+def test_apply_range_uses_content_length_header():
+    response = wrappers.Response(iter([b"0123456789"]), direct_passthrough=True)
+    response.content_length = 10
+    response.apply_range(_cond_request(Range="bytes=0-3"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-3/10"
+    assert response.headers["Content-Length"] == "4"
+
+
+def test_apply_range_unknown_length_ignored():
+    response = wrappers.Response(iter([b"0123456789"]), direct_passthrough=True)
+    response.apply_range(_cond_request(Range="bytes=0-3"))
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_if_range_etag():
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=0-1", **{"If-Range": '"abc"'}))
+    assert response.status_code == 206
+
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=0-1", **{"If-Range": '"other"'}))
+    assert response.status_code == 200
+    assert response.data == b"0123456789"
+
+
+def test_apply_range_if_range_date():
+    response = _range_response()
+    response.apply_range(
+        _cond_request(Range="bytes=0-1", **{"If-Range": _LM_HEADER})
+    )
+    assert response.status_code == 206
+
+    response = _range_response()
+    response.apply_range(_cond_request(Range="bytes=0-1", **{"If-Range": _BEFORE}))
+    assert response.status_code == 200
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
