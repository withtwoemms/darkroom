"""Save/expect paths into a JSON body: dict keys, and array indexes since
drive-scripts 1.7 — a list endpoint's newest item is `$.items[0]`."""

import pytest

from darkroom.drive import DriveError, _dot_path

BODY = {
    "items": [
        {"id": "newest", "receipts": [{"who": "owner", "assurance": "presence"}]},
        {"id": "older", "receipts": []},
    ],
    "count": 2,
}


class TestDotPath:
    def test_dict_keys_walk_as_before(self):
        assert _dot_path(BODY, "$.count") == 2

    def test_index_into_an_array(self):
        assert _dot_path(BODY, "$.items[0].id") == "newest"
        assert _dot_path(BODY, "$.items[1].id") == "older"

    def test_nested_index(self):
        assert _dot_path(BODY, "$.items[0].receipts[0].who") == "owner"

    def test_negative_index_counts_from_the_end(self):
        assert _dot_path(BODY, "$.items[-1].id") == "older"

    def test_out_of_range_is_not_found(self):
        with pytest.raises(DriveError, match="not found"):
            _dot_path(BODY, "$.items[2].id")

    def test_index_on_a_non_array_is_not_found(self):
        with pytest.raises(DriveError, match="not found"):
            _dot_path(BODY, "$.count[0]")

    def test_missing_key_is_not_found(self):
        with pytest.raises(DriveError, match="not found"):
            _dot_path(BODY, "$.items[0].missing")

    def test_malformed_segment_is_refused(self):
        with pytest.raises(DriveError, match="malformed"):
            _dot_path(BODY, "$.items[zero].id")

    def test_requires_the_dollar_prefix(self):
        with pytest.raises(DriveError, match="form"):
            _dot_path(BODY, "items[0].id")
