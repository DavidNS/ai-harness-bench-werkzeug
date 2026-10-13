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

## Task T3 (t3_send_file)

Refactor send_file onto apply_conditions/apply_range: detect name/size/mtime from file objects, seek(0), drop path hash from ETag, default to octet-stream; update send_file tests.

Acceptance criteria:
- ACC10 [behavior]: send_file detects name, size and mtime from file-like objects when possible, calls seek(0) on file-like objects so range responses have correct lengths and an already-read file is sent in full.
- ACC11 [behavior]: send_file's generated ETag does not include a hash of the path.
- ACC12 [behavior]: send_file defaults to application/octet-stream when no download_name or mimetype is available instead of raising TypeError; conditional and range requests go through apply_conditions/apply_range.

Files declared for the task:
- src/werkzeug/utils.py (production)
- tests/test_send_file.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_send_file.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/utils.py b/src/werkzeug/utils.py
index df4f7232..21bd0b02 100644
--- a/src/werkzeug/utils.py
+++ b/src/werkzeug/utils.py
@@ -12,13 +12,13 @@ from datetime import datetime
 from functools import update_wrapper
 from time import time
 from urllib.parse import quote
-from zlib import adler32
 
 from markupsafe import escape
 
 from ._internal import _missing
 from .datastructures.headers import Headers
 from .exceptions import NotFound
+from .exceptions import PreconditionFailed
 from .exceptions import RequestedRangeNotSatisfiable
 from .security import _windows_device_files
 from .security import safe_join
