import pytest

from app.services.storage import sanitize_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\line 1.L5X", "line_1.L5X"),
        ("   ", "upload"),
        (".hidden.xml", "hidden.xml"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected
