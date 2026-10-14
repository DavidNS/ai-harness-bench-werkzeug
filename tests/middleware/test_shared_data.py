import os
from contextlib import closing

import pytest

from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import create_environ
from werkzeug.test import run_wsgi_app


def _serve(app, path="/test.txt", **headers):
    app_iter, status, response_headers = run_wsgi_app(
        app, create_environ(path, headers=headers)
    )

    with closing(app_iter) as app_iter:
        data = b"".join(app_iter)

    return status, response_headers, data


@pytest.fixture
def app():
    res = os.path.join(os.path.dirname(__file__), "..", "res")
    return SharedDataMiddleware(None, {"/": res})


def test_no_max_age_by_default(app):
    status, headers, data = _serve(app)
    assert status == "200 OK"
    headers = dict(headers)
    assert "max-age" not in headers["Cache-Control"]
    assert "no-cache" in headers["Cache-Control"]
    assert "ETag" in headers
    assert "Last-Modified" in headers
    assert data.strip() == b"FOUND"


def test_cache_timeout():
    res = os.path.join(os.path.dirname(__file__), "..", "res")
    app = SharedDataMiddleware(None, {"/": res}, cache_timeout=60)
    status, headers, data = _serve(app)
    assert "max-age=60" in dict(headers)["Cache-Control"]


def test_conditional(app):
    _, headers, _ = _serve(app)
    etag = dict(headers)["ETag"]
    status, headers, data = _serve(app, **{"If-None-Match": etag})
    assert status == "304 Not Modified"
    assert data == b""

    status, headers, data = _serve(app, **{"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"


def test_range(app):
    status, headers, data = _serve(app, Range="bytes=0-1")
    assert status == "206 Partial Content"
    assert dict(headers)["Content-Range"].startswith("bytes 0-1/")
    assert data == b"FO"


def test_range_not_satisfiable(app):
    status, headers, data = _serve(app, Range="bytes=1000-")
    assert status == "416 Requested Range Not Satisfiable"
    assert dict(headers)["Content-Range"].startswith("bytes */")


def test_fallback_mimetype_default(tmp_path):
    (tmp_path / "data.unknownext").write_bytes(b"x")
    app = SharedDataMiddleware(None, {"/": str(tmp_path)})
    status, headers, data = _serve(app, "/data.unknownext")
    assert dict(headers)["Content-Type"] == "application/octet-stream"


def test_deprecated_parameters(tmp_path):
    (tmp_path / "data.unknownext").write_bytes(b"x")

    with pytest.deprecated_call(match="'cache'"):
        SharedDataMiddleware(None, {}, cache=False)

    with pytest.deprecated_call(match="'fallback_mimetype'"):
        app = SharedDataMiddleware(
            None, {"/": str(tmp_path)}, fallback_mimetype="application/x-test"
        )

    status, headers, data = _serve(app, "/data.unknownext")
    assert dict(headers)["Content-Type"] == "application/x-test"


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