@@ -415,18 +415,41 @@ def send_file(
     else:
         file = path_or_file
 
+        if isinstance(file, io.TextIOBase):
+            raise ValueError("Files must be opened in binary mode or use BytesIO.")
+
+        # Seek to the start so that sizes and ranges are relative to the whole
+        # file, and a file that was already read is sent in full.
+        file.seek(0)
+        name = getattr(file, "name", None)
+
+        if isinstance(name, str):
+            path_name = os.path.basename(name)
+        else:
+            path_name = None
+
+        if download_name is None:
+            download_name = path_name
+
+        if isinstance(file, io.BytesIO):
+            size = file.getbuffer().nbytes
+        else:
+            try:
+                stat = os.fstat(file.fileno())
+            except (AttributeError, OSError):
+                pass
+            else:
+                size = stat.st_size
+                mtime = stat.st_mtime
+
     if download_name is None and path is not None:
         download_name = os.path.basename(path)
 
     if mimetype is None:
-        if download_name is None:
-            raise TypeError(
-                "Unable to detect the MIME type because a file name is"
-                " not available. Either set 'download_name', pass a"
-                " path instead of a file, or set 'mimetype'."
-            )
+        encoding = None
 
-        mimetype, encoding = mimetypes.guess_type(download_name)
+        if download_name is not None:
+            mimetype, encoding = mimetypes.guess_type(download_name)
 
         if mimetype is None:
             mimetype = "application/octet-stream"
@@ -462,10 +485,6 @@ def send_file(
     else:
         if file is None:
             file = open(path, "rb")  # type: ignore[arg-type]
-        elif isinstance(file, io.BytesIO):
-            size = file.getbuffer().nbytes
-        elif isinstance(file, io.TextIOBase):
-            raise ValueError("Files must be opened in binary mode or use BytesIO.")
 
         data = wrap_file(environ, file)
 
@@ -498,14 +517,18 @@ def send_file(
 
     if isinstance(etag, str):
         rv.etag = etag
-    elif etag and path is not None:
-        check = adler32(path.encode()) & 0xFFFFFFFF
-        rv.etag = f"{mtime}-{size}-{check}"
+    elif etag and mtime is not None:
+        rv.etag = f"{mtime}-{size}"
 
     if conditional:
+        from .wrappers import Request
+
+        request = Request(environ)
+
         try:
-            rv = rv.make_conditional(environ, accept_ranges=True, complete_length=size)
-        except RequestedRangeNotSatisfiable:
+            rv.apply_conditions(request)
+            rv.apply_range(request)
+        except (PreconditionFailed, RequestedRangeNotSatisfiable):
             if file is not None:
                 file.close()
 
diff --git a/tests/test_send_file.py b/tests/test_send_file.py
index 6143e0ed..812f2044 100644
--- a/tests/test_send_file.py
+++ b/tests/test_send_file.py
@@ -5,6 +5,8 @@ import pathlib
 import pytest
 
 from werkzeug.exceptions import NotFound
+from werkzeug.exceptions import PreconditionFailed
+from werkzeug.exceptions import RequestedRangeNotSatisfiable
 from werkzeug.http import http_date
 from werkzeug.test import create_environ
 from werkzeug.utils import send_file
@@ -52,8 +54,109 @@ def test_object(file_factory):
 
 
 def test_object_without_mimetype():
-    with pytest.raises(TypeError, match="detect the MIME type"):
-        send_file(io.BytesIO(b"test"), environ)
+    with send_file(io.BytesIO(b"test"), environ) as rv:
+        assert rv.mimetype == "application/octet-stream"
+
+
+def test_object_detects_name_size_mtime():
+    with txt_path.open("rb") as f:
+        with send_file(f, environ) as rv:
+            assert rv.mimetype == "text/plain"
+            assert rv.headers["Content-Disposition"] == "inline; filename=test.txt"
+            assert rv.content_length == txt_path.stat().st_size
+            assert rv.last_modified is not None
+
+
+def test_object_without_fileno():
+    class Obj:
+        def __init__(self):
+            self.data = io.BytesIO(b"test")
+
+        def seek(self, pos):
+            self.data.seek(pos)
+
+        def read(self, size=-1):
+            return self.data.read(size)
+
+    with send_file(Obj(), environ) as rv:
+        assert rv.content_length is None
+        assert rv.last_modified is None
+        assert "ETag" not in rv.headers
+
+    # fileno() raises for a buffered wrapper of BytesIO
+    with send_file(io.BufferedReader(io.BytesIO(b"test")), environ) as rv:
+        assert rv.content_length is None
+
+
+def test_object_seeks_to_start():
+    f = io.BytesIO(b"0123456789")
+    f.read()
+
+    with send_file(f, environ) as rv:
+        rv.direct_passthrough = False
+        assert rv.data == b"0123456789"
+
+    f = txt_path.open("rb")
+    f.read()
+
+    with send_file(f, environ) as rv:
+        rv.direct_passthrough = False
+        assert rv.data == txt_path.read_bytes()
+
+
+def test_object_range():
+    f = io.BytesIO(b"0123456789")
+    f.read(5)
+    rv = send_file(f, create_environ(headers={"Range": "bytes=2-4"}))
+
+    with rv:
+        assert rv.status_code == 206
+        assert rv.content_length == 3
+        assert rv.headers["Content-Range"] == "bytes 2-4/10"
+        rv.direct_passthrough = False
+        assert rv.data == b"234"
+
+
+def test_range_unsatisfiable_closes_file():
+    f = io.BytesIO(b"0123456789")
+
+    with pytest.raises(RequestedRangeNotSatisfiable):
+        send_file(f, create_environ(headers={"Range": "bytes=20-30"}))
+
+    assert f.closed
+
+
+def test_precondition_failed_closes_file():
+    f = io.BytesIO(b"0123456789")
+
+    with pytest.raises(PreconditionFailed):
+        send_file(
+            f,
+            create_environ(
+                headers={"If-Unmodified-Since": http_date(datetime.datetime(2000, 1, 1))}
+            ),
+            last_modified=datetime.datetime(2020, 1, 1),
+        )
+
+    assert f.closed
+
+
+def test_path_range_and_accept_ranges():
+    with send_file(txt_path, create_environ(headers={"Range": "bytes=0-1"})) as rv:
+        assert rv.status_code == 206
+        assert rv.headers["Accept-Ranges"] == "bytes"
+        assert rv.content_length == 2
+
+    with send_file(txt_path, environ, conditional=False) as rv:
+        assert "Accept-Ranges" not in rv.headers
+
+
+def test_etag_conditional_not_modified():
+    with send_file(txt_path, environ) as rv:
+        etag = rv.headers["ETag"]
+
+    with send_file(txt_path, create_environ(headers={"If-None-Match": etag})) as rv:
+        assert rv.status_code == 304
 
 
 def test_object_mimetype_from_name():
@@ -145,8 +248,10 @@ def test_max_age(value, public):
 
 
 def test_etag():
+    stat = txt_path.stat()
+
     with send_file(txt_path, environ) as rv:
-        assert rv.headers["ETag"].count("-") == 2
+        assert rv.headers["ETag"] == f'"{stat.st_mtime}-{stat.st_size}"'
 
     with send_file(txt_path, environ, etag=False) as rv:
         assert "ETag" not in rv.headers

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
