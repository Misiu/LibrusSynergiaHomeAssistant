"""Tests for the Librus API wrapper."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from librus_apix.exceptions import AuthorizationError, MaintananceError, ParseError, TokenError

from custom_components.librus_apix.api import LibrusApiClient


def _authenticated_client() -> LibrusApiClient:
    client = LibrusApiClient("user", "password")
    client._client = MagicMock()
    client._token = object()
    return client


async def test_authenticate_success() -> None:
    """Successful authentication stores the client and token."""
    api = LibrusApiClient("user", "password")
    client = MagicMock()
    token = object()
    client.get_token.return_value = token

    with patch("custom_components.librus_apix.api.new_client", return_value=client):
        assert await api.async_authenticate() is True

    assert api._client is client
    assert api._token is token
    assert api.last_auth_error is None


@pytest.mark.parametrize(
    "error",
    [
        AuthorizationError("bad credentials"),
        MaintananceError("maintenance"),
        RuntimeError("unexpected"),
    ],
)
async def test_authenticate_failures_reset_state(error: Exception) -> None:
    """Authentication failures are retained for setup error classification."""
    api = LibrusApiClient("user", "password")
    client = MagicMock()
    client.get_token.side_effect = error

    with patch("custom_components.librus_apix.api.new_client", return_value=client):
        assert await api.async_authenticate() is False

    assert api._client is None
    assert api._token is None
    assert api.last_auth_error is error


async def test_async_call_reauthenticates_after_token_error() -> None:
    """A token failure resets auth and retries once with a new session."""
    api = _authenticated_client()
    original_client = api._client
    replacement_client = MagicMock()
    replacement_client.get_token.return_value = object()
    call = MagicMock(side_effect=[TokenError("expired"), "ok"])

    with patch(
        "custom_components.librus_apix.api.new_client",
        return_value=replacement_client,
    ):
        result = await api._async_call("test", call)

    assert result == "ok"
    assert call.call_count == 2
    assert call.call_args_list[0].args[0] is original_client
    assert call.call_args_list[1].args[0] is replacement_client


async def test_async_call_returns_none_after_two_failures() -> None:
    """Repeated endpoint errors do not escape the wrapper."""
    api = _authenticated_client()
    replacement_client = MagicMock()
    replacement_client.get_token.return_value = object()
    call = MagicMock(side_effect=RuntimeError("offline"))

    with patch(
        "custom_components.librus_apix.api.new_client",
        return_value=replacement_client,
    ):
        assert await api._async_call("test", call) is None

    assert call.call_count == 2


async def test_async_call_stops_when_reauthentication_fails() -> None:
    """A failed authentication prevents the blocking endpoint call."""
    api = LibrusApiClient("user", "password")
    with patch.object(api, "async_authenticate", return_value=False):
        call = MagicMock()
        assert await api._async_call("test", call) is None
    call.assert_not_called()


async def test_get_grades_filters_semester_and_non_numeric_descriptions(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Grades expose only current-semester numeric values."""
    freezer.move_to("2026-09-21")
    api = _authenticated_client()
    numeric_current = SimpleNamespace(
        semester=1,
        grade="5",
        date="2026-09-20",
        category="Test",
        teacher="Teacher",
    )
    numeric_old = SimpleNamespace(
        semester=2,
        grade="4",
        date="2026-04-10",
        category="Test",
        teacher="Teacher",
    )
    descriptive_numeric = SimpleNamespace(
        semester=1,
        grade="4+",
        date="2026-09-19",
        desc="Kartkowka\nDetails",
        teacher="Teacher",
    )
    descriptive_text = SimpleNamespace(
        semester=1,
        grade="bz",
        date="2026-09-18",
        desc="Brak zadania",
        teacher="Teacher",
    )

    with patch(
        "librus_apix.grades.get_grades",
        return_value=(
            [{"Matematyka": [numeric_current, numeric_old]}],
            [],
            [{"Fizyka": [descriptive_numeric, descriptive_text]}],
        ),
    ):
        result = await api.async_get_grades()

    assert result == [
        {
            "subject": "Matematyka",
            "grade": "5",
            "date": "2026-09-20",
            "category": "Test",
            "teacher": "Teacher",
            "semester": 1,
            "type": "numeric",
        },
        {
            "subject": "Fizyka",
            "grade": "4+",
            "date": "2026-09-19",
            "category": "Kartkowka",
            "teacher": "Teacher",
            "semester": 1,
            "type": "descriptive",
        },
    ]


