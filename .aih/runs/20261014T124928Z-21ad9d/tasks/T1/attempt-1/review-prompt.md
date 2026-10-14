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



## Task T1 (T1)

Add apply_conditions/apply_range and IfRange.check, fix Range/ETagSet validation, then migrate send_file and SharedDataMiddleware and their tests, and deprecate make_conditional/is_resource_modified/is_byte_range_valid last (internal callers must stop using them first since warnings may be errors). Update docs and changelog.

Acceptance criteria:
- ACC1 [behavior]: apply_conditions raises PreconditionFailed for failed If-Match/If-Unmodified-Since on any method, and for If-None-Match matches on non-GET/HEAD; evaluates in RFC order; star ETag honors exists.
- ACC2 [behavior]: apply_conditions turns the response into 304 with entity headers removed when If-None-Match/If-Modified-Since is satisfied on GET/HEAD, and sets Accept-Ranges: bytes.
- ACC3 [behavior]: apply_range always sets Accept-Ranges: bytes; leaves response unchanged for non-GET, non-200, or unknown/zero Content-Length.
- ACC4 [behavior]: apply_range uses only the first range, clamps too-large stop/suffix, raises RequestedRangeNotSatisfiable when unsatisfiable, else 206 with sliced data and correct Content-Range; ignores non-bytes units.
- ACC5 [behavior]: apply_range honors If-Range by strong ETag or Last-Modified match, otherwise returns the full response.
- ACC6 [behavior]: make_conditional, is_resource_modified and is_byte_range_valid emit DeprecationWarning and still work.
- ACC7 [behavior]: Range.make_content_range clamps too-large stop and suffix, uses first range, validates without is_byte_range_valid; from_header methods reject invalid values; ETagSet.from_header discards unquoted values.
- ACC8 [behavior]: IfRange.check returns True for matching strong ETag or equal date, False otherwise.
- ACC9 [behavior]: send_file detects name/size/mtime from file-likes, seeks to 0, ETag has no path hash, and defaults to application/octet-stream without download_name.
- ACC10 [behavior]: SharedDataMiddleware serves via send_file, sets no max-age by default, supports conditional and range requests, and warns when cache or fallback_mimetype is passed.
- ACC11 [other]: Quickstart documents apply_conditions and apply_range; CHANGES.rst has an entry.
- ACC12 [behavior]: New tests cover apply_conditions and apply_range; send_file tests updated; deprecated-function tests moved/removed; pytest -m 'not dev_server' passes.

Files declared for the task:
- src/werkzeug/wrappers/response.py (production)
- src/werkzeug/http.py (production)
- src/werkzeug/sansio/http.py (production)
- src/werkzeug/datastructures/range.py (production)
- src/werkzeug/datastructures/etag.py (production)
- src/werkzeug/utils.py (production)
- src/werkzeug/middleware/shared_data.py (production)
- docs/quickstart.rst (production)
- docs/http.rst (production)
- CHANGES.rst (production)
- tests/test_wrappers.py (test)
- tests/test_http.py (test)
- tests/test_send_file.py (test)
- tests/middleware/test_shared_data.py (test)
- tests/test_datastructures.py (test)

Test files of this task that the change modified (existing tests, declared by the plan):
- tests/middleware/test_shared_data.py
- tests/test_datastructures.py
- tests/test_http.py
- tests/test_send_file.py
- tests/test_wrappers.py

Test results: selected tests green; red proven; suite green

## The diff

```diff
diff --git a/CHANGES.rst b/CHANGES.rst
index 995b7bf1..88a093e0 100644
--- a/CHANGES.rst
+++ b/CHANGES.rst
@@ -11,6 +11,23 @@ Version 3.2.0
 
 -   Minimum required version of MarkupSafe is 3.0.3.
 -   Minimum supported version of Watchdog is 6.0.
+-   Add ``Response.apply_conditions`` and ``apply_range``, which correctly
+    evaluate ``If-Match``, ``If-Unmodified-Since``, ``If-None-Match``,
+    ``If-Modified-Since``, ``Range``, and ``If-Range`` for all request methods
+    as described by RFC 9110. A failed precondition raises
+    ``PreconditionFailed``. ``Response.make_conditional``,
+    ``http.is_resource_modified``, and ``http.is_byte_range_valid`` are
+    deprecated. Add ``IfRange.check``. ``Range.make_content_range`` clamps
+    too-large values and validates its own values. :issue:`3291` :pr:`3308`
+
+    -   ``send_file`` uses the new methods. It detects the name, size, and
+        modification time from file-like objects, and seeks them to the start.
+        The ETag no longer includes a hash of the path. The mimetype defaults to
+        ``application/octet-stream`` instead of raising an error if
+        ``download_name`` is not given.
+    -   ``SharedDataMiddleware`` uses ``send_file``. ``cache_timeout`` is not
+        set by default, so conditional caching works. The ``cache`` and
+        ``fallback_mimetype`` parameters are deprecated.
 -   The CSP ``prefetch_src``, ``navigate_to``, and ``plugin_types`` properties
     are deprecated. Their corresponding directives have been deprecated or
     removed from the spec. :pr:`3114`
diff --git a/docs/quickstart.rst b/docs/quickstart.rst
index c7f5dc44..e73034b2 100644
--- a/docs/quickstart.rst
+++ b/docs/quickstart.rst
@@ -292,11 +292,30 @@ Finally if you have set all the conditional values, you can make the
 response conditional against a request.  Which means that if the request
 can assure that it has the information already, no data besides the headers
 is sent over the network which saves traffic.  For that you should set at
-least an ETag (which is used for comparison) and the date header and then
-call :class:`~Request.make_conditional` with the request object.
-
-The response is modified accordingly (status code changed, response body
-removed, entity headers removed etc.)
+least an ETag (which is used for comparison) or the ``Last-Modified`` date,
+and then call :meth:`.Response.apply_conditions` with the request object.
+
+The response is modified accordingly (status code changed to ``304``, response
+body removed, entity headers removed etc.) If a precondition such as
+``If-Match`` fails, :exc:`~werkzeug.exceptions.PreconditionFailed` is raised
+instead. This is checked for all request methods, and ``exists`` can be passed
+to say whether the resource exists, for the ``*`` ETag value.
+
+If the response has a known ``Content-Length``, call
+:meth:`.Response.apply_range` after that to handle a ``Range`` request. It
+always sets ``Accept-Ranges: bytes``. For a ``GET`` request with a satisfiable
+``Range``, the response is changed to ``206 Partial Content`` with the
+requested slice of the data. An unsatisfiable range raises
+:exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`.
+
+.. code-block:: python
+
+    response = Response(data)
+    response.add_etag()
+    response.apply_conditions(request)
+    response.apply_range(request)
+
+:meth:`.Response.make_conditional` is deprecated in favor of these two methods.
 
 
 Trusting Data
