import datetime
import io
import pathlib

import pytest

from werkzeug.exceptions import NotFound
from werkzeug.exceptions import PreconditionFailed
from werkzeug.exceptions import RequestedRangeNotSatisfiable
from werkzeug.http import http_date
from werkzeug.test import create_environ
from werkzeug.utils import send_file
from werkzeug.utils import send_from_directory

res_path = pathlib.Path(__file__).parent / "res"
html_path = res_path / "index.html"
txt_path = res_path / "test.txt"
environ = create_environ()


@pytest.mark.parametrize("path", [html_path, str(html_path)])
def test_path(path):
    with send_file(path, environ) as rv:
        assert rv.mimetype == "text/html"
        assert rv.direct_passthrough
        rv.direct_passthrough = False
        assert rv.data == html_path.read_bytes()


def test_x_sendfile():
    with send_file(html_path, environ, use_x_sendfile=True) as rv:
        assert rv.headers["X-Sendfile"] == str(html_path)
        assert rv.data == b""


def test_last_modified():
    last_modified = datetime.datetime(1999, 1, 1, tzinfo=datetime.timezone.utc)

    with send_file(txt_path, environ, last_modified=last_modified) as rv:
        assert rv.last_modified == last_modified


@pytest.mark.parametrize(
    "file_factory", [lambda: txt_path.open("rb"), lambda: io.BytesIO(b"test")]
)
def test_object(file_factory):
    with send_file(
        file_factory(), environ, mimetype="text/plain", use_x_sendfile=True
    ) as rv:
        rv.direct_passthrough = False
        assert rv.data
        assert rv.mimetype == "text/plain"
        assert "X-Sendfile" not in rv.headers


def test_object_without_mimetype():
    with pytest.raises(TypeError, match="detect the MIME type"):
        send_file(io.BytesIO(b"test"), environ)


def test_object_mimetype_from_name():
    with send_file(io.BytesIO(b"test"), environ, download_name="test.txt") as rv:
        assert rv.mimetype == "text/plain"


@pytest.mark.parametrize(
    "file_factory", [lambda: txt_path.open(), lambda: io.StringIO("test")]
)
def test_text_mode_fails(file_factory):
    with file_factory() as f, pytest.raises(ValueError, match="binary mode"):
        send_file(f, environ, mimetype="text/plain")


@pytest.mark.parametrize(
    ("as_attachment", "value"), [(False, "inline"), (True, "attachment")]
)
def test_disposition_name(as_attachment, value):
    with send_file(txt_path, environ, as_attachment=as_attachment) as rv:
        assert rv.headers["Content-Disposition"] == f"{value}; filename=test.txt"


def test_object_attachment_requires_name():
    with pytest.raises(TypeError, match="attachment"):
        send_file(
            io.BytesIO(b"test"), environ, mimetype="text/plain", as_attachment=True
        )

    with send_file(
        io.BytesIO(b"test"), environ, as_attachment=True, download_name="test.txt"
    ) as rv:
        assert rv.headers["Content-Disposition"] == "attachment; filename=test.txt"


@pytest.mark.parametrize(
    ("name", "ascii", "utf8"),
    (
        ("index.html", "index.html", None),
        (
            "Ñandú／pingüino.txt",
            '"Nandu/pinguino.txt"',
            "%C3%91and%C3%BA%EF%BC%8Fping%C3%BCino.txt",
        ),
        # latin-1 isn't ascii, should be quoted
        ("Vögel.txt", "Vogel.txt", "V%C3%B6gel.txt"),
        # ":/" are not safe in filename* value
        ("те:/ст", '":/"', "%D1%82%D0%B5%3A%2F%D1%81%D1%82"),
        # general test of extended parameter (non-quoted)
        ("(тест.txt", '"(.txt"', "%28%D1%82%D0%B5%D1%81%D1%82.txt"),
        ("(test.txt", '"(test.txt"', None),
    ),
)
def test_non_ascii_name(name, ascii, utf8):
    with send_file(html_path, environ, as_attachment=True, download_name=name) as rv:
        content_disposition = rv.headers["Content-Disposition"]

    assert f"filename={ascii}" in content_disposition

    if utf8:
        assert f"filename*=UTF-8''{utf8}" in content_disposition
    else:
        assert "filename*=UTF-8''" not in content_disposition


def test_no_cache_conditional_default():
    with send_file(
        txt_path,
        create_environ(
            headers={"If-Modified-Since": http_date(datetime.datetime(2020, 7, 12))}
        ),
        last_modified=datetime.datetime(2020, 7, 11),
    ) as rv:
        assert "no-cache" in rv.headers["Cache-Control"]
        assert not rv.cache_control.public
        assert not rv.cache_control.max_age
        assert not rv.expires
        assert rv.status_code == 304


@pytest.mark.parametrize(("value", "public"), [(0, False), (60, True)])
def test_max_age(value, public):
    with send_file(txt_path, environ, max_age=value) as rv:
        assert ("no-cache" in rv.headers["Cache-Control"]) != public
        assert rv.cache_control.public == public
        assert rv.cache_control.max_age == value
        assert rv.expires
        assert rv.status_code == 200


def test_etag():
    with send_file(txt_path, environ) as rv:
        assert rv.headers["ETag"].count("-") == 2

    with send_file(txt_path, environ, etag=False) as rv:
        assert "ETag" not in rv.headers

    with send_file(txt_path, environ, etag="unique") as rv:
        assert rv.headers["ETag"] == '"unique"'


