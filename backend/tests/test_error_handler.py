import app_config
from api import app, internal_error
from unittest import mock


def test_internal_error_hides_exception_details_in_production():
    with app.app_context():
        with mock.patch.object(app_config, "is_production", return_value=True), mock.patch.object(
            app_config, "is_testing", return_value=False
        ):
            response, status = internal_error(ValueError("secret-db-info"))

    assert status == 500
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["message"] == "Internal Server Error"
    assert payload["details"] == "Internal Server Error"


def test_internal_error_shows_details_in_testing():
    with app.app_context():
        with mock.patch.object(app_config, "is_production", return_value=False):
            response, status = internal_error(ValueError("visible-in-test"))

    assert status == 500
    payload = response.get_json()
    assert payload["details"] == "visible-in-test"