diff --git a/src/werkzeug/datastructures/range.py b/src/werkzeug/datastructures/range.py
index 4a680f40..f9c91ebf 100644
--- a/src/werkzeug/datastructures/range.py
+++ b/src/werkzeug/datastructures/range.py
@@ -4,9 +4,9 @@ import collections.abc as cabc
 import typing as t
 from datetime import datetime
 
+from .._internal import _dt_as_utc
 from .._internal import _plain_int
 from ..http import http_date
-from ..http import is_byte_range_valid
 from ..http import parse_date
 from .etag import ETag
 
@@ -63,6 +63,33 @@ class IfRange:
 
         return ""
 
+    def check(self, etag: ETag | str | None, last_modified: datetime | None) -> bool:
+        """Check whether the ``If-Range`` condition is met by the response's
+        values. Only a strong ETag equal to the condition, or a date equal to
+        the last modified time, meets it.
+
+        :param etag: The response's ETag. A ``str`` is assumed to be an
+            unquoted strong value.
+        :param last_modified: The response's last modified time.
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
+            return etag is not None and self.etag == etag
+
+        if self.date is not None and last_modified is not None:
+            # HTTP dates don't have microseconds, naive datetimes are UTC.
+            last_modified = _dt_as_utc(last_modified.replace(microsecond=0))
+            return self.date == last_modified
+
+        return False
+
     def __bool__(self) -> bool:
         return self.etag is not None or self.date is not None
 
@@ -108,7 +135,7 @@ class Range:
         if a valid range cannot be constructed.
 
         This will generate a range regardless of the value of :attr:`units`.
-        However, :meth:`.Response.make_conditional` can only handle ``bytes``.
+        However, :meth:`.Response.apply_range` can only handle ``bytes``.
 
         If there are multiple ranges in the header, this will only return the
         first range.
@@ -145,22 +172,26 @@ class Range:
             stop = length
 
             if start < 0:
-                start += length
+                # A suffix longer than the content selects all of it.
+                start = max(0, start + length)
+        else:
+            stop = min(stop, length)
 
-        if not is_byte_range_valid(start, stop, length):
+        if not 0 <= start < stop:
             return None
 
-        return start, min(stop, length)
+        return start, stop
 
     def make_content_range(self, length: int | None) -> ContentRange | None:
         """Create a :class:`.ContentRange` with the given complete length. Or
         ``None`` if a valid range cannot be constructed.
 
         This will generate a range regardless of the value of :attr:`units`.
-        However, :meth:`.Response.make_conditional` can only handle ``bytes``.
+        However, :meth:`.Response.apply_range` can only handle ``bytes``.
 
         If there are multiple ranges in the header, this will only return the
-        first range.
+        first range. A ``stop`` or suffix length that is too large is clamped
+        to the complete length.
 
         .. versionchanged:: 3.2
             Allows units other than ``bytes``. Will return the first range if
diff --git a/src/werkzeug/http.py b/src/werkzeug/http.py
index da7fba49..dc4f3ecd 100644
--- a/src/werkzeug/http.py
+++ b/src/werkzeug/http.py
@@ -1166,9 +1166,21 @@ def is_resource_modified(
                             account.
     :return: `True` if the resource was modified, otherwise `False`.
 
+    .. deprecated:: 3.2
+        Will be removed in Werkzeug 4.0. Use ``Response.apply_conditions`` and
+        ``Response.apply_range`` instead.
+
     .. versionchanged:: 1.0
         The check is run for methods other than ``GET`` and ``HEAD``.
     """
+    import warnings
+
+    warnings.warn(
+        "'is_resource_modified' is deprecated and will be removed in Werkzeug 4.0."
+        " Use 'Response.apply_conditions' and 'Response.apply_range' instead.",
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
+        Will be removed in Werkzeug 4.0. ``Range.make_content_range`` validates
+        its own values.
+
     .. versionadded:: 0.7
     """
+    import warnings
+
+    warnings.warn(
+        "'is_byte_range_valid' is deprecated and will be removed in Werkzeug 4.0."
+        " 'Range.make_content_range' validates its own values.",
+        DeprecationWarning,
+        stacklevel=2,
+    )
+
     if (start is None) != (stop is None):
         return False
     elif start is None:
diff --git a/src/werkzeug/middleware/shared_data.py b/src/werkzeug/middleware/shared_data.py
index c2810a01..a39051ee 100644
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
@@ -84,9 +81,17 @@ class SharedDataMiddleware:
                 application you can pass it :exc:`NotFound`.
     :param exports: a list or dict of exported files and folders.
     :param disallow: a list of :func:`~fnmatch.fnmatch` rules.
-    :param cache: enable or disable caching headers.
-    :param cache_timeout: the cache timeout in seconds for the headers.
-    :param fallback_mimetype: The fallback mimetype for unknown files.
+    :param cache: Deprecated, has no effect.
+    :param cache_timeout: the cache timeout in seconds for the headers. Not set
+        by default, so clients use conditional caching.
+    :param fallback_mimetype: Deprecated. The fallback mimetype for unknown
+        files.
+
+    .. versionchanged:: 3.2
+        Files are served using :func:`~werkzeug.utils.send_file`, so conditional
+        and range requests are supported. ``cache_timeout`` is not set by
+        default. The ``cache`` and ``fallback_mimetype`` parameters are
+        deprecated.
 
     .. versionchanged:: 1.0
         The default ``fallback_mimetype`` is
@@ -108,13 +113,31 @@ class SharedDataMiddleware:
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
+                " Werkzeug 4.0. Caching headers are always sent.",
+                DeprecationWarning,
+                stacklevel=2,
+            )
+
+        if fallback_mimetype is not None:
+            warnings.warn(
+                "The 'fallback_mimetype' parameter is deprecated and will be"
+                " removed in Werkzeug 4.0. It will always be"
+                " 'application/octet-stream'.",
+                DeprecationWarning,
+                stacklevel=2,
+            )
+        else:
+            fallback_mimetype = "application/octet-stream"
+
         self.app = app
         self.exports: list[tuple[str, _TLoader]] = []
-        self.cache = cache
         self.cache_timeout = cache_timeout
 
         if isinstance(exports, cabc.Mapping):
@@ -259,34 +282,20 @@ class SharedDataMiddleware:
         guessed_type = (
             mimetypes.guess_type(real_filename) if real_filename else (None, None)
         )
