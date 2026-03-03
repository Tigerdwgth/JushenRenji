from src.distribution.bilibili import _extract_payload_dict


def test_extract_payload_dict_from_content_list():
    raw = {"content": [{"resource_id": "BV1abc"}], "isError": False}
    assert _extract_payload_dict(raw)["resource_id"] == "BV1abc"


def test_extract_payload_dict_falls_back_to_raw_dict():
    raw = {"resource_id": "BV2xyz"}
    assert _extract_payload_dict(raw)["resource_id"] == "BV2xyz"
