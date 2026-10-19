import os
from contextlib import closing

import pytest

from werkzeug.datastructures import Headers
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import create_environ
from werkzeug.test import run_wsgi_app


def test_get_file_loader():
    app = SharedDataMiddleware(None, {})
    assert callable(app.get_file_loader("foo"))


def test_shared_data_middleware(tmpdir):
    def null_application(environ, start_response):
        start_response("404 NOT FOUND", [("Content-Type", "text/plain")])
        yield b"NOT FOUND"

    test_dir = str(tmpdir)

    with open(os.path.join(test_dir, "äöü"), "w") as test_file:
        test_file.write("FOUND")

    for t in [list, dict]:
        app = SharedDataMiddleware(
            null_application,
            t(
                [
                    ("/", os.path.join(os.path.dirname(__file__), "..", "res")),
                    ("/sources", os.path.join(os.path.dirname(__file__), "..", "res")),
                    ("/pkg", ("werkzeug.debug", "shared")),
                    ("/foo", test_dir),
                ]
            ),
        )

        for p in "/test.txt", "/sources/test.txt", "/foo/äöü":
            app_iter, status, headers = run_wsgi_app(app, create_environ(p))
            assert status == "200 OK"

            if p.endswith(".txt"):
                content_type = next(v for k, v in headers if k == "Content-Type")
                assert content_type == "text/plain; charset=utf-8"

            with closing(app_iter) as app_iter:
                data = b"".join(app_iter).strip()

            assert data == b"FOUND"

        app_iter, status, headers = run_wsgi_app(
            app, create_environ("/pkg/debugger.js")
        )

        with closing(app_iter) as app_iter:
            contents = b"".join(app_iter)

        assert b"docReady(() =>" in contents

        for path in ("/missing", "/pkg", "/pkg/", "/pkg/missing.txt"):
            app_iter, status, headers = run_wsgi_app(app, create_environ(path))
            assert status == "404 NOT FOUND"
            assert b"".join(app_iter).strip() == b"NOT FOUND"


def _app(tmp_path, **kwargs):
    (tmp_path / "a.txt").write_bytes(b"Hello World")
    return SharedDataMiddleware(
        lambda e, s: s("404 NOT FOUND", []) or [b"NOT FOUND"],
        {"/s": str(tmp_path)},
        **kwargs,
    )


def _get(app, path="/s/a.txt", method="GET", **headers):
    environ = create_environ(path, method=method, headers=headers)
    app_iter, status, response_headers = run_wsgi_app(app, environ)

    with closing(app_iter):
        return status, Headers(response_headers), b"".join(app_iter)


def test_headers(tmp_path):
    status, headers, data = _get(_app(tmp_path))
    assert status == "200 OK"
    assert data == b"Hello World"
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    assert headers["Content-Length"] == "11"
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["ETag"].startswith('"wzsdm-')
    assert headers["Cache-Control"] == "public, max-age=43200"
    assert "Expires" in headers
    assert "Last-Modified" in headers


def test_unknown_type(tmp_path):
    (tmp_path / "a.unknownext").write_bytes(b"x")
    _, headers, _ = _get(_app(tmp_path), "/s/a.unknownext")
    assert headers["Content-Type"] == "application/octet-stream"


def test_not_modified(tmp_path):
    app = _app(tmp_path)
    _, headers, _ = _get(app)
    status, h, data = _get(app, **{"If-None-Match": headers["ETag"]})
    assert status == "304 Not Modified"
    assert data == b""

    status, _, _ = _get(
        app, **{"If-Modified-Since": headers["Last-Modified"]}
    )
    assert status == "304 Not Modified"


def test_precondition_failed(tmp_path):
    status, _, _ = _get(_app(tmp_path), **{"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"


def test_range(tmp_path):
    app = _app(tmp_path)
    status, headers, data = _get(app, Range="bytes=6-")
    assert status == "206 Partial Content"
    assert headers["Content-Range"] == "bytes 6-10/11"
    assert data == b"World"

    status, headers, _ = _get(app, Range="bytes=50-")
    assert status == "416 Requested Range Not Satisfiable"
    assert headers["Content-Range"] == "bytes */11"


def test_head(tmp_path):
    status, headers, data = _get(_app(tmp_path), method="HEAD")
    assert status == "200 OK"
    assert headers["Content-Length"] == "11"
    assert data == b""


def test_deprecated_cache(tmp_path):
    with pytest.deprecated_call():
        app = _app(tmp_path, cache=False)

    status, headers, data = _get(app)
    assert status == "200 OK"
    assert data == b"Hello World"
    assert "ETag" not in headers
    assert "Expires" not in headers
    assert headers["Cache-Control"] == "public"

    # not conditional
    status, _, _ = _get(app, **{"If-Modified-Since": headers["Last-Modified"]})
    assert status == "200 OK"

    status, headers, data = _get(app, Range="bytes=0-4")
    assert status == "206 Partial Content"
    assert data == b"Hello"


def test_deprecated_fallback_mimetype(tmp_path):
    (tmp_path / "a.unknownext").write_bytes(b"x")

    with pytest.deprecated_call():
        app = _app(tmp_path, fallback_mimetype="application/x-test")

    _, headers, _ = _get(app, "/s/a.unknownext")
    assert headers["Content-Type"] == "application/x-test"
