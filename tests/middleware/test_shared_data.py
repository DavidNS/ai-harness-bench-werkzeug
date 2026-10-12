import os
from contextlib import closing

import pytest

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


def _serve(app, path="/data.unknownext", **kwargs):
    app_iter, status, headers = run_wsgi_app(app, create_environ(path, **kwargs))

    with closing(app_iter):
        body = b"".join(app_iter)

    return status, headers, body


@pytest.fixture
def shared_dir(tmp_path):
    (tmp_path / "data.unknownext").write_bytes(b"0123456789")
    return str(tmp_path)


def test_conditional_no_default_cache_timeout(shared_dir):
    app = SharedDataMiddleware(None, {"/": shared_dir})
    status, headers, body = _serve(app)
    assert status == "200 OK"
    assert body == b"0123456789"
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["Cache-Control"] == "no-cache"
    assert "Expires" not in headers
    etag = headers["ETag"]
    assert "Last-Modified" in headers

    status, headers, body = _serve(app, headers={"If-None-Match": etag})
    assert status == "304 Not Modified"
    assert body == b""


def test_range_request(shared_dir):
    app = SharedDataMiddleware(None, {"/": shared_dir})
    status, headers, body = _serve(app, headers={"Range": "bytes=2-4"})
    assert status == "206 Partial Content"
    assert body == b"234"
    assert headers["Content-Range"] == "bytes 2-4/10"


def test_precondition_failed_and_unsatisfiable(shared_dir):
    app = SharedDataMiddleware(None, {"/": shared_dir})
    status, _, _ = _serve(app, headers={"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"
    status, _, _ = _serve(app, headers={"Range": "bytes=50-60"})
    assert status == "416 Requested Range Not Satisfiable"


def test_cache_timeout(shared_dir):
    app = SharedDataMiddleware(None, {"/": shared_dir}, cache_timeout=100)
    _, headers, _ = _serve(app)
    assert "max-age=100" in headers["Cache-Control"]
    assert "Expires" in headers


def test_cache_deprecated(shared_dir):
    with pytest.deprecated_call():
        app = SharedDataMiddleware(None, {"/": shared_dir}, cache=False)

    status, headers, body = _serve(app)
    assert status == "200 OK"
    assert body == b"0123456789"
    assert "ETag" not in headers


def test_fallback_mimetype_deprecated(shared_dir):
    with pytest.deprecated_call():
        app = SharedDataMiddleware(
            None, {"/": shared_dir}, fallback_mimetype="text/x-fallback"
        )

    status, headers, _ = _serve(app)
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/x-fallback; charset=utf-8"
