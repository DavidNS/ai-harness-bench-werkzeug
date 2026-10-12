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

## Task T1 (T1_datastructures)

Add IfRange.check, make Range/ContentRange parsing and make_content_range self-validating with clamping and first-range use (no longer importing is_byte_range_valid), and make ETagSet.from_header discard invalid unquoted values. Add tests.

Acceptance criteria:
- ACC1 [behavior]: IfRange.check(etag, last_modified) returns True for a strong ETag equal to etag or a date equal to last_modified, False otherwise (empty IfRange, differing values, etag None).
- ACC2 [behavior]: Range.make_content_range clamps a too-large stop or suffix length to the complete length, uses only the first of several ranges, returns None when unsatisfiable, and does so without importing http.is_byte_range_valid; Range.from_header and ContentRange.from_header reject invalid values.
- ACC3 [behavior]: ETagSet.from_header discards invalid unquoted values while keeping valid quoted and weak tags.

Files declared for the task:
- src/werkzeug/datastructures/range.py (production)
- src/werkzeug/datastructures/etag.py (production)
- tests/test_http.py (test)
- tests/test_datastructures.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_datastructures.py
- tests/test_http.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/datastructures/range.py b/src/werkzeug/datastructures/range.py
index 4a680f40..e3e6e68d 100644
--- a/src/werkzeug/datastructures/range.py
+++ b/src/werkzeug/datastructures/range.py
@@ -3,10 +3,10 @@ from __future__ import annotations
 import collections.abc as cabc
 import typing as t
 from datetime import datetime
+from datetime import timezone
 
 from .._internal import _plain_int
 from ..http import http_date
-from ..http import is_byte_range_valid
 from ..http import parse_date
 from .etag import ETag
 
@@ -53,6 +53,37 @@ class IfRange:
 
         return cls(etag=etag.value)
 
+    def check(
+        self, etag: ETag | str | None = None, last_modified: datetime | None = None
+    ) -> bool:
+        """Check whether the ``If-Range`` condition is met by the response's
+        values. A strong ETag must equal ``etag``, or a date must equal
+        ``last_modified``. A weak ``etag`` never matches.
+
+        :param etag: The response's ETag. A ``str`` is assumed to be an
+            unquoted strong value.
+        :param last_modified: The response's modification time. A naive
+            datetime is assumed to be UTC.
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
+            return bool(etag) and etag == self.etag
+
+        if self.date is not None and last_modified is not None:
+            if last_modified.tzinfo is None:
+                last_modified = last_modified.replace(tzinfo=timezone.utc)
+
+            return self.date == last_modified.replace(microsecond=0)
+
+        return False
+
     def to_header(self) -> str:
         """Convert to an ``If-Range`` header value."""
         if self.date is not None:
@@ -145,12 +176,15 @@ class Range:
             stop = length
 
             if start < 0:
-                start += length
+                # A suffix longer than the content is clamped to all of it.
+                start = max(start + length, 0)
+        else:
+            stop = min(stop, length)
 
-        if not is_byte_range_valid(start, stop, length):
+        if start < 0 or start >= stop:
             return None
 
-        return start, min(stop, length)
+        return start, stop
 
     def make_content_range(self, length: int | None) -> ContentRange | None:
         """Create a :class:`.ContentRange` with the given complete length. Or
diff --git a/tests/test_datastructures.py b/tests/test_datastructures.py
index 0136ce15..03493123 100644
--- a/tests/test_datastructures.py
+++ b/tests/test_datastructures.py
@@ -7,10 +7,14 @@ import typing as t
 from contextlib import contextmanager
 from copy import copy
 from copy import deepcopy
+from datetime import datetime
+from datetime import timedelta
+from datetime import timezone
 
 import pytest
 
 from werkzeug import datastructures as ds
+from werkzeug import http
 from werkzeug.datastructures import ETag
 from werkzeug.datastructures import ETagSet
 from werkzeug.exceptions import BadRequestKeyError
@@ -1046,6 +1050,80 @@ def test_range_to_header(ranges):
     assert r.ranges == ranges
 
 
