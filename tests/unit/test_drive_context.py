"""Drive interpolation: placeholders, escapes, and their interaction."""

import pytest

from darkroom.drive import Context, DriveError


class TestInterpolationEscapes:
    def test_double_braces_become_literals(self):
        ctx = Context()
        assert ctx.interpolate("curl -w %{{http_code}}") == "curl -w %{http_code}"

    def test_escapes_and_placeholders_coexist(self):
        ctx = Context({"base_url": "http://x"})
        assert (
            ctx.interpolate("{base_url}/a -w %{{http_code}}")
            == "http://x/a -w %{http_code}"
        )

    def test_escaped_placeholder_is_not_resolved(self):
        ctx = Context({"nonce": "secret"})
        assert ctx.interpolate("{{nonce}}") == "{nonce}"

    def test_unknown_placeholder_still_errors(self):
        with pytest.raises(DriveError, match="unknown placeholder"):
            Context().interpolate("{missing}")

    def test_json_values_interpolate_with_escapes(self):
        ctx = Context({"who": "mom"})
        assert ctx.interpolate_json({"a": "{who}", "b": "{{who}}"}) == {
            "a": "mom",
            "b": "{who}",
        }
