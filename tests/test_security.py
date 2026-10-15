import pytest
from tools.browser_tools import validate_public_http_url


def test_blocks_non_http_urls():
    with pytest.raises(ValueError):
        validate_public_http_url("file:///C:/Windows/win.ini")


def test_blocks_localhost_without_network_call():
    with pytest.raises(ValueError, match="Local and internal"):
        validate_public_http_url("http://localhost:8501")
