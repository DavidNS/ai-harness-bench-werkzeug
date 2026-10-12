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

## Task T4 (T4_shared_data)

Serve SharedDataMiddleware files through send_file, drop the default cache_timeout, and deprecate the cache and fallback_mimetype parameters. Update middleware tests.

Acceptance criteria:
- ACC13 [behavior]: SharedDataMiddleware serves files via send_file, supports 304 and range requests, and does not set Cache-Control max-age by default (cache_timeout default None).
- ACC14 [behavior]: Passing cache or fallback_mimetype to SharedDataMiddleware is still accepted but emits a DeprecationWarning.

Files declared for the task:
- src/werkzeug/middleware/shared_data.py (production)
- tests/middleware/test_shared_data.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/middleware/test_shared_data.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/src/werkzeug/middleware/shared_data.py b/src/werkzeug/middleware/shared_data.py
index c2810a01..96ea2871 100644
--- a/src/werkzeug/middleware/shared_data.py
+++ b/src/werkzeug/middleware/shared_data.py
@@ -17,18 +17,16 @@ import mimetypes
 import os
 import posixpath
 import typing as t
+import warnings
 from datetime import datetime
 from datetime import timezone
 from io import BytesIO
-from time import time
 from zlib import adler32
 
-from ..http import http_date
-from ..http import is_resource_modified
+from ..exceptions import HTTPException
 from ..security import safe_join
-from ..utils import get_content_type
+from ..utils import send_file
 from ..wsgi import get_path_info
-from ..wsgi import wrap_file
 
 _TOpener = t.Callable[[], tuple[t.IO[bytes], datetime, int]]
 _TLoader = t.Callable[[str | None], tuple[str | None, _TOpener | None]]
@@ -68,8 +66,7 @@ class SharedDataMiddleware:
     Python package.
 
     The optional `disallow` parameter can be a list of :func:`~fnmatch.fnmatch`
-    rules for files that are not accessible from the web.  If `cache` is set to
-    `False` no caching headers are sent.
+    rules for files that are not accessible from the web.
 
     Currently the middleware does not support non-ASCII filenames. If the
     encoding on the file system happens to match the encoding of the URI it may
@@ -77,16 +74,22 @@ class SharedDataMiddleware:
     only file names for static files.
 
     The middleware will guess the mimetype using the Python `mimetype`
-    module.  If it's unable to figure out the charset it will fall back
-    to `fallback_mimetype`.
+    module.  Files are served with :func:`~werkzeug.utils.send_file`, so
+    conditional and range requests are supported.
 
     :param app: the application to wrap.  If you don't want to wrap an
                 application you can pass it :exc:`NotFound`.
     :param exports: a list or dict of exported files and folders.
     :param disallow: a list of :func:`~fnmatch.fnmatch` rules.
-    :param cache: enable or disable caching headers.
+    :param cache: Deprecated. Enable or disable caching headers.
     :param cache_timeout: the cache timeout in seconds for the headers.
-    :param fallback_mimetype: The fallback mimetype for unknown files.
+        Not set by default, so clients revalidate using conditional requests.
+    :param fallback_mimetype: Deprecated. The fallback mimetype for
+        unknown files.
+
+    .. versionchanged:: 3.2
+        Files are served using ``send_file``. ``cache_timeout`` is not set
+        by default. ``cache`` and ``fallback_mimetype`` are deprecated.
 
     .. versionchanged:: 1.0
         The default ``fallback_mimetype`` is
@@ -108,10 +111,27 @@ class SharedDataMiddleware:
             | t.Iterable[tuple[str, str | tuple[str, str]]]
         ),
         disallow: None = None,
-        cache: bool = True,
-        cache_timeout: int = 60 * 60 * 12,
-        fallback_mimetype: str = "application/octet-stream",
+        cache: bool | None = None,
+        cache_timeout: int | None = None,
+        fallback_mimetype: str | None = None,
     ) -> None:
+        if cache is not None:
+            warnings.warn(
+                "The 'cache' parameter is deprecated and will be removed in"
+                " Werkzeug 3.3. Conditional caching is always enabled.",
+                DeprecationWarning,
+                stacklevel=2,
+            )
+
+        if fallback_mimetype is not None:
+            warnings.warn(
+                "The 'fallback_mimetype' parameter is deprecated and will be"
+                " removed in Werkzeug 3.3. Unknown types use"
+                " 'application/octet-stream'.",
+                DeprecationWarning,
+                stacklevel=2,
+            )
+
         self.app = app
         self.exports: list[tuple[str, _TLoader]] = []
         self.cache = cache
@@ -256,37 +276,30 @@ class SharedDataMiddleware:
         if file_loader is None or not self.is_allowed(real_filename):
             return self.app(environ, start_response)
 
