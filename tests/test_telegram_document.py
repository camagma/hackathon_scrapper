"""Verify multipart CSV uploads and errors using fake HTTP responses."""

import codecs
from datetime import date
import json
from unittest.mock import Mock

import pytest
import requests

from devpost_reminder.export import CsvExport
from devpost_reminder.telegram import TelegramClient, TelegramCredentials, TelegramError


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = (body if isinstance(body, str) else json.dumps(body)).encode()
    result._content_consumed = True
    return result


@pytest.fixture
def upload(tmp_path):
    path = tmp_path / "hackathons.csv"
    path.write_text('id,title\n1,"Агенти, AI"\n', encoding="utf-8-sig")
    session = Mock()
    session.post.return_value = response({"ok": True, "result": {"message_id": 123}})
    client = TelegramClient(TelegramCredentials("fake-document-token", "12345"), session)
    return client, session, path


def test_csv_is_uploaded_as_multipart_with_caption_and_bom(upload):
    client, session, path = upload
    caption = CsvExport(path, (1,), date(2026, 11, 10)).caption
    seen = {}

    def accept(url, **kwargs):
        seen.update(kwargs)
        assert url.endswith("/sendDocument")
        assert kwargs["data"] == {"chat_id": "12345", "caption": caption}
        name, document, mime = kwargs["files"]["document"]
        assert name == "hackathons.csv" and mime == "text/csv"
        assert document.read() == path.read_bytes()
        document.seek(0)
        prepared = requests.Request("POST", url, data=kwargs["data"], files=kwargs["files"]).prepare()
        assert prepared.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'name="document"; filename="hackathons.csv"' in prepared.body
        assert path.read_bytes() in prepared.body
        assert path.read_bytes().startswith(codecs.BOM_UTF8)
        assert not document.closed
        assert "json" not in kwargs and "headers" not in kwargs
        assert kwargs["timeout"] == (10, 30)
        assert kwargs["allow_redirects"] is False
        return response({"ok": True, "result": {"message_id": 123}})

    session.post.side_effect = accept
    assert client.send_document(path, caption) is None
    assert seen["files"]["document"][1].closed
    assert "Hackathons in this file: 1" in caption
    assert "2026-11-10" in caption
    assert "Nearest submission deadline" in caption


@pytest.mark.parametrize("body,status", [
    ({"ok": False, "description": "private-content"}, 400),
    ({"ok": False, "error_code": 400}, 200),
    ({"ok": True, "result": {}}, 200), ("not-json", 502),
])
def test_rejection_closes_file_and_is_not_retried(upload, body, status):
    client, session, path = upload
    session.post.return_value = response(body, status)
    with pytest.raises(TelegramError) as error:
        client.send_document(path, "Summary")
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["files"]["document"][1].closed
    assert "private-content" not in str(error.value)


def test_timeout_does_not_leak_token_and_closes_file(upload):
    client, session, path = upload
    session.post.side_effect = requests.Timeout("URL contains fake-document-token")
    with pytest.raises(TelegramError) as error:
        client.send_document(path)
    assert "fake-document-token" not in str(error.value)
    assert session.post.call_args.kwargs["files"]["document"][1].closed
    session.post.assert_called_once()


def test_document_rate_limit_also_blocks_text_sends(upload):
    client, session, path = upload
    session.post.return_value = response({"ok": False, "parameters": {"retry_after": 30}}, 429)
    with pytest.raises(TelegramError) as error:
        client.send_document(path)
    assert error.value.retry_after == 30
    with pytest.raises(TelegramError, match="cooldown"):
        client.send_message("Reminder")
    assert session.post.call_count == 1


@pytest.mark.parametrize("caption", [None, "a" * 1025])
def test_invalid_caption_does_not_make_a_request(upload, caption):
    client, session, path = upload
    with pytest.raises(ValueError, match="caption"):
        client.send_document(path, caption)
    session.post.assert_not_called()


def test_empty_file_is_not_uploaded(upload):
    client, session, path = upload
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        client.send_document(path)
    session.post.assert_not_called()


def test_missing_file_is_not_a_success(upload):
    client, session, path = upload
    path.unlink()
    with pytest.raises(FileNotFoundError):
        client.send_document(path)
    session.post.assert_not_called()
