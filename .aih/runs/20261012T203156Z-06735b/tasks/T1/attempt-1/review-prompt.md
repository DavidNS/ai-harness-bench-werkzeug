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

## Task T1 (T1)

Add IfRange.check, make Range/ContentRange validate themselves without http.is_byte_range_valid (clamping, first range), and make ETagSet.from_header drop invalid unquoted values.

Acceptance criteria:
- ACC1 [behavior]: IfRange.check(etag, last_modified) is true for a strong equal etag or an equal date, false otherwise (including empty IfRange and weak/other etags).
- ACC2 [behavior]: Range.make_content_range clamps too-large stop/suffix to the length, uses the first range only, returns None when unsatisfiable, and does not call werkzeug.http.is_byte_range_valid; Range.from_header and ContentRange.from_header validate values.
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
index 4a680f40..f7511d68 100644
--- a/src/werkzeug/datastructures/range.py
+++ b/src/werkzeug/datastructures/range.py
@@ -6,7 +6,6 @@ from datetime import datetime
 
 from .._internal import _plain_int
 from ..http import http_date
-from ..http import is_byte_range_valid
 from ..http import parse_date
 from .etag import ETag
 
@@ -63,6 +62,24 @@ class IfRange:
 
         return ""
 
+    def check(self, etag: ETag | None, last_modified: datetime | None) -> bool:
+        """Check whether the condition is met by the response's values. True if
+        this has a strong ETag equal to the given strong ``etag``, or a date equal
+        to ``last_modified``.
+
+        :param etag: The response's ETag.
+        :param last_modified: The response's modification time.
+
+        .. versionadded:: 3.2
+        """
+        if self.etag is not None:
+            return etag is not None and not etag.weak and etag.value == self.etag
+
+        if self.date is not None:
+            return last_modified is not None and last_modified == self.date
+
+        return False
+
     def __bool__(self) -> bool:
         return self.etag is not None or self.date is not None
 
@@ -133,44 +150,43 @@ class Range:
             DeprecationWarning,
             stacklevel=2,
         )
-        return self._private_range_for_length(length)
-
-    def _private_range_for_length(self, length: int | None) -> tuple[int, int] | None:
-        if length is None or not self.ranges:
-            return None
-
-        start, stop = self.ranges[0]
-
-        if stop is None:
-            stop = length
-
-            if start < 0:
-                start += length
-
-        if not is_byte_range_valid(start, stop, length):
+        if (cr := self.make_content_range(length)) is None:
             return None
 
-        return start, min(stop, length)
+        return cr.start, cr.stop  # type: ignore[return-value]
 
     def make_content_range(self, length: int | None) -> ContentRange | None:
         """Create a :class:`.ContentRange` with the given complete length. Or
         ``None`` if a valid range cannot be constructed.
 
         This will generate a range regardless of the value of :attr:`units`.
-        However, :meth:`.Response.make_conditional` can only handle ``bytes``.
+        However, :meth:`.Response.apply_range` can only handle ``bytes``.
 
-        If there are multiple ranges in the header, this will only return the
-        first range.
+        If there are multiple ranges in the header, this will only use the
+        first range. A ``stop`` or suffix length that is too large is clamped to
+        the complete length.
 
         .. versionchanged:: 3.2
-            Allows units other than ``bytes``. Will return the first range if
-            there are multiple.
+            Allows units other than ``bytes``. Will use the first range if
+            there are multiple. Too-large values are clamped.
         """
-        # TODO inline after deprecation
-        if (bounds := self._private_range_for_length(length)) is None:
+        if length is None or not self.ranges:
+            return None
+
+        start, stop = self.ranges[0]
+
+        if stop is None:
+            stop = length
+
+            if start < 0:
+                start = max(0, start + length)
+
+        stop = min(stop, length)
+
+        if start >= stop:
             return None
 
-        return ContentRange(self.units, bounds[0], bounds[1], length)
+        return ContentRange(self.units, start, stop, length)
 
     @classmethod
     def from_header(cls, value: str | None) -> te.Self | None:
diff --git a/tests/test_datastructures.py b/tests/test_datastructures.py
index 0136ce15..a3a5cc18 100644
--- a/tests/test_datastructures.py
+++ b/tests/test_datastructures.py
@@ -7,6 +7,9 @@ import typing as t
 from contextlib import contextmanager
 from copy import copy
 from copy import deepcopy