-        mime_type = get_content_type(guessed_type[0] or self.fallback_mimetype, "utf-8")
+        mimetype = guessed_type[0] or self.fallback_mimetype
         f, mtime, file_size = file_loader()
 
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
+        try:
+            rv = send_file(
+                f,
+                environ,
+                mimetype=mimetype,
+                download_name=real_filename,
+                etag=self.generate_etag(mtime, file_size, real_filename),
+                last_modified=mtime,
+                max_age=self.cache_timeout,
             )
-        )
-        start_response("200 OK", headers)
-        return wrap_file(environ, f)
+        except HTTPException as e:
+            return e(environ, start_response)
+
+        return rv(environ, start_response)
diff --git a/src/werkzeug/utils.py b/src/werkzeug/utils.py
index df4f7232..9f1b3f55 100644
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
@@ -334,11 +334,12 @@ def send_file(
 
     :param path_or_file: The path to the file to send, relative to the
         current working directory if a relative path is given.
-        Alternatively, a file-like object opened in binary mode. Make
-        sure the file pointer is seeked to the start of the data.
+        Alternatively, a file-like object opened in binary mode. It is
+        seeked to the start of the data.
     :param environ: The WSGI environ for the current request.
     :param mimetype: The MIME type to send for the file. If not
-        provided, it will try to detect it from the file name.
+        provided, it will try to detect it from the file name, falling
+        back to ``application/octet-stream``.
     :param as_attachment: Indicate to a browser that it should offer to
         save the file instead of displaying it.
     :param download_name: The default name browsers will use when saving
@@ -361,6 +362,14 @@ def send_file(
     :param _root_path: Do not use. For internal use only. Use
         :func:`send_from_directory` to safely send files under a path.
 
+    .. versionchanged:: 3.2
+        The name, size, and modification time are detected from a file-like
+        object when possible. File-like objects are seeked to the start. The
+        ETag no longer includes a hash of the path. The mimetype defaults to
+        ``application/octet-stream`` instead of raising an error if
+        ``download_name`` is not given. Uses ``Response.apply_conditions`` and
+        ``Response.apply_range``.
+
     .. versionchanged:: 2.0.2
         ``send_file`` only sets a detected ``Content-Encoding`` if
         ``as_attachment`` is disabled.
@@ -415,26 +424,46 @@ def send_file(
     else:
         file = path_or_file
 
+        if isinstance(file, io.TextIOBase):
+            raise ValueError("Files must be opened in binary mode or use BytesIO.")
+
+        name = getattr(file, "name", None)
+
+        if download_name is None and isinstance(name, str):
+            download_name = os.path.basename(name)
+
+        try:
+            stat = os.fstat(file.fileno())
+        except (AttributeError, OSError):
+            stat = None
+
+        if stat is not None and S_ISREG(stat.st_mode):
+            size = stat.st_size
+            mtime = stat.st_mtime
+        elif isinstance(file, io.BytesIO):
+            size = file.getbuffer().nbytes
+
+        try:
+            file.seek(0)
+        except (AttributeError, OSError):
+            pass
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
+        mimetype = "application/octet-stream"
 
-        mimetype, encoding = mimetypes.guess_type(download_name)
+        if download_name is not None:
+            guessed, encoding = mimetypes.guess_type(download_name)
 
-        if mimetype is None:
-            mimetype = "application/octet-stream"
+            if guessed is not None:
+                mimetype = guessed
 
-        # Don't send encoding for attachments, it causes browsers to
-        # save decompress tar.gz files.
-        if encoding is not None and not as_attachment:
-            headers.set("Content-Encoding", encoding)
+            # Don't send encoding for attachments, it causes browsers to
+            # save decompress tar.gz files.
+            if encoding is not None and not as_attachment:
+                headers.set("Content-Encoding", encoding)
 
     if download_name is not None:
         try:
@@ -462,10 +491,6 @@ def send_file(
     else:
         if file is None:
             file = open(path, "rb")  # type: ignore[arg-type]
-        elif isinstance(file, io.BytesIO):
-            size = file.getbuffer().nbytes
-        elif isinstance(file, io.TextIOBase):
-            raise ValueError("Files must be opened in binary mode or use BytesIO.")
 
         data = wrap_file(environ, file)
 
@@ -498,14 +523,18 @@ def send_file(
 
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
 
diff --git a/src/werkzeug/wrappers/response.py b/src/werkzeug/wrappers/response.py
index ba2a15fb..82e209cc 100644
--- a/src/werkzeug/wrappers/response.py
+++ b/src/werkzeug/wrappers/response.py
@@ -7,12 +7,9 @@ from types import TracebackType
 from urllib.parse import urljoin
 
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
@@ -655,72 +652,110 @@ class Response(_SansIOResponse):
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
+    def apply_conditions(self, request: Request, *, exists: bool = True) -> None:
+        """Evaluate the request's precondition headers against this response's
+        ``ETag`` and ``Last-Modified``, in the order defined by :rfc:`9110`:
+        ``If-Match``, ``If-Unmodified-Since``, ``If-None-Match``, then
+        ``If-Modified-Since``. This applies to all request methods.
 
-        Returns ``True`` if Range Request can be fulfilled, ``False`` otherwise.
+        A failed precondition raises :exc:`~werkzeug.exceptions.PreconditionFailed`.
+        A satisfied ``If-None-Match`` or ``If-Modified-Since`` on a ``GET`` or
+        ``HEAD`` request changes the response to ``304 Not Modified``, the
+        entity headers are removed when the response is sent. Sets the
+        ``Accept-Ranges`` header to ``bytes``.
 
-        :raises: :class:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`
-                 if `Range` header could not be parsed or satisfied.
+        Call :meth:`apply_range` after this to handle a ``Range`` header.
 
-        .. versionchanged:: 3.2
-            Adds the ``Accept-Ranges`` header if ``accept_ranges`` is passed,
-            even if this is not a satisfiable range request.
+        :param request: The request to check the preconditions of.
+        :param exists: Whether the resource already exists. A ``*`` value in
+            ``If-Match`` only matches an existing resource, and a ``*`` value in
+            ``If-None-Match`` only matches if the resource exists.
+        :raises: :exc:`~werkzeug.exceptions.PreconditionFailed`
 
-        .. versionchanged:: 2.0
-            Returns ``False`` if the length is 0.
+        .. versionadded:: 3.2
+        """
+        from ..exceptions import PreconditionFailed
+
+        self.accept_ranges = "bytes"
+        etag = self.etag
+        last_modified = self.last_modified
+        is_get = request.method in {"GET", "HEAD"}
+
+        if if_match := request.if_match:
+            # Strong comparison.
+            if not (exists if if_match.star_tag else if_match.contains_strong(etag)):
+                raise PreconditionFailed()
+        elif (
+            (since := request.if_unmodified_since) is not None
+            and last_modified is not None
+            and last_modified > since
+        ):
+            raise PreconditionFailed()
+
+        if if_none_match := request.if_none_match:
+            # Weak comparison.
+            if exists if if_none_match.star_tag else if_none_match.contains_weak(etag):
+                if not is_get:
+                    raise PreconditionFailed()
+
+                self.status_code = 304
+        elif (
+            is_get
+            and (since := request.if_modified_since) is not None
+            and last_modified is not None
+            and last_modified <= since
+        ):
+            self.status_code = 304
+
+    def apply_range(self, request: Request) -> None:
+        """Apply the request's ``Range`` header, after :meth:`apply_conditions`.
+        Always sets the ``Accept-Ranges`` header to ``bytes``.
+
+        The range is only applied to ``GET`` requests with a ``200`` response
+        that has a known, non-zero ``Content-Length``, which is used as the
+        complete length. Otherwise the response is not changed. Only the
+        ``bytes`` unit is supported. If multiple ranges are given, only the first
+        is used. A ``stop`` or suffix length that is too large is clamped to the
+        complete length. If the request has an ``If-Range`` header, the range is
+        only applied if the condition matches the response's ``ETag`` or
+        ``Last-Modified``.
+
+        A satisfiable range changes the response to ``206 Partial Content``
+        with the sliced data and a ``Content-Range`` header. For best
+        performance, the response data should be a seekable file, such as one
+        returned by :func:`~werkzeug.wsgi.wrap_file`.
+
+        :param request: The request to get the range from.
+        :raises: :exc:`~werkzeug.exceptions.RequestedRangeNotSatisfiable`
+
+        .. versionadded:: 3.2
         """
         from ..exceptions import RequestedRangeNotSatisfiable
 
-        if not accept_ranges:
-            return False
-
-        if accept_ranges is True:
-            accept_ranges = "bytes"
+        self.accept_ranges = "bytes"
 
-        self.accept_ranges = accept_ranges
-
-        if not (complete_length and self._is_range_request_processable(environ)):
-            return False
-
-        parsed_range = Range.from_header(environ.get("HTTP_RANGE"))
-
-        if parsed_range is None:
-            raise RequestedRangeNotSatisfiable(complete_length)
+        if (
+            request.method != "GET"
+            or self.status_code != 200
+            or not (length := self.content_length)
+            or (range_ := request.range) is None
+            or range_.units != "bytes"
+        ):
+            return
 
-        content_range = parsed_range.make_content_range(complete_length)
+        if (if_range := request.if_range) and not if_range.check(
+            self.etag, self.last_modified
+        ):
+            return
 
-        if content_range is None:
-            raise RequestedRangeNotSatisfiable(complete_length)
+        if (content_range := range_.make_content_range(length)) is None:
+            raise RequestedRangeNotSatisfiable(length)
 
         content_length = content_range.stop - content_range.start  # type: ignore[operator]
         self.content_length = content_length
         self.content_range = content_range
         self.status_code = 206
         self._wrap_range_response(content_range.start, content_length)  # type: ignore[arg-type]
-        return True
 
     def make_conditional(
         self,
@@ -763,7 +798,11 @@ class Response(_SansIOResponse):
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
 
@@ -771,24 +810,49 @@ class Response(_SansIOResponse):
             Range processing is skipped if length is 0 instead of
             raising a 416 Range Not Satisfiable error.
         """
-        environ = _get_environ(request_or_environ)
-        if environ["REQUEST_METHOD"] in ("GET", "HEAD"):
+        import warnings
+
+        from ..exceptions import PreconditionFailed
+        from .request import Request
+
+        warnings.warn(
+            "'make_conditional' is deprecated and will be removed in Werkzeug 4.0."
+            " Use 'apply_conditions' and 'apply_range' instead.",
+            DeprecationWarning,
+            stacklevel=2,
+        )
+
+        if isinstance(request_or_environ, Request):
+            request = request_or_environ
+        else:
+            request = Request(_get_environ(request_or_environ))
+
+        if request.method in ("GET", "HEAD"):
             # if the date is not in the headers, add it now.  We however
             # will not override an already existing header.  Unfortunately
             # this header will be overridden by many WSGI servers including
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
+            old_accept_ranges = self.accept_ranges
+
+            try:
+                self.apply_conditions(request)
+            except PreconditionFailed:
+                self.status_code = 412
+
+            if accept_ranges:
+                if complete_length is not None and self.content_length is None:
+                    self.content_length = complete_length
+
+                self.apply_range(request)
+
+                if accept_ranges is not True:
+                    self.accept_ranges = accept_ranges
+            else:
+                self.accept_ranges = old_accept_ranges
+
             if (
                 self.automatically_set_content_length
                 and "Content-Length" not in self.headers
diff --git a/tests/middleware/test_shared_data.py b/tests/middleware/test_shared_data.py
index 26e64645..e195316b 100644
--- a/tests/middleware/test_shared_data.py
+++ b/tests/middleware/test_shared_data.py
@@ -1,11 +1,94 @@
 import os
 from contextlib import closing
 
+import pytest
+
 from werkzeug.middleware.shared_data import SharedDataMiddleware
 from werkzeug.test import create_environ
 from werkzeug.test import run_wsgi_app
 
 
+def _serve(app, path="/test.txt", **headers):
+    app_iter, status, response_headers = run_wsgi_app(
+        app, create_environ(path, headers=headers)
+    )
+
+    with closing(app_iter) as app_iter:
+        data = b"".join(app_iter)
+
+    return status, response_headers, data
+
+
+@pytest.fixture
+def app():
+    res = os.path.join(os.path.dirname(__file__), "..", "res")
+    return SharedDataMiddleware(None, {"/": res})
+
+
+def test_no_max_age_by_default(app):
+    status, headers, data = _serve(app)
+    assert status == "200 OK"
+    headers = dict(headers)
+    assert "max-age" not in headers["Cache-Control"]
+    assert "no-cache" in headers["Cache-Control"]
+    assert "ETag" in headers
+    assert "Last-Modified" in headers
+    assert data.strip() == b"FOUND"
+
+
+def test_cache_timeout():
+    res = os.path.join(os.path.dirname(__file__), "..", "res")
+    app = SharedDataMiddleware(None, {"/": res}, cache_timeout=60)
+    status, headers, data = _serve(app)
+    assert "max-age=60" in dict(headers)["Cache-Control"]
+
+
+def test_conditional(app):
+    _, headers, _ = _serve(app)
+    etag = dict(headers)["ETag"]
+    status, headers, data = _serve(app, **{"If-None-Match": etag})
+    assert status == "304 Not Modified"
+    assert data == b""
+
+    status, headers, data = _serve(app, **{"If-Match": '"nope"'})
+    assert status == "412 Precondition Failed"
+
+
+def test_range(app):
+    status, headers, data = _serve(app, Range="bytes=0-1")
+    assert status == "206 Partial Content"
+    assert dict(headers)["Content-Range"].startswith("bytes 0-1/")
+    assert data == b"FO"
+
+
+def test_range_not_satisfiable(app):
+    status, headers, data = _serve(app, Range="bytes=1000-")
+    assert status == "416 Requested Range Not Satisfiable"
+    assert dict(headers)["Content-Range"].startswith("bytes */")
+
+
+def test_fallback_mimetype_default(tmp_path):
+    (tmp_path / "data.unknownext").write_bytes(b"x")
+    app = SharedDataMiddleware(None, {"/": str(tmp_path)})
+    status, headers, data = _serve(app, "/data.unknownext")
+    assert dict(headers)["Content-Type"] == "application/octet-stream"
+
+
+def test_deprecated_parameters(tmp_path):
+    (tmp_path / "data.unknownext").write_bytes(b"x")
+
+    with pytest.deprecated_call(match="'cache'"):
+        SharedDataMiddleware(None, {}, cache=False)
+
+    with pytest.deprecated_call(match="'fallback_mimetype'"):
+        app = SharedDataMiddleware(
+            None, {"/": str(tmp_path)}, fallback_mimetype="application/x-test"
+        )
+
+    status, headers, data = _serve(app, "/data.unknownext")
+    assert dict(headers)["Content-Type"] == "application/x-test"
+
+
 def test_get_file_loader():
     app = SharedDataMiddleware(None, {})
     assert callable(app.get_file_loader("foo"))
diff --git a/tests/test_datastructures.py b/tests/test_datastructures.py
index 0136ce15..d90f151b 100644
--- a/tests/test_datastructures.py
+++ b/tests/test_datastructures.py
@@ -7,6 +7,8 @@ import typing as t
 from contextlib import contextmanager
 from copy import copy
 from copy import deepcopy
+from datetime import datetime
+from datetime import timezone
 
 import pytest
 
@@ -1098,3 +1100,84 @@ def test_etag_strong_comparison(header: ETagSet, etag: ETag, expect: bool) -> No
 )
 def test_etag_weak_comparison(header: ETagSet, etag: ETag, expect: bool) -> None:
     assert header.contains_weak(etag) is expect
+
+
+def test_etag_set_discards_unquoted() -> None:
+    header = ETagSet.from_header('abc, "def", W/ghi, W/"jkl"')
+    assert header.contains_strong("def")
+    assert header.contains_weak("jkl")
+    assert not header.contains_weak("abc")
+    assert not header.contains_weak("ghi")
+
+
+@pytest.mark.parametrize(
+    ("header", "length", "expect"),
+    [
+        ("bytes=0-4", 11, (0, 5)),
+        ("bytes=6-666", 11, (6, 11)),
+        ("bytes=6-", 11, (6, 11)),
+        ("bytes=-5", 11, (6, 11)),
+        ("bytes=-666", 11, (0, 11)),
+        ("bytes=0-1, 4-5", 11, (0, 2)),
+        ("bytes=11-", 11, None),
+        ("bytes=11-20", 11, None),
+        ("bytes=0-", 0, None),
+        ("bytes=-5", 0, None),
+        ("bytes=0-4", None, None),
+    ],
+)
+def test_make_content_range(
+    header: str, length: int | None, expect: tuple[int, int] | None
+) -> None:
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
+def test_make_content_range_no_ranges() -> None:
+    assert ds.Range("bytes", []).make_content_range(10) is None
+
+
+_modified = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
+
+
+@pytest.mark.parametrize(
+    ("if_range", "etag", "last_modified", "expect"),
+    [
+        pytest.param(ds.IfRange("a"), ETag("a"), None, True, id="etag, same"),
+        pytest.param(ds.IfRange("a"), "a", None, True, id="etag, str"),
+        pytest.param(ds.IfRange("a"), ETag("b"), None, False, id="etag, different"),
+        pytest.param(ds.IfRange("a"), ETag("a", True), None, False, id="etag, weak"),
+        pytest.param(ds.IfRange("a"), None, _modified, False, id="etag, missing"),
+        pytest.param(ds.IfRange(date=_modified), None, _modified, True, id="date"),
+        pytest.param(
+            ds.IfRange(date=_modified),
+            None,
+            _modified.replace(microsecond=5, tzinfo=None),
+            True,
+            id="date, naive microsecond",
+        ),
+        pytest.param(
+            ds.IfRange(date=_modified),
+            None,
+            _modified.replace(day=3),
+            False,
+            id="date, different",
+        ),
+        pytest.param(ds.IfRange(date=_modified), None, None, False, id="date, missing"),
+        pytest.param(ds.IfRange(), ETag("a"), _modified, False, id="empty"),
+    ],
+)
+def test_if_range_check(
+    if_range: ds.IfRange,
+    etag: ETag | str | None,
+    last_modified: datetime | None,
+    expect: bool,
+) -> None:
+    assert if_range.check(etag, last_modified) is expect
diff --git a/tests/test_http.py b/tests/test_http.py
index d0bf0e85..4812f96f 100644
--- a/tests/test_http.py
+++ b/tests/test_http.py
@@ -403,6 +403,21 @@ class TestHTTPUtility:
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
+            assert not http.is_byte_range_valid(0, None, 10)
+
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified(self):
         env = create_environ()
 
@@ -428,6 +443,7 @@ class TestHTTPUtility:
             env, last_modified=datetime(2008, 1, 1, 13, 00)
         )
 
+    @pytest.mark.filterwarnings("ignore:'is_resource_modified':DeprecationWarning")
     def test_is_resource_modified_for_range_requests(self):
         env = create_environ()
 
diff --git a/tests/test_send_file.py b/tests/test_send_file.py
index 6143e0ed..ea176006 100644
--- a/tests/test_send_file.py
+++ b/tests/test_send_file.py
@@ -1,10 +1,13 @@
 import datetime
 import io
+import os
 import pathlib
 
 import pytest
 
 from werkzeug.exceptions import NotFound
+from werkzeug.exceptions import PreconditionFailed
+from werkzeug.exceptions import RequestedRangeNotSatisfiable
 from werkzeug.http import http_date
 from werkzeug.test import create_environ
 from werkzeug.utils import send_file
@@ -52,8 +55,127 @@ def test_object(file_factory):
 
 
 def test_object_without_mimetype():
-    with pytest.raises(TypeError, match="detect the MIME type"):
-        send_file(io.BytesIO(b"test"), environ)
+    with send_file(io.BytesIO(b"test"), environ) as rv:
+        assert rv.mimetype == "application/octet-stream"
+        assert "Content-Disposition" not in rv.headers
+
+
+def test_object_detects_name_size_mtime():
+    with txt_path.open("rb") as f, send_file(f, environ) as rv:
+        assert rv.mimetype == "text/plain"
+        assert rv.headers["Content-Disposition"] == "inline; filename=test.txt"
+        assert rv.content_length == txt_path.stat().st_size
+        assert rv.last_modified is not None
+        assert rv.last_modified.timestamp() == int(txt_path.stat().st_mtime)
+        assert rv.etag is not None
+
+
+def test_object_download_name_overrides_detected_name():
+    with txt_path.open("rb") as f, send_file(f, environ, download_name="a.html") as rv:
+        assert rv.mimetype == "text/html"
+
+
+def test_object_bytesio_size():
+    with send_file(io.BytesIO(b"test"), environ) as rv:
+        assert rv.content_length == 4
+        assert rv.last_modified is None
+        assert rv.etag is None
+
+
+def test_object_unknown_size():
+    r, w = os.pipe()
+
+    with os.fdopen(r, "rb") as f, send_file(f, environ) as rv:
+        assert rv.content_length is None
+        assert rv.last_modified is None
+        assert rv.etag is None
+
+    os.close(w)
+
+
+def test_object_without_fileno_or_seek():
+    class Reader:
+        def read(self, size=-1):
+            return b""
+
+    with send_file(Reader(), environ) as rv:
+        assert rv.content_length is None
+
+
+def test_object_seeks_to_start():
+    f = io.BytesIO(b"Hello World")
+    f.read()
+
+    with send_file(f, environ) as rv:
+        rv.direct_passthrough = False
+        assert rv.data == b"Hello World"
+
+    with txt_path.open("rb") as f:
+        f.read()
+
+        with send_file(f, environ) as rv:
+            rv.direct_passthrough = False
+            assert rv.data.strip() == b"FOUND"
+
+
+def test_object_range():
+    f = io.BytesIO(b"Hello World")
+    f.read(3)
+    env = create_environ(headers={"Range": "bytes=6-"})
+
+    with send_file(f, env) as rv:
+        assert rv.status_code == 206
+        assert rv.headers["Content-Range"] == "bytes 6-10/11"
+        assert rv.content_length == 5
+        rv.direct_passthrough = False
+        assert rv.data == b"World"
+
+
+def test_path_range():
+    env = create_environ(headers={"Range": "bytes=0-1"})
+
+    with send_file(txt_path, env) as rv:
+        assert rv.status_code == 206
+        assert rv.headers["Accept-Ranges"] == "bytes"
+        assert rv.headers["Content-Range"] == f"bytes 0-1/{txt_path.stat().st_size}"
+        rv.direct_passthrough = False
+        assert rv.data == b"FO"
+
+
+def test_range_not_satisfiable_closes_file():
+    f = io.BytesIO(b"Hello World")
+    env = create_environ(headers={"Range": "bytes=20-"})
+
+    with pytest.raises(RequestedRangeNotSatisfiable):
+        send_file(f, env)
+
+    assert f.closed
+
+
+def test_precondition_failed_closes_file():
+    f = io.BytesIO(b"Hello World")
+    env = create_environ(headers={"If-Match": '"nope"'})
+
+    with pytest.raises(PreconditionFailed):
+        send_file(f, env, etag="abc")
+
+    assert f.closed
+
+
+def test_if_none_match_not_modified():
+    env = create_environ(headers={"If-None-Match": '"abc"'})
+
+    with send_file(txt_path, env, etag="abc", use_x_sendfile=True) as rv:
+        assert rv.status_code == 304
+        assert "X-Sendfile" not in rv.headers
+
+
+def test_not_conditional():
+    env = create_environ(headers={"If-None-Match": '"abc"', "Range": "bytes=0-1"})
+
+    with send_file(txt_path, env, etag="abc", conditional=False) as rv:
+        assert rv.status_code == 200
+        assert "Accept-Ranges" not in rv.headers
 
 
 def test_object_mimetype_from_name():
@@ -146,7 +268,8 @@ def test_max_age(value, public):
 
 def test_etag():
     with send_file(txt_path, environ) as rv:
-        assert rv.headers["ETag"].count("-") == 2
+        stat = txt_path.stat()
+        assert rv.headers["ETag"] == f'"{stat.st_mtime}-{stat.st_size}"'
 
     with send_file(txt_path, environ, etag=False) as rv:
         assert "ETag" not in rv.headers
diff --git a/tests/test_wrappers.py b/tests/test_wrappers.py
index 0960e588..591e995c 100644
--- a/tests/test_wrappers.py
+++ b/tests/test_wrappers.py
@@ -18,12 +18,14 @@ from werkzeug.datastructures import MIMEAccept
 from werkzeug.datastructures import MultiDict
 from werkzeug.datastructures import WWWAuthenticate
 from werkzeug.exceptions import BadRequest
+from werkzeug.exceptions import PreconditionFailed
 from werkzeug.exceptions import RequestedRangeNotSatisfiable
 from werkzeug.exceptions import SecurityError
 from werkzeug.exceptions import UnsupportedMediaType
 from werkzeug.http import COEP
 from werkzeug.http import COOP
 from werkzeug.http import generate_etag
+from werkzeug.http import http_date
 from werkzeug.test import Client
 from werkzeug.test import create_environ
 from werkzeug.test import run_wsgi_app
@@ -523,91 +525,229 @@ def test_etag_response():
         "max-age=60, must-revalidate",
     )
 
-    assert "Date" not in response.headers
-    env = create_environ()
-    env.update(
-        {"REQUEST_METHOD": "GET", "HTTP_IF_NONE_MATCH": response.headers["ETag"]}
+    request = wrappers.Request.from_values(
+        headers={"If-None-Match": response.headers["ETag"]}
     )
-    response.make_conditional(env)
-    assert "Date" in response.headers
+    response.apply_conditions(request)
+    assert response.status_code == 304
+    assert response.headers["Accept-Ranges"] == "bytes"
 
     # after the thing is invoked by the server as wsgi application
     # (we're emulating this here), there must not be any entity
-    # headers left and the status code would have to be 304
-    resp = wrappers.Response.from_app(response, env)
+    # headers left
+    resp = wrappers.Response.from_app(response, request.environ)
     assert resp.status_code == 304
     assert "Content-Length" not in resp.headers
 
-    # make sure date is not overridden
-    response = wrappers.Response("Hello World")
-    response.date = 1337
-    d = response.date
-    response.make_conditional(env)
-    assert response.date == d
 
-    # make sure content length is only set if missing
-    response = wrappers.Response("Hello World")
-    response.content_length = 999
-    response.make_conditional(env)
-    assert response.content_length == 999
+def _request(method="GET", **headers):
+    return wrappers.Request.from_values(method=method, headers=headers)
 
 
-def test_etag_response_412():
+def _response(etag=None, last_modified=None):
     response = wrappers.Response("Hello World")
-    assert response.etag is None
-    response.add_etag()
-    assert response.etag.value == "4Wf2jWVj11uyXzqknCnvYS1BNS3ABgbefL1jC7JmX1E"
-    assert not response.cache_control
-    response.cache_control.must_revalidate = True
-    response.cache_control.max_age = 60
-    response.headers["Content-Length"] = len(response.get_data())
-    assert response.headers["Cache-Control"] in (
-        "must-revalidate, max-age=60",
-        "max-age=60, must-revalidate",
+
+    if etag is not None:
+        response.etag = etag
+
+    if last_modified is not None:
+        response.last_modified = last_modified
+
+    return response
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
+def test_apply_conditions_if_match(method):
+    response = _response("abc")
+    response.apply_conditions(_request(method, **{"If-Match": '"abc"'}))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+
+    response.apply_conditions(_request(method, **{"If-Match": '"x", "abc"'}))
+    assert response.status_code == 200
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_request(method, **{"If-Match": '"xyz"'}))
+
+    # weak comparison is not allowed
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(_request(method, **{"If-Match": 'W/"abc"'}))
+
+    # response without an ETag never matches
+    with pytest.raises(PreconditionFailed):
+        _response().apply_conditions(_request(method, **{"If-Match": '"abc"'}))
+
+
+@pytest.mark.parametrize("method", ["GET", "POST"])
+@pytest.mark.parametrize(("exists", "ok"), [(True, True), (False, False)])
+def test_apply_conditions_if_match_star(method, exists, ok):
+    response = _response("abc")
+    request = _request(method, **{"If-Match": "*"})
+
+    if ok:
+        response.apply_conditions(request, exists=exists)
+        assert response.status_code == 200
+    else:
+        with pytest.raises(PreconditionFailed):
+            response.apply_conditions(request, exists=exists)
+
+
+@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
+def test_apply_conditions_if_unmodified_since(method):
+    modified = datetime(2024, 1, 2, tzinfo=timezone.utc)
+    response = _response(last_modified=modified)
+    response.apply_conditions(
+        _request(method, **{"If-Unmodified-Since": http_date(modified)})
     )
+    assert response.status_code == 200
 
-    assert "Date" not in response.headers
-    env = create_environ()
-    env.update({"REQUEST_METHOD": "GET", "HTTP_IF_MATCH": '"xyz"'})
-    response.make_conditional(env)
-    assert "Date" in response.headers
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _request(method, **{"If-Unmodified-Since": http_date(datetime(2024, 1, 1))})
+        )
 
-    # after the thing is invoked by the server as wsgi application
-    # (we're emulating this here), there must not be any entity
-    # headers left and the status code would have to be 412
-    resp = wrappers.Response.from_app(response, env)
-    assert resp.status_code == 412
-    # Make sure there is a body still
-    assert resp.data != b""
+    # not evaluated if the response has no modification time
+    response = _response()
+    response.apply_conditions(
+        _request(method, **{"If-Unmodified-Since": http_date(modified)})
+    )
+    assert response.status_code == 200
 
-    # make sure date is not overridden
-    response = wrappers.Response("Hello World")
-    response.date = 1337
-    d = response.date
-    response.make_conditional(env)
-    assert response.date == d
 
-    # make sure content length is only set if missing
-    response = wrappers.Response("Hello World")
-    response.content_length = 999
-    response.make_conditional(env)
-    assert response.content_length == 999
+def test_apply_conditions_if_match_before_if_unmodified_since():
+    # If-Unmodified-Since is ignored if If-Match is present.
+    modified = datetime(2024, 1, 2, tzinfo=timezone.utc)
+    response = _response("abc", modified)
+    response.apply_conditions(
+        _request(
+            **{
+                "If-Match": '"abc"',
+                "If-Unmodified-Since": http_date(datetime(2024, 1, 1)),
+            }
+        )
+    )
+    assert response.status_code == 200
 
 
-def test_advertise_accept_ranges() -> None:
-    env = create_environ()
+@pytest.mark.parametrize("method", ["GET", "HEAD"])
+def test_apply_conditions_if_none_match_not_modified(method):
+    response = _response("abc")
+    response.apply_conditions(_request(method, **{"If-None-Match": '"abc"'}))
+    assert response.status_code == 304
+
+    # weak comparison is used
+    response = _response("abc")
+    response.apply_conditions(_request(method, **{"If-None-Match": 'W/"abc"'}))
+    assert response.status_code == 304
+
+    response = _response("abc")
+    response.apply_conditions(_request(method, **{"If-None-Match": '"xyz"'}))
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
+def test_apply_conditions_if_none_match_failed(method):
+    with pytest.raises(PreconditionFailed):
+        _response("abc").apply_conditions(
+            _request(method, **{"If-None-Match": '"abc"'})
+        )
+
+    response = _response("abc")
+    response.apply_conditions(_request(method, **{"If-None-Match": '"xyz"'}))
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize(
+    ("method", "exists", "status"),
+    [
+        ("GET", True, 304),
+        ("GET", False, 200),
+        ("POST", False, 200),
+        ("POST", True, 412),
+    ],
+)
+def test_apply_conditions_if_none_match_star(method, exists, status):
+    response = _response("abc")
+    request = _request(method, **{"If-None-Match": "*"})
+
+    if status == 412:
+        with pytest.raises(PreconditionFailed):
+            response.apply_conditions(request, exists=exists)
+    else:
+        response.apply_conditions(request, exists=exists)
+        assert response.status_code == status
+
+
+def test_apply_conditions_if_modified_since():
+    modified = datetime(2024, 1, 2, tzinfo=timezone.utc)
+
+    for method in "GET", "HEAD":
+        response = _response(last_modified=modified)
+        response.apply_conditions(
+            _request(method, **{"If-Modified-Since": http_date(modified)})
+        )
+        assert response.status_code == 304
+
+        response = _response(last_modified=modified)
+        response.apply_conditions(
+            _request(method, **{"If-Modified-Since": http_date(datetime(2024, 1, 1))})
+        )
+        assert response.status_code == 200
+
+    # not evaluated for other methods, and does not fail
+    response = _response(last_modified=modified)
+    response.apply_conditions(
+        _request("POST", **{"If-Modified-Since": http_date(modified)})
+    )
+    assert response.status_code == 200
+
+    # not evaluated without a modification time
+    response = _response()
+    response.apply_conditions(
+        _request(**{"If-Modified-Since": http_date(modified)})
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_none_match_before_if_modified_since():
+    # If-Modified-Since is ignored if If-None-Match is present.
+    modified = datetime(2024, 1, 2, tzinfo=timezone.utc)
+    response = _response("abc", modified)
+    response.apply_conditions(
+        _request(**{"If-None-Match": '"xyz"', "If-Modified-Since": http_date(modified)})
+    )
+    assert response.status_code == 200
+
+
+def test_apply_conditions_if_match_failed_before_if_none_match():
+    response = _response("abc")
+
+    with pytest.raises(PreconditionFailed):
+        response.apply_conditions(
+            _request(**{"If-Match": '"xyz"', "If-None-Match": '"abc"'})
+        )
+
+    assert response.status_code == 200
+
+
+def test_apply_conditions_no_headers():
+    response = _response("abc")
+    response.apply_conditions(_request())
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+
+
+def test_apply_range_accept_ranges():
     response = wrappers.Response()
-    response.make_conditional(env, accept_ranges=True)
+    response.apply_range(_request())
     assert response.status_code == 200
     assert response.headers["Accept-Ranges"] == "bytes"
     assert "Content-Range" not in response.headers
 
 
-def test_range_request_basic():
-    env = create_environ()
+def test_apply_range_basic():
     response = wrappers.Response("Hello World")
-    env["HTTP_RANGE"] = "bytes=0-4"
-    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    response.apply_range(_request(Range="bytes=0-4"))
     assert response.status_code == 206
     assert response.headers["Accept-Ranges"] == "bytes"
     assert response.headers["Content-Range"] == "bytes 0-4/11"
@@ -615,69 +755,225 @@ def test_range_request_basic():
     assert response.data == b"Hello"
 
 
-def test_range_request_out_of_bound():
-    env = create_environ()
+def test_apply_range_first_only():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_request(Range="bytes=0-1, 4-5"))
+    assert response.status_code == 206
+    assert response.headers["Content-Range"] == "bytes 0-1/11"
+    assert response.data == b"He"
+
+
+@pytest.mark.parametrize(
+    ("value", "content_range", "data"),
+    [
+        ("bytes=6-666", "bytes 6-10/11", b"World"),
+        ("bytes=-666", "bytes 0-10/11", b"Hello World"),
+        ("bytes=-5", "bytes 6-10/11", b"World"),
+        ("bytes=6-", "bytes 6-10/11", b"World"),
+    ],
+)
+def test_apply_range_clamped(value, content_range, data):
     response = wrappers.Response("Hello World")
-    env["HTTP_RANGE"] = "bytes=6-666"
-    response.make_conditional(env, accept_ranges=True, complete_length=11)
+    response.apply_range(_request(Range=value))
     assert response.status_code == 206
+    assert response.headers["Content-Range"] == content_range
+    assert response.data == data
+
+
+@pytest.mark.parametrize("value", ["bytes=11-", "bytes=20-30", "bytes=11-15"])
+def test_apply_range_unsatisfiable(value):
+    response = wrappers.Response("Hello World")
+
+    with pytest.raises(RequestedRangeNotSatisfiable) as exc_info:
+        response.apply_range(_request(Range=value))
+
+    assert exc_info.value.length == 11
+    assert response.status_code == 200
+
+
+@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "DELETE"])
+def test_apply_range_only_get(method):
+    response = wrappers.Response("Hello World")
+    response.apply_range(_request(method, Range="bytes=0-4"))
+    assert response.status_code == 200
     assert response.headers["Accept-Ranges"] == "bytes"
-    assert response.headers["Content-Range"] == "bytes 6-10/11"
-    assert response.headers["Content-Length"] == "5"
-    assert response.data == b"World"
+    assert response.data == b"Hello World"
 
 
-def test_range_request_with_file():
-    env = create_environ()
-    resources = os.path.join(os.path.dirname(__file__), "res")
-    fname = os.path.join(resources, "test.txt")
-    with open(fname, "rb") as f:
-        fcontent = f.read()
-    with open(fname, "rb") as f:
-        response = wrappers.Response(f)
-        env["HTTP_RANGE"] = "bytes=0-0"
-        response.make_conditional(
-            env, accept_ranges=True, complete_length=len(fcontent)
-        )
-        assert response.status_code == 206
-        assert response.headers["Accept-Ranges"] == "bytes"
-        assert response.headers["Content-Range"] == f"bytes 0-0/{len(fcontent)}"
-        assert response.headers["Content-Length"] == "1"
-        assert response.data == fcontent[:1]
+def test_apply_range_only_200():
+    response = wrappers.Response("Hello World", status=201)
+    response.apply_range(_request(Range="bytes=0-4"))
+    assert response.status_code == 201
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert "Content-Range" not in response.headers
 
 
-def test_range_request_with_complete_file():
-    env = create_environ()
+def test_apply_range_unknown_length():
+    response = wrappers.Response(["Hello World"])
+    assert response.content_length is None
+    response.apply_range(_request(Range="bytes=0-4"))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+
+
+def test_apply_range_zero_length():
+    response = wrappers.Response()
+    response.content_length = 0
+    response.apply_range(_request(Range="bytes=0-4"))
+    assert response.status_code == 200
+    assert "Content-Range" not in response.headers
+
+
+def test_apply_range_other_units():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_request(Range="items=0-4"))
+    assert response.status_code == 200
+    assert response.headers["Accept-Ranges"] == "bytes"
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_invalid_header_ignored():
+    response = wrappers.Response("Hello World")
+    response.apply_range(_request(Range="bytes=-"))
+    assert response.status_code == 200
+    assert response.data == b"Hello World"
+
+
+def test_apply_range_with_file():
     resources = os.path.join(os.path.dirname(__file__), "res")
     fname = os.path.join(resources, "test.txt")
+    fsize = os.path.getsize(fname)
+
     with open(fname, "rb") as f:
         fcontent = f.read()
+
     with open(fname, "rb") as f:
-        fsize = os.path.getsize(fname)
         response = wrappers.Response(f)
-        env["HTTP_RANGE"] = f"bytes=0-{fsize - 1}"
-        response.make_conditional(env, accept_ranges=True, complete_length=fsize)
+        response.content_length = fsize
+        response.apply_range(_request(Range=f"bytes=0-{fsize - 1}"))
         assert response.status_code == 206
-        assert response.headers["Accept-Ranges"] == "bytes"
         assert response.headers["Content-Range"] == f"bytes 0-{fsize - 1}/{fsize}"
         assert response.headers["Content-Length"] == str(fsize)
         assert response.data == fcontent
 
 
-@pytest.mark.parametrize("value", [None, 0])
-def test_range_request_without_complete_length(value):
-    env = create_environ(headers=
... (truncated; 5116 more characters; read the files)
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
