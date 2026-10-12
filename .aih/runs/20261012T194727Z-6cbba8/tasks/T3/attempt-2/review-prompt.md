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

## Task T3 (T3_send_file)

Refactor send_file to use apply_conditions/apply_range, detect name/size/mtime from file-like objects, seek(0), drop path hash from the ETag, and default to application/octet-stream. Update send_file tests.

Acceptance criteria:
- ACC11 [behavior]: send_file with a file-like object detects name (from .name), size and mtime when possible, calls seek(0) so an already-read file or range request reports correct Content-Length/Content-Range, and defaults mimetype to application/octet-stream without raising when no download_name is given.
- ACC12 [behavior]: send_file ETag no longer contains a hash of the path (depends only on mtime and size) and conditional/range behaviour uses apply_conditions/apply_range.

Files declared for the task:
- src/werkzeug/utils.py (production)
- tests/test_send_file.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/test_send_file.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/utils.py b/src/werkzeug/utils.py
index df4f7232..2ad9481f 100644
--- a/src/werkzeug/utils.py
+++ b/src/werkzeug/utils.py
@@ -10,16 +10,16 @@ import typing as t
 import unicodedata
 from datetime import datetime
 from functools import update_wrapper
+from stat import S_ISREG
 from time import time
 from urllib.parse import quote
-from zlib import adler32
 
 from markupsafe import escape
 
 from ._internal import _missing
 from .datastructures.headers import Headers
+from .exceptions import HTTPException
 from .exceptions import NotFound
-from .exceptions import RequestedRangeNotSatisfiable
 from .security import _windows_device_files
 from .security import safe_join
 from .wsgi import wrap_file
