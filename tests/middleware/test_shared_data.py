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


res_dir = os.path.join(os.path.dirname(__file__), "..", "res")


def _serve(app, path="/test.txt", **headers):
    app_iter, status, response_headers = run_wsgi_app(
        app, create_environ(path, headers=headers)
    )

    with closing(app_iter) as app_iter:
        data = b"".join(app_iter)

    return status, dict(response_headers), data


def test_conditional_and_range():
    app = SharedDataMiddleware(None, {"/": res_dir})
    status, headers, data = _serve(app)
    assert status == "200 OK"
    assert data.strip() == b"FOUND"
    assert headers["Accept-Ranges"] == "bytes"
    assert "max-age" not in headers["Cache-Control"]

    status, _, data = _serve(app, **{"If-None-Match": headers["ETag"]})
    assert status == "304 Not Modified"
    assert data == b""

    status, headers, data = _serve(app, Range="bytes=0-1")
    assert status == "206 Partial Content"
    assert data == b"FO"

    status, _, _ = _serve(app, Range="bytes=999-")
    assert status == "416 Requested Range Not Satisfiable"

    status, _, _ = _serve(app, **{"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"


def test_cache_timeout():
    app = SharedDataMiddleware(None, {"/": res_dir}, cache_timeout=60)
    _, headers, _ = _serve(app)
    assert "max-age=60" in headers["Cache-Control"]


def test_deprecated_params():
    with pytest.deprecated_call():
        app = SharedDataMiddleware(None, {"/": res_dir}, cache=False)

    status, headers, _ = _serve(app)
    assert status == "200 OK"
    assert "ETag" not in headers

    with pytest.deprecated_call():
        app = SharedDataMiddleware(
            None, {"/": res_dir}, fallback_mimetype="application/x-custom"
        )

    _, headers, _ = _serve(app, "/index.html")
    assert headers["Content-Type"] == "text/html; charset=utf-8"
