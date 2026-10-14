import os
from contextlib import closing

import pytest

from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import create_environ
from werkzeug.test import run_wsgi_app


def test_get_file_loader():
    app = SharedDataMiddleware(None, {})
    assert callable(app.get_file_loader("foo"))


res_dir = os.path.join(os.path.dirname(__file__), "..", "res")


def _run(app, path="/test.txt", **kwargs):
    app_iter, status, headers = run_wsgi_app(app, create_environ(path, **kwargs))

    with closing(app_iter):
        data = b"".join(app_iter)

    return status, dict(headers), data


def test_conditional_request():
    app = SharedDataMiddleware(None, {"/": res_dir})
    status, headers, data = _run(app)
    assert status == "200 OK"
    assert data.strip() == b"FOUND"
    assert "max-age" not in headers["Cache-Control"]
    assert "ETag" in headers
    assert "Last-Modified" in headers

    status, headers, data = _run(
        app, headers={"If-None-Match": headers["ETag"]}
    )
    assert status == "304 Not Modified"
    assert data == b""


def test_range_request():
    app = SharedDataMiddleware(None, {"/": res_dir})
    status, headers, data = _run(app, headers={"Range": "bytes=0-1"})
    assert status == "206 Partial Content"
    assert data == b"FO"
    assert headers["Content-Range"].startswith("bytes 0-1/")


def test_precondition_failed_and_range_not_satisfiable():
    app = SharedDataMiddleware(None, {"/": res_dir})
    status, _, _ = _run(app, headers={"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"
    status, _, _ = _run(app, headers={"Range": "bytes=1000-2000"})
    assert status == "416 Requested Range Not Satisfiable"


def test_cache_timeout():
    app = SharedDataMiddleware(None, {"/": res_dir}, cache_timeout=60)
    _, headers, _ = _run(app)
    assert "max-age=60" in headers["Cache-Control"]


def test_cache_deprecated():
    with pytest.deprecated_call():
        app = SharedDataMiddleware(None, {"/": res_dir}, cache=False)

    status, headers, data = _run(app, headers={"If-None-Match": '"x"'})
    assert status == "200 OK"
    assert headers["Cache-Control"] == "public"
    assert "ETag" not in headers
    assert data.strip() == b"FOUND"


def test_fallback_mimetype_deprecated():
    with pytest.deprecated_call():
        app = SharedDataMiddleware(
            None, {"/": res_dir}, fallback_mimetype="application/x-test"
        )

    assert app.fallback_mimetype == "application/x-test"
    app2 = SharedDataMiddleware(None, {"/": res_dir})
    assert app2.fallback_mimetype == "application/octet-stream"


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
