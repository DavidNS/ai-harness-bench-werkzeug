import os
from contextlib import closing

import pytest

from werkzeug.datastructures import Headers
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import create_environ
from werkzeug.test import run_wsgi_app


RES = os.path.join(os.path.dirname(__file__), "..", "res")


def _app(**kwargs):
    def fallback(environ, start_response):
        start_response("404 NOT FOUND", [("Content-Type", "text/plain")])
        return [b"NOT FOUND"]

    return SharedDataMiddleware(fallback, {"/": RES}, **kwargs)


def _get(app, **kwargs):
    app_iter, status, headers = run_wsgi_app(app, create_environ("/test.txt", **kwargs))

    with closing(app_iter):
        data = b"".join(app_iter)

    return status, Headers(headers), data


def test_no_default_cache_timeout():
    status, headers, data = _get(_app())
    assert status == "200 OK"
    assert data.strip() == b"FOUND"
    assert "ETag" in headers
    assert "Last-Modified" in headers
    assert headers["Accept-Ranges"] == "bytes"
    assert "max-age" not in headers["Cache-Control"]
    assert "Expires" not in headers


def test_cache_timeout():
    _, headers, _ = _get(_app(cache_timeout=60))
    assert "max-age=60" in headers["Cache-Control"]


def test_conditional_304():
    app = _app()
    _, headers, _ = _get(app)
    status, _, data = _get(app, headers={"If-None-Match": headers["ETag"]})
    assert status == "304 Not Modified"
    assert data == b""
    status, _, _ = _get(
        app, headers={"If-Modified-Since": headers["Last-Modified"]}
    )
    assert status == "304 Not Modified"


def test_precondition_failed():
    status, _, _ = _get(_app(), headers={"If-Match": '"nope"'})
    assert status == "412 Precondition Failed"


def test_range():
    status, headers, data = _get(_app(), headers={"Range": "bytes=0-2"})
    assert status == "206 Partial Content"
    assert data == b"FOU"
    assert headers["Content-Range"].startswith("bytes 0-2/")


def test_range_not_satisfiable():
    status, _, _ = _get(_app(), headers={"Range": "bytes=1000-2000"})
    assert status == "416 Requested Range Not Satisfiable"


def test_cache_false_deprecated():
    with pytest.deprecated_call():
        app = _app(cache=False)

    status, headers, _ = _get(app, headers={"Range": "bytes=0-2"})
    assert status == "200 OK"
    assert "ETag" not in headers


def test_fallback_mimetype_deprecated_and_used(tmp_path):
    (tmp_path / "data.zzzqq").write_bytes(b"x")

    with pytest.deprecated_call():
        app = SharedDataMiddleware(None, {"/": str(tmp_path)}, fallback_mimetype="a/b")

    app_iter, status, headers = run_wsgi_app(app, create_environ("/data.zzzqq"))
    app_iter.close()
    assert status == "200 OK"
    assert Headers(headers)["Content-Type"] == "a/b"


def test_default_fallback_mimetype(tmp_path):
    (tmp_path / "data.zzzqq").write_bytes(b"x")
    app = SharedDataMiddleware(None, {"/": str(tmp_path)})
    app_iter, status, headers = run_wsgi_app(app, create_environ("/data.zzzqq"))
    app_iter.close()
    assert Headers(headers)["Content-Type"] == "application/octet-stream"


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