-        guessed_type = (
-            mimetypes.guess_type(real_filename) if real_filename else (None, None)
-        )
-        mime_type = get_content_type(guessed_type[0] or self.fallback_mimetype, "utf-8")
         f, mtime, file_size = file_loader()
-
-        headers = [("Date", http_date())]
-
-        if self.cache:
-            timeout = self.cache_timeout
-            etag = f'"{self.generate_etag(mtime, file_size, real_filename)}"'
-            headers += [
-                ("ETag", etag),
-                ("Cache-Control", f"max-age={timeout}, public"),
-            ]
-
-            if not is_resource_modified(environ, etag, last_modified=mtime):
-                f.close()
-                start_response("304 Not Modified", headers)
-                return []
-
-            headers.append(("Expires", http_date(time() + timeout)))
-        else:
-            headers.append(("Cache-Control", "public"))
-
-        headers.extend(
-            (
-                ("Content-Type", mime_type),
-                ("Content-Length", str(file_size)),
-                ("Last-Modified", http_date(mtime)),
+        mimetype: str | None = None
+
+        if self.fallback_mimetype is not None and (
+            not real_filename or mimetypes.guess_type(real_filename)[0] is None
+        ):
+            mimetype = self.fallback_mimetype
+
+        try:
+            response = send_file(
+                f,
+                environ,
+                mimetype=mimetype,
+                download_name=real_filename,
+                etag=(
+                    self.generate_etag(mtime, file_size, real_filename)
+                    if self.cache is not False
+                    else False
+                ),
+                last_modified=mtime,
+                max_age=self.cache_timeout,
             )
-        )
-        start_response("200 OK", headers)
-        return wrap_file(environ, f)
+        except HTTPException as e:
+            # send_file closes the file when a precondition or range fails.
+            return e(environ, start_response)
+
+        return response(environ, start_response)
diff --git a/tests/middleware/test_shared_data.py b/tests/middleware/test_shared_data.py
index 26e64645..11fe7a20 100644
--- a/tests/middleware/test_shared_data.py
+++ b/tests/middleware/test_shared_data.py
@@ -1,11 +1,80 @@
 import os
 from contextlib import closing
 
+import pytest
+
+from werkzeug.datastructures import Headers
 from werkzeug.middleware.shared_data import SharedDataMiddleware
 from werkzeug.test import create_environ
 from werkzeug.test import run_wsgi_app
 
 
+def _serve(tmp_path, headers=None, path="/f/data.txt"):
+    data_file = tmp_path / "data.txt"
+
+    # Don't rewrite the file between calls, the ETag depends on its mtime.
+    if not data_file.exists():
+        data_file.write_bytes(b"0123456789")
+
+    app = SharedDataMiddleware(None, {"/f": str(tmp_path)})
+    environ = create_environ(path, headers=headers)
+    app_iter, status, response_headers = run_wsgi_app(app, environ)
+
+    with closing(app_iter):
+        body = b"".join(app_iter)
+
+    return status, Headers(response_headers), body
+
+
+def test_no_default_max_age(tmp_path):
+    status, headers, body = _serve(tmp_path)
+    assert status == "200 OK"
+    assert body == b"0123456789"
+    assert "max-age" not in headers["Cache-Control"]
+    assert "ETag" in headers
+    assert "Last-Modified" in headers
+
+
+def test_cache_timeout(tmp_path):
+    (tmp_path / "data.txt").write_bytes(b"x")
+    app = SharedDataMiddleware(None, {"/f": str(tmp_path)}, cache_timeout=60)
+    app_iter, status, headers = run_wsgi_app(app, create_environ("/f/data.txt"))
+    app_iter.close()
+    assert "max-age=60" in Headers(headers)["Cache-Control"]
+
+
+def test_not_modified(tmp_path):
+    _, headers, _ = _serve(tmp_path)
+    status, _, body = _serve(tmp_path, {"If-None-Match": headers["ETag"]})
+    assert status.startswith("304")
+    assert body == b""
+
+
+def test_range(tmp_path):
+    status, headers, body = _serve(tmp_path, {"Range": "bytes=2-4"})
+    assert status.startswith("206")
+    assert body == b"234"
+    assert headers["Content-Range"] == "bytes 2-4/10"
+
+
+def test_range_not_satisfiable(tmp_path):
+    status, _, _ = _serve(tmp_path, {"Range": "bytes=50-60"})
+    assert status.startswith("416")
+
+
+def test_precondition_failed(tmp_path):
+    status, _, _ = _serve(tmp_path, {"If-Match": '"nope"'})
+    assert status.startswith("412")
+
+
+def test_deprecated_parameters():
+    with pytest.deprecated_call():
+        SharedDataMiddleware(None, {}, cache=False)
+
+    with pytest.deprecated_call():
+        SharedDataMiddleware(None, {}, fallback_mimetype="text/plain")
+
+
 def test_get_file_loader():
     app = SharedDataMiddleware(None, {})
     assert callable(app.get_file_loader("foo"))

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
