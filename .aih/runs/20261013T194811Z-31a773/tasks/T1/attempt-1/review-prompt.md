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

## Task T1 (t1_datastructures)

Add IfRange.check, make Range.make_content_range self-validating with clamping and first-range-only (no is_byte_range_valid), tighten Range/ContentRange.from_header validation and ETagSet.from_header invalid unquoted values.

Acceptance criteria:
- ACC1 [behavior]: IfRange.check(etag, last_modified) is true for a strong ETag equal to etag or a date equal to last_modified, false otherwise (including empty IfRange, mismatched values).
- ACC2 [behavior]: Range.make_content_range clamps too-large stop and suffix values to the length, uses only the first range, and returns None for unsatisfiable ranges without using http.is_byte_range_valid; Range.from_header and ContentRange.from_header reject invalid values.
- ACC3 [behavior]: ETagSet.from_header discards invalid unquoted values.

Files declared for the task:
- src/werkzeug/datastructures/range.py (production)
- src/werkzeug/datastructures/etag.py (production)
- tests/test_datastructures.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_datastructures.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/datastructures/range.py b/src/werkzeug/datastructures/range.py
index 4a680f40..e7cf961a 100644
--- a/src/werkzeug/datastructures/range.py
+++ b/src/werkzeug/datastructures/range.py
@@ -6,7 +6,6 @@ from datetime import datetime
 
 from .._internal import _plain_int
 from ..http import http_date
-from ..http import is_byte_range_valid
 from ..http import parse_date
 from .etag import ETag
 
@@ -53,6 +52,33 @@ class IfRange:
 
         return cls(etag=etag.value)
 
+    def check(self, etag: ETag | str | None, last_modified: datetime | None) -> bool:
+        """Check whether this condition is met by the response's values. True
+        if a strong ETag is equal to ``etag``, or a date is equal to
+        ``last_modified``.
+
+        :param etag: The response's ETag. A ``str`` is an unquoted strong value.
+        :param last_modified: The response's timezone-aware modification time.
+
+        .. versionadded:: 3.2
+        """
+        if self.etag is not None:
+            if isinstance(etag, ETag):
+                if etag.weak:
+                    return False
+
+                etag = etag.value
+
+            return etag == self.etag
+
+        if self.date is not None:
+            return (
+                last_modified is not None
+                and last_modified.replace(microsecond=0) == self.date
+            )
+
+        return False
+
     def to_header(self) -> str:
         """Convert to an ``If-Range`` header value."""
         if self.date is not None:
@@ -145,12 +171,15 @@ class Range:
             stop = length
 
             if start < 0:
-                start += length
+                # A suffix longer than the content selects all of it.
+                start = max(start + length, 0)
+        else:
+            stop = min(stop, length)
 
-        if not is_byte_range_valid(start, stop, length):
+        if start >= stop:
             return None
 
