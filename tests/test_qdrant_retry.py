import httpx
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from backend.services.nutrition_service import _query_points_retrying


class _Client:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def query_points(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def test_dropped_connection_is_retried_once():
    c = _Client([ResponseHandlingException(httpx.RemoteProtocolError("Server disconnected"))])
    assert _query_points_retrying(c, collection_name="x") == "ok"
    assert c.calls == 2


def test_timeout_is_not_retried():
    c = _Client([ResponseHandlingException(httpx.ReadTimeout("slow"))])
    with pytest.raises(ResponseHandlingException):
        _query_points_retrying(c, collection_name="x")
    assert c.calls == 1


def test_second_drop_is_raised():
    drop = lambda: ResponseHandlingException(httpx.RemoteProtocolError("Server disconnected"))
    c = _Client([drop(), drop()])
    with pytest.raises(ResponseHandlingException):
        _query_points_retrying(c, collection_name="x")
    assert c.calls == 2
