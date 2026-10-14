import pytest

from scripts.check_version_absent import classify_manifest_response


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, "{}", "EXISTS"),
        (404, '{"errors":[{"code":"MANIFEST_UNKNOWN"}]}', "ABSENT"),
        (404, '{"errors":[{"code":"NAME_UNKNOWN"}]}', "ABSENT"),
        (401, "{}", "UNCERTAIN"),
        (403, "{}", "UNCERTAIN"),
        (500, "{}", "UNCERTAIN"),
        (404, "<html>Error</html>", "UNCERTAIN"),
        (404, '{"errors":[{"code":"DENIED"}]}', "UNCERTAIN"),
    ],
)
def test_classify_manifest_response(status, body, expected):
    assert classify_manifest_response(status, body) == expected