+from datetime import datetime
+from datetime import timedelta
+from datetime import timezone
 
 import pytest
 
@@ -14,6 +17,7 @@ from werkzeug import datastructures as ds
 from werkzeug.datastructures import ETag
 from werkzeug.datastructures import ETagSet
 from werkzeug.exceptions import BadRequestKeyError
+from werkzeug.http import http_date
 
 
 class _MutableMultiDictTests:
@@ -1098,3 +1102,91 @@ def test_etag_strong_comparison(header: ETagSet, etag: ETag, expect: bool) -> No
 )
 def test_etag_weak_comparison(header: ETagSet, etag: ETag, expect: bool) -> None:
     assert header.contains_weak(etag) is expect
+
+
+def test_etag_set_from_header_discards_invalid() -> None:
+    header = ETagSet.from_header('bad, "a", W/"b", unquoted"x", "c" junk, "d"')
+    assert header.contains_strong("a")
+    assert header.contains_weak("b")
+    assert header.contains_strong("d")
+    assert not header.contains_weak("bad")
+    assert not header.contains_weak("unquoted")
+    assert not header.contains_weak("c")
+
+
+_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
+
+
+@pytest.mark.parametrize(
+    ("header", "etag", "last_modified", "expect"),
+    [
+        pytest.param('"a"', ETag("a"), None, True, id="strong equal"),
+        pytest.param('"a"', ETag("b"), None, False, id="strong different"),
+        pytest.param('"a"', ETag("a", weak=True), None, False, id="response weak"),
+        pytest.param('"a"', None, _DATE, False, id="etag, no response etag"),
+        pytest.param('W/"a"', ETag("a"), None, False, id="header weak"),
+        pytest.param(http_date(_DATE), None, _DATE, True, id="date equal"),
+        pytest.param(
+            http_date(_DATE), None, _DATE + timedelta(seconds=1), False, id="date diff"
+        ),
+        pytest.param(http_date(_DATE), ETag("a"), None, False, id="date, none"),
+        pytest.param("", ETag("a"), _DATE, False, id="empty"),
+    ],
+)
+def test_if_range_check(
+    header: str, etag: ETag | None, last_modified: datetime | None, expect: bool
+) -> None:
+    assert ds.IfRange.from_header(header).check(etag, last_modified) is expect
+
+
+@pytest.mark.parametrize(
+    ("header", "length", "expect"),
+    [
+        pytest.param("bytes=0-9", 100, (0, 10), id="normal"),
+        pytest.param("bytes=0-999", 100, (0, 100), id="stop clamped"),
+        pytest.param("bytes=90-", 100, (90, 100), id="open"),
+        pytest.param("bytes=-10", 100, (90, 100), id="suffix"),
+        pytest.param("bytes=-1000", 100, (0, 100), id="suffix clamped"),
+        pytest.param("bytes=0-4,10-14", 100, (0, 5), id="first only"),
+        pytest.param("bytes=100-", 100, None, id="start at length"),
+        pytest.param("bytes=200-300", 100, None, id="start past length"),
+        pytest.param("bytes=-10", 0, None, id="empty content"),
+        pytest.param("bytes=0-9", None, None, id="unknown length"),
+    ],
+)
+def test_range_make_content_range(
+    monkeypatch: pytest.MonkeyPatch,
+    header: str,
+    length: int | None,
+    expect: tuple[int, int] | None,
+) -> None:
+    def fail(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
+        raise AssertionError("is_byte_range_valid must not be used")
+
+    monkeypatch.setattr("werkzeug.http.is_byte_range_valid", fail, raising=False)
+    monkeypatch.setattr(
+        "werkzeug.datastructures.range.is_byte_range_valid", fail, raising=False
+    )
+    r = ds.Range.from_header(header)
+    cr = r.make_content_range(length)
+
+    if expect is None:
+        assert cr is None
+    else:
+        assert (cr.start, cr.stop) == expect
+        assert cr.length == length
+        assert cr.units == "bytes"
+
+
+def test_range_make_content_range_no_ranges() -> None:
+    assert ds.Range("bytes", []).make_content_range(100) is None
+
+
+def test_range_for_length_deprecated() -> None:
+    r = ds.Range.from_header("bytes=0-999")
+
+    with pytest.deprecated_call():
+        assert r.range_for_length(100) == (0, 100)
+
+    with pytest.deprecated_call():
+        assert ds.Range.from_header("bytes=500-").range_for_length(100) is None

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
