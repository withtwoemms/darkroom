"""Expectation witnesses (drive-scripts 1.4) and the raw http body."""

import pytest

from darkroom.drive import (
    DriveError,
    _evaluate_browser_expect,
    _evaluate_expect,
    _http_request_body,
)


class TestExpectWitness:
    def test_records_what_it_found(self):
        transcript = {"response": {"status": 201, "body": '{"id": 7}'}}
        detail, found = _evaluate_expect(
            {"status": 201, "body_contains": '"id"'}, transcript
        )
        assert detail is None
        assert found == {"status": 201, "body_contains": True}

    def test_failure_detail_and_found_agree(self):
        transcript = {"response": {"status": 404, "body": "nope"}}
        detail, found = _evaluate_expect({"status": 200}, transcript)
        assert detail == "expected status 200, got 404"
        assert found == {"status": 404}

    def test_command_exit_code_is_recorded(self):
        transcript = {"exit_code": 1, "stdout": "x"}
        detail, found = _evaluate_expect({"exit_code": 0}, transcript)
        assert detail is not None
        assert found == {"exit_code": 1}

    def test_body_miss_is_recorded_false(self):
        transcript = {"response": {"status": 200, "body": "hello"}}
        detail, found = _evaluate_expect({"body_contains": "bye"}, transcript)
        assert "does not contain" in detail
        assert found == {"body_contains": False}


class _Page:
    """The slice of a Playwright page the browser evaluator touches."""

    def __init__(self, title="t", url="http://x/a", content="<b>hi</b>", visible=True):
        self._title, self.url, self._content, self._visible = title, url, content, visible

    def title(self):
        return self._title

    def content(self):
        return self._content

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        page = self

        class _First:
            def wait_for(self, state, timeout):
                if not page._visible:
                    raise RuntimeError("not visible")

        class _Locator:
            first = _First()

        return _Locator()


class TestBrowserExpectWitness:
    def test_records_title_url_body_and_selector(self):
        page = _Page(title="zikora", url="http://x/me", content='<div data-member="mom">')
        detail, found = _evaluate_browser_expect(
            {
                "title_contains": "zik",
                "url_contains": "/me",
                "body_contains": 'data-member="mom"',
                "selector_visible": "#x",
            },
            page,
            200,
        )
        assert detail is None
        assert found == {
            "title": "zikora",
            "url": "http://x/me",
            "body_contains": True,
            "selector_visible": True,
        }

    def test_missing_selector_is_recorded_false(self):
        detail, found = _evaluate_browser_expect(
            {"selector_visible": "#gone"}, _Page(visible=False), None
        )
        assert "not visible" in detail
        assert found == {"selector_visible": False}

    def test_status_mismatch_stops_early(self):
        detail, found = _evaluate_browser_expect(
            {"status": 200, "title_contains": "x"}, _Page(), 500
        )
        assert detail == "expected status 200, got 500"
        assert found == {"status": 500}


class _Ctx:
    def interpolate(self, s):
        return s.replace("{n}", "42")

    def interpolate_json(self, v):
        return v


class TestHttpBody:
    def test_raw_body_is_verbatim_and_untyped(self):
        headers = {}
        assert _http_request_body({"body": "t={n}.raw"}, _Ctx(), headers) == "t=42.raw"
        assert "Content-Type" not in headers

    def test_json_body_is_serialized_and_typed(self):
        headers = {}
        assert _http_request_body({"json": {"a": 1}}, _Ctx(), headers) == '{"a": 1}'
        assert headers["Content-Type"] == "application/json"

    def test_no_body_when_neither_given(self):
        assert _http_request_body({"name": "s"}, _Ctx(), {}) is None

    def test_both_is_an_error(self):
        with pytest.raises(DriveError, match="json or body, not both"):
            _http_request_body({"name": "s", "json": {}, "body": "x"}, _Ctx(), {})