+_lm = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
+
+
+@pytest.mark.parametrize(
+    ("header", "etag", "last_modified", "expect"),
+    [
+        pytest.param('"a"', "a", None, True, id="etag same"),
+        pytest.param('"a"', ETag("a"), None, True, id="etag object same"),
+        pytest.param('"a"', "b", None, False, id="etag different"),
+        pytest.param('"a"', None, None, False, id="etag None"),
+        pytest.param('"a"', ETag("a", weak=True), None, False, id="response weak"),
+        pytest.param('W/"a"', "a", None, False, id="header weak"),
+        pytest.param(http.http_date(_lm), None, _lm, True, id="date same"),
+        pytest.param(
+            http.http_date(_lm), None, _lm.replace(microsecond=5), True, id="date us"
+        ),
+        pytest.param(
+            http.http_date(_lm), None, _lm + timedelta(seconds=1), False, id="date diff"
+        ),
+        pytest.param(http.http_date(_lm), None, None, False, id="date None"),
+        pytest.param(http.http_date(_lm), "a", None, False, id="date, etag only"),
+        pytest.param("", "a", _lm, False, id="empty"),
+    ],
+)
+def test_if_range_check(header, etag, last_modified, expect):
+    assert ds.IfRange.from_header(header).check(etag, last_modified) is expect
+
+
+@pytest.mark.parametrize(
+    ("ranges", "length", "expect"),
+    [
+        pytest.param([(0, 5)], 10, (0, 5), id="within"),
+        pytest.param([(2, 100)], 10, (2, 10), id="stop clamped"),
+        pytest.param([(2, None)], 10, (2, 10), id="open"),
+        pytest.param([(-4, None)], 10, (6, 10), id="suffix"),
+        pytest.param([(-100, None)], 10, (0, 10), id="suffix clamped"),
+        pytest.param([(1, 3), (5, 7)], 10, (1, 3), id="first only"),
+        pytest.param([(10, 20)], 10, None, id="start past end"),
+        pytest.param([(10, None)], 10, None, id="open past end"),
+        pytest.param([(0, 5)], 0, None, id="empty content"),
+        pytest.param([(0, 5)], None, None, id="unknown length"),
+    ],
+)
+def test_range_make_content_range(ranges, length, expect):
+    cr = ds.Range("bytes", ranges).make_content_range(length)
+
+    if expect is None:
+        assert cr is None
+    else:
+        assert (cr.start, cr.stop, cr.length) == (*expect, length)
+
+
+def test_range_does_not_import_is_byte_range_valid():
+    import werkzeug.datastructures.range as range_module
+
+    assert not hasattr(range_module, "is_byte_range_valid")
+
+
+@pytest.mark.parametrize(
+    ("value", "strong", "weak"),
+    [
+        ('"a", W/"b"', {"a"}, {"b"}),
+        ('unquoted, "a"', {"a"}, set()),
+        ('"a", unquoted, W/"b"', {"a"}, {"b"}),
+        ('"a" junk, "b"', {"b"}, set()),
+        ("unquoted", set(), set()),
+    ],
+)
+def test_etag_set_from_header_discards_invalid(value, strong, weak):
+    etags = ETagSet.from_header(value)
+    assert etags._strong == strong
+    assert etags._weak == weak
+
+
 @pytest.mark.parametrize(
     ("value", "expect"),
     [
diff --git a/tests/test_http.py b/tests/test_http.py
index d0bf0e85..1d2eaea3 100644
--- a/tests/test_http.py
+++ b/tests/test_http.py
@@ -799,6 +799,29 @@ def test_range_invalid_int(value):
     assert Range.from_header(value) is None
 
 
-@pytest.mark.parametrize("value", ["*/🯱🯲🯳", "1-+2/3", "1_23-125/*"])
+def test_range_make_content_range_clamps_and_uses_first():
+    rv = Range.from_header("bytes=2-99,-3").make_content_range(10)
+    assert rv.to_header() == "bytes 2-9/10"
+
+    rv = Range.from_header("bytes=-100").make_content_range(10)
+    assert rv.to_header() == "bytes 0-9/10"
+
+    assert Range.from_header("bytes=10-").make_content_range(10) is None
+
+
+def test_if_range_check():
+    lm = datetime(1970, 1, 1, tzinfo=timezone.utc)
+    assert IfRange.from_header('"Test"').check("Test", None)
+    assert not IfRange.from_header('"Test"').check("Other", lm)
+    assert IfRange.from_header("Thu, 01 Jan 1970 00:00:00 GMT").check(None, lm)
+    assert not IfRange.from_header("").check("Test", lm)
+
+
+@pytest.mark.parametrize("value", ["bytes 5-2/10", "bytes 0-10/10", "bytes x-1/10"])
+def test_content_range_invalid_values(value):
+    assert not ContentRange.from_header(value)
+
+
+@pytest.mark.parametrize("value", ["*/🯱🯲🯳","1-+2/3", "1_23-125/*"])
 def test_content_range_invalid_int(value):
     assert not ContentRange.from_header(f"bytes {value}")

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