@@ -334,8 +334,9 @@ def send_file(
 
     :param path_or_file: The path to the file to send, relative to the
         current working directory if a relative path is given.
-        Alternatively, a file-like object opened in binary mode. Make
-        sure the file pointer is seeked to the start of the data.
+        Alternatively, a file-like object opened in binary mode. The
+        file is seeked to the start, and its name, size, and modified
+        time are detected if possible.
     :param environ: The WSGI environ for the current request.
     :param mimetype: The MIME type to send for the file. If not
         provided, it will try to detect it from the file name.
@@ -415,26 +416,57 @@ def send_file(
     else:
         file = path_or_file
 
+        if isinstance(file, io.TextIOBase):
+            raise ValueError("Files must be opened in binary mode or use BytesIO.")
+
+        # Start from the beginning so an already-read file is sent in full
+        # and range responses have correct lengths.
+        try:
+            file.seek(0)
+        except (AttributeError, OSError, ValueError):
+            pass
+
+        if download_name is None:
+            name = getattr(file, "name", None)
+
+            if isinstance(name, str):
+                download_name = os.path.basename(name)
+
+        if isinstance(file, io.BytesIO):
+            size = file.getbuffer().nbytes
+        else:
+            try:
+                stat = os.fstat(file.fileno())
+            except (AttributeError, OSError, ValueError):
+                pass
+            else:
+                if S_ISREG(stat.st_mode):
+                    size = stat.st_size
+                    mtime = stat.st_mtime
+
+            if size is None:
+                try:
+                    size = file.seek(0, os.SEEK_END)
+                    file.seek(0)
+                except (AttributeError, OSError, ValueError):
+                    size = None
+
     if download_name is None and path is not None:
         download_name = os.path.basename(path)
 
     if mimetype is None:
         if download_name is None:
-            raise TypeError(
-                "Unable to detect the MIME type because a file name is"
-                " not available. Either set 'download_name', pass a"
-                " path instead of a file, or set 'mimetype'."
-            )
-
-        mimetype, encoding = mimetypes.guess_type(download_name)
-
-        if mimetype is None:
             mimetype = "application/octet-stream"
+        else:
+            mimetype, encoding = mimetypes.guess_type(download_name)
 
-        # Don't send encoding for attachments, it causes browsers to
-        # save decompress tar.gz files.
-        if encoding is not None and not as_attachment:
-            headers.set("Content-Encoding", encoding)
+            if mimetype is None:
+                mimetype = "application/octet-stream"
+
+            # Don't send encoding for attachments, it causes browsers to
+            # save decompress tar.gz files.
+            if encoding is not None and not as_attachment:
+                headers.set("Content-Encoding", encoding)
 
     if download_name is not None:
         try:
@@ -462,10 +494,6 @@ def send_file(
     else:
         if file is None:
             file = open(path, "rb")  # type: ignore[arg-type]
-        elif isinstance(file, io.BytesIO):
-            size = file.getbuffer().nbytes
-        elif isinstance(file, io.TextIOBase):
-            raise ValueError("Files must be opened in binary mode or use BytesIO.")
 
         data = wrap_file(environ, file)
 
@@ -498,14 +526,18 @@ def send_file(
 
     if isinstance(etag, str):
         rv.etag = etag
-    elif etag and path is not None:
-        check = adler32(path.encode()) & 0xFFFFFFFF
-        rv.etag = f"{mtime}-{size}-{check}"
+    elif etag and mtime is not None and size is not None:
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
+        except HTTPException:
             if file is not None:
                 file.close()
 
diff --git a/tests/test_send_file.py b/tests/test_send_file.py
index 6143e0ed..e90c812a 100644
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
@@ -52,8 +54,96 @@ def test_object(file_factory):
 
 
 def test_object_without_mimetype():
-    with pytest.raises(TypeError, match="detect the MIME type"):
-        send_file(io.BytesIO(b"test"), environ)
+    with send_file(io.BytesIO(b"test"), environ) as rv:
+        assert rv.mimetype == "application/octet-stream"
+
+
+def test_object_detects_name_size_mtime():
+    with txt_path.open("rb") as f, send_file(f, environ) as rv:
+        assert rv.mimetype == "text/plain"
+        assert rv.headers["Content-Disposition"] == "inline; filename=test.txt"
+        assert rv.content_length == txt_path.stat().st_size
+        assert rv.last_modified is not None
+        assert rv.etag is not None
+
+
+def test_object_seeks_to_start():
+    f = io.BytesIO(b"0123456789")
+    f.read()
+
+    with send_file(f, environ) as rv:
+        rv.direct_passthrough = False
+        assert rv.content_length == 10
+        assert rv.data == b"0123456789"
+
+
+def test_object_range():
+    f = io.BytesIO(b"0123456789")
+    f.read()
+    range_environ = create_environ(headers={"Range": "bytes=2-4"})
+
+    with send_file(f, range_environ) as rv:
+        assert rv.status_code == 206
+        assert rv.content_length == 3
+        assert rv.headers["Content-Range"] == "bytes 2-4/10"
+        rv.direct_passthrough = False
+        assert rv.data == b"234"
+
+
+def test_range_not_satisfiable():
+    f = io.BytesIO(b"0123456789")
+
+    with pytest.raises(RequestedRangeNotSatisfiable):
+        send_file(f, create_environ(headers={"Range": "bytes=20-30"}))
+
+    assert f.closed
+
+
+def test_precondition_failed_closes_file():
+    f = io.BytesIO(b"test")
+
+    with pytest.raises(PreconditionFailed):
+        send_file(f, create_environ(headers={"If-Match": '"nope"'}), etag="other")
+
+    assert f.closed
+
+
+class _Unseekable:
+    """A minimal readable stream with no seek, tell, or fileno."""
+
+    def __init__(self, data):
+        self._io = io.BytesIO(data)
+
+    def read(self, size=-1):
+        return self._io.read(size)
+
+    def __iter__(self):
+        return iter(self._io.readline, b"")
+
+    def close(self):
+        self._io.close()
+
+
+def test_object_unseekable():
+    with send_file(_Unseekable(b"test"), environ) as rv:
+        assert rv.mimetype == "application/octet-stream"
+        assert rv.status_code == 200
+        assert "Content-Length" not in rv.headers
+        assert "ETag" not in rv.headers
+        rv.direct_passthrough = False
+        assert rv.data == b"test"
+
+
+def test_object_unseekable_range_ignored():
+    # The complete length is unknown, so the range can't be applied and the
+    # whole body is sent instead of failing.
+    range_environ = create_environ(headers={"Range": "bytes=1-2"})
+
+    with send_file(_Unseekable(b"test"), range_environ) as rv:
+        assert rv.status_code == 200
+        assert "Content-Range" not in rv.headers
+        rv.direct_passthrough = False
+        assert rv.data == b"test"
 
 
 def test_object_mimetype_from_name():
@@ -146,7 +236,12 @@ def test_max_age(value, public):
 
 def test_etag():
     with send_file(txt_path, environ) as rv:
-        assert rv.headers["ETag"].count("-") == 2
+        stat = txt_path.stat()
+        assert rv.headers["ETag"] == f'"{stat.st_mtime}-{stat.st_size}"'
+
+    # The path is not part of the ETag.
+    with send_file(txt_path, environ, download_name="other.txt") as rv:
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

`verdict` is `request_changes` if and only if there is at least one `blocking` finding.