async def test_get_grades_returns_none_on_api_failure() -> None:
    """The grades wrapper propagates endpoint unavailability as None."""
    api = _authenticated_client()
    replacement_client = MagicMock()
    replacement_client.get_token.return_value = object()

    with (
        patch("librus_apix.grades.get_grades", side_effect=RuntimeError("offline")),
        patch("custom_components.librus_apix.api.new_client", return_value=replacement_client),
    ):
        assert await api.async_get_grades() is None


async def test_get_messages_limits_and_maps_results() -> None:
    """Messages are limited without fetching their body."""
    api = _authenticated_client()
    messages = [
        SimpleNamespace(
            author=f"Author {index}",
            title=f"Title {index}",
            date="2026-09-21",
            href=f"/{index}",
            unread=bool(index % 2),
            has_attachment=False,
        )
        for index in range(3)
    ]

    with patch("librus_apix.messages.get_received", return_value=messages):
        result = await api.async_get_messages(count=2)

    assert len(result) == 2
    assert result[0]["author"] == "Author 0"
    assert result[1]["href"] == "/1"


async def test_get_homework_uses_30_day_window(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Homework requests exactly the configured fixed date window."""
    freezer.move_to("2026-09-21")
    api = _authenticated_client()
    get_homework = MagicMock(return_value=["homework"])

    with patch("librus_apix.homework.get_homework", get_homework):
        result = await api.async_get_homework()

    assert result == ["homework"]
    assert get_homework.call_args.args[1:] == ("2026-09-21", "2026-10-21")


async def test_get_schedule_maps_future_events_and_rolls_year(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Schedule fetches current and next month and filters past days."""
    freezer.move_to("2026-12-15")
    api = _authenticated_client()
    future = SimpleNamespace(
        title="Sprawdzian",
        subject="Matematyka",
        hour="08:00",
        number=1,
        data={"Opis": "Algebra"},
        href="/event",
    )

    def get_schedule(_client, month: str, year: str):
        if (month, year) == ("12", "2026"):
            return {"14": [future], "20": [future]}
        assert (month, year) == ("01", "2027")
        return {"05": [future]}

    with patch("librus_apix.schedule.get_schedule", side_effect=get_schedule):
        result = await api.async_get_schedule()

    assert [event["data"] for event in result] == [
        "2026-12-20",
        "2027-01-05",
    ]
    assert result[0]["tytul"] == "Sprawdzian"


async def test_get_timetable_tolerates_empty_week(
    freezer: FrozenDateTimeFactory,
) -> None:
    """One ParseError does not discard the other timetable week."""
    freezer.move_to("2026-09-21")
    api = _authenticated_client()
    second_week = {"week": "second"}

    with (
        patch(
            "librus_apix.timetable.get_timetable",
            side_effect=[ParseError("empty"), second_week],
        ) as get_timetable,
        patch(
            "custom_components.librus_apix.api.przetworz_plan",
            return_value=[{"przedmiot": "Matematyka"}],
        ) as process,
    ):
        result = await api.async_get_timetable()

    assert result == [{"przedmiot": "Matematyka"}]
    assert get_timetable.call_count == 2
    process.assert_called_once_with([second_week])
    assert get_timetable.call_args_list[0].args[1] == datetime(2026, 9, 21)


async def test_get_student_information() -> None:
    """Student information uses the shared blocking-call wrapper."""
    api = _authenticated_client()
    student = SimpleNamespace(name="Jan Kowalski")

    with patch(
        "librus_apix.student_information.get_student_information",
        return_value=student,
    ):
        assert await api.async_get_student_information() is student
