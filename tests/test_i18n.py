import re
from unittest.mock import Mock

import pytest

from talos_panel.i18n import language_from_request, static_asset_url, translate


def test_polish_translation_and_english_fallback() -> None:
    assert translate("Servers", "pl") == "Serwery"
    assert translate("Servers", "en") == "Servers"
    assert translate("Unmapped value", "pl") == "Unmapped value"


def test_language_cookie_is_validated() -> None:
    request = Mock()
    request.cookies = {"talos_language": "pl"}
    assert language_from_request(request) == "pl"
    request.cookies = {"talos_language": "unsupported"}
    assert language_from_request(request) == "en"


def test_static_asset_url_contains_content_fingerprint() -> None:
    url = static_asset_url("async.css")

    assert re.fullmatch(r"/static/async\.css\?v=[0-9a-f]{12}", url)
    assert url == static_asset_url("async.css")


def test_static_asset_url_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid static asset path"):
        static_asset_url("../secret")