@pytest.mark.parametrize("as_attachment", (True, False))
def test_content_encoding(as_attachment):
    with send_file(
        txt_path, environ, download_name="logo.svgz", as_attachment=as_attachment
    ) as rv:
        assert rv.mimetype == "image/svg+xml"
        assert rv.content_encoding == ("gzip" if not as_attachment else None)


@pytest.mark.parametrize(
    ("directory", "path"),
    [(str(res_path), "test.txt"), (res_path, pathlib.Path("test.txt"))],
)
def test_from_directory(directory, path):
    with send_from_directory(directory, path, environ) as rv:
        rv.direct_passthrough = False
        assert rv.data.strip() == b"FOUND"


@pytest.mark.parametrize("path", ["../res/test.txt", "nothing.txt", "null\x00.txt"])
def test_from_directory_not_found(path):
    with pytest.raises(NotFound):
        send_from_directory(res_path, path, environ)


def test_root_path(tmp_path):
    # This is a private API, it should only be used by Flask.
    d = tmp_path / "d"
    d.mkdir()
    (d / "test.txt").write_bytes(b"test")

    with send_file("d/test.txt", environ, _root_path=tmp_path) as rv:
        rv.direct_passthrough = False
        assert rv.data == b"test"

    with send_from_directory("d", "test.txt", environ, _root_path=tmp_path) as rv:
        rv.direct_passthrough = False
        assert rv.data == b"test"


def test_max_age_callable():
    # This is a private API, it should only be used by Flask.
    with send_file(txt_path, environ, max_age=lambda p: 10) as rv:
        assert rv.cache_control.max_age == 10


def _env(method="GET", **headers):
    return create_environ(method=method, headers=headers)


def test_object_detects_name_size_mtime(tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"Hello World")

    with path.open("rb") as f:
        f.read()  # already read, will be seeked back

        with send_file(f, environ) as rv:
            assert rv.mimetype == "text/plain"
            assert rv.content_length == 11
            assert rv.last_modified is not None
            assert rv.headers["Content-Disposition"] == "inline; filename=data.txt"
            assert rv.etag is not None
            rv.direct_passthrough = False
            assert rv.data == b"Hello World"


def test_bytesio_seeked_to_start():
    f = io.BytesIO(b"Hello World")
    f.read()

    with send_file(f, environ, mimetype="text/plain") as rv:
        assert rv.content_length == 11
        assert rv.last_modified is None
        assert "ETag" not in rv.headers
        rv.direct_passthrough = False
        assert rv.data == b"Hello World"


def test_unseekable_object_no_size():
    class Unseekable(io.RawIOBase):
        def readable(self):
            return True

    with send_file(
        Unseekable(), _env(Range="bytes=0-1"), mimetype="text/plain"
    ) as rv:
        assert rv.content_length is None
        assert rv.status_code == 200


def test_range_bytesio():
    f = io.BytesIO(b"Hello World")
    f.read()

    with send_file(f, _env(Range="bytes=6-"), mimetype="text/plain") as rv:
        assert rv.status_code == 206
        assert rv.headers["Accept-Ranges"] == "bytes"
        assert rv.headers["Content-Range"] == "bytes 6-10/11"
        assert rv.content_length == 5
        assert b"".join(rv.response) == b"World"


def test_range_path():
    with send_file(txt_path, _env(Range="bytes=0-1")) as rv:
        assert rv.status_code == 206
        assert rv.content_length == 2
        assert b"".join(rv.response) == txt_path.read_bytes()[:2]


def test_if_range_etag_path():
    with send_file(txt_path, environ) as rv:
        etag = rv.headers["ETag"]

    with send_file(txt_path, _env(Range="bytes=0-1", **{"If-Range": etag})) as rv:
        assert rv.status_code == 206

    with send_file(txt_path, _env(Range="bytes=0-1", **{"If-Range": '"x"'})) as rv:
        assert rv.status_code == 200


def test_invalid_range_ignored():
    with send_file(txt_path, _env(Range="bytes=-")) as rv:
        assert rv.status_code == 200


def test_unsatisfiable_range_closes_file():
    f = io.BytesIO(b"Hello World")

    with pytest.raises(RequestedRangeNotSatisfiable):
        send_file(f, _env(Range="bytes=50-"), mimetype="text/plain")

    assert f.closed


def test_precondition_failed_closes_file():
    f = io.BytesIO(b"Hello World")

    with pytest.raises(PreconditionFailed):
        send_file(f, _env(**{"If-Match": '"x"'}), mimetype="text/plain", etag="a")

    assert f.closed


def test_if_none_match_304():
    with send_file(txt_path, environ) as rv:
        etag = rv.headers["ETag"]

    with send_file(txt_path, _env(**{"If-None-Match": etag})) as rv:
        assert rv.status_code == 304

    with send_file(
        txt_path, _env(**{"If-None-Match": etag}), use_x_sendfile=True
    ) as rv:
        assert rv.status_code == 304
        assert "X-Sendfile" not in rv.headers


def test_if_unmodified_since_412():
    last_modified = datetime.datetime(2020, 1, 2, tzinfo=datetime.timezone.utc)
    since = http_date(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))

    with pytest.raises(PreconditionFailed):
        send_file(
            txt_path,
            _env(**{"If-Unmodified-Since": since}),
            last_modified=last_modified,
        )


def test_not_conditional():
    with send_file(
        txt_path, _env(Range="bytes=0-1", **{"If-Match": '"x"'}), conditional=False
    ) as rv:
        assert rv.status_code == 200
