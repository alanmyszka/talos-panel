from unittest.mock import Mock

from talos_panel.i18n import language_from_request, translate


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