-        return start, min(stop, length)
+        return start, stop
 
     def make_content_range(self, length: int | None) -> ContentRange | None:
         """Create a :class:`.ContentRange` with the given complete length. Or
@@ -187,6 +216,9 @@ class Range:
         units, _, ranges_str = value.partition("=")
         units = units.strip(" \t").lower()
 
+        if not units:
+            return None
+
         for item in ranges_str.split(","):
             item = item.strip(" \t")
 
@@ -400,7 +432,7 @@ class ContentRange:
         units, _, range_str = value.partition(" ")
         range_str, sep, length_str = range_str.partition("/")
 
-        if not sep:
+        if not units or not sep:
             return cls()
 
         if length_str == "*":
diff --git a/tests/test_datastructures.py b/tests/test_datastructures.py
index 0136ce15..a8d707ad 100644
--- a/tests/test_datastructures.py
+++ b/tests/test_datastructures.py
@@ -7,6 +7,8 @@ import typing as t
 from contextlib import contextmanager
 from copy import copy
 from copy import deepcopy
+from datetime import datetime
+from datetime import timezone
 
 import pytest
 
@@ -1098,3 +1100,93 @@ def test_etag_strong_comparison(header: ETagSet, etag: ETag, expect: bool) -> No
 )
 def test_etag_weak_comparison(header: ETagSet, etag: ETag, expect: bool) -> None:
     assert header.contains_weak(etag) is expect
+
+
+def test_etag_set_discards_invalid_unquoted() -> None:
+    s = ETagSet.from_header('foo, "a", W/bar, W/"b", "c" x, baz')
+    assert s.contains_strong("a")
+    assert s.contains_weak("b")
+    assert not s.contains_weak("foo")
+    assert not s.contains_weak("bar")
+    assert not s.contains_weak("c")
+    assert not s.contains_weak("baz")
+
+
+_http_date = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
+
+
+@pytest.mark.parametrize(
+    ("header", "etag", "last_modified", "expect"),
+    [
+        pytest.param('"1"', "1", None, True, id="etag str"),
+        pytest.param('"1"', ETag("1"), None, True, id="etag strong"),
+        pytest.param('"1"', ETag("1", weak=True), None, False, id="etag weak"),
+        pytest.param('"1"', "2", None, False, id="etag different"),
+        pytest.param('"1"', None, None, False, id="etag missing"),
+        pytest.param("Tue, 02 Jan 2024 03:04:05 GMT", None, _http_date, True, id="date"),
+        pytest.param(
+            "Tue, 02 Jan 2024 03:04:05 GMT",
+            None,
+            _http_date.replace(microsecond=500),
+            True,
+            id="date microseconds",
+        ),
+        pytest.param(
+            "Tue, 02 Jan 2024 03:04:05 GMT",
+            None,
+            _http_date.replace(second=6),
+            False,
+            id="date different",
+        ),
+        pytest.param("Tue, 02 Jan 2024 03:04:05 GMT", "1", None, False, id="date none"),
+        pytest.param("", "1", _http_date, False, id="empty"),
+    ],
+)
+def test_if_range_check(
+    header: str, etag: t.Any, last_modified: datetime | None, expect: bool
+) -> None:
+    assert ds.IfRange.from_header(header).check(etag, last_modified) is expect
+
+
+@pytest.mark.parametrize(
+    ("ranges", "length", "expect"),
+    [
+        pytest.param([(0, 5)], 10, (0, 5), id="normal"),
+        pytest.param([(2, 100)], 10, (2, 10), id="clamp stop"),
+        pytest.param([(2, None)], 10, (2, 10), id="open"),
+        pytest.param([(-3, None)], 10, (7, 10), id="suffix"),
+        pytest.param([(-100, None)], 10, (0, 10), id="clamp suffix"),
+        pytest.param([(1, 3), (5, 7)], 10, (1, 3), id="first only"),
+        pytest.param([(10, None)], 10, None, id="start at length"),
+        pytest.param([(20, 30)], 10, None, id="start past length"),
+        pytest.param([(0, 5)], 0, None, id="zero length"),
+        pytest.param([(-3, None)], 0, None, id="suffix zero length"),
+        pytest.param([(0, 5)], None, None, id="unknown length"),
+        pytest.param([], 10, None, id="no ranges"),
+    ],
+)
+def test_range_make_content_range(
+    ranges: list[tuple[int, int | None]],
+    length: int | None,
+    expect: tuple[int, int] | None,
+) -> None:
+    cr = ds.Range("bytes", ranges).make_content_range(length)
+
+    if expect is None:
+        assert cr is None
+    else:
+        assert cr is not None
+        assert (cr.start, cr.stop, cr.length) == (*expect, length)
+        assert cr.units == "bytes"
+
+
+@pytest.mark.parametrize("value", ["", "0-1", "=0-1", "bytes=", "bytes=a-b", "bytes=5-2"])
+def test_range_from_header_invalid(value: str) -> None:
+    assert ds.Range.from_header(value) is None
+
+
+@pytest.mark.parametrize(
+    "value", ["", "0-1/5", " 0-1/5", "bytes 0-1", "bytes 0-5/5", "bytes */*", "bytes a-b/5"]
+)
+def test_content_range_from_header_invalid(value: str) -> None:
+    assert not ds.ContentRange.from_header(value)

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
