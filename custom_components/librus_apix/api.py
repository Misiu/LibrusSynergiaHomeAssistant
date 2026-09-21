"""API wrapper for Librus Synergia."""

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any, TypeVar

from homeassistant.util import dt as dt_util
from librus_apix.client import Client, new_client
from librus_apix.exceptions import (
    AuthorizationError,
    MaintananceError,
    ParseError,
    TokenError,
)

from .coordinator import _current_semester
from .plan_lekcji import DNI_TYGODNIA_PL, przetworz_plan

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class LibrusApiClient:
    """Class to interface with the Librus API."""

    def __init__(self, username: str, password: str) -> None:
        """Initialize the client."""
        self.username = username
        self.password = password
        self._client: Client | None = None
        self._token: Any = None
        self._auth_lock = asyncio.Lock()
        self.last_auth_error: Exception | None = None

    def _reset_auth(self) -> None:
        """Reset authentication state."""
        self._client = None
        self._token = None

    async def async_authenticate(self) -> bool:
        """Authenticate with Librus API."""
        async with self._auth_lock:
            try:
                loop = asyncio.get_running_loop()
                self._client = await loop.run_in_executor(None, new_client)
                self._token = await loop.run_in_executor(
                    None, self._client.get_token, self.username, self.password
                )
            except AuthorizationError as ex:
                self.last_auth_error = ex
                _LOGGER.warning("Librus authentication rejected: %s", ex)
                self._reset_auth()
                return False
            except MaintananceError as ex:
                self.last_auth_error = ex
                _LOGGER.warning("Librus is under maintenance: %s", ex)
                self._reset_auth()
                return False
            except Exception as ex:
                self.last_auth_error = ex
                _LOGGER.debug("Authentication failed: %s", ex, exc_info=True)
                self._reset_auth()
                return False

            self.last_auth_error = None
            return True

    async def _async_call(
        self,
        operation: str,
        func: Callable[..., T],
        *args: Any,
    ) -> T | None:
        """Run a blocking Librus call with one authentication retry."""
        for attempt in range(2):
            if (self._client is None or self._token is None) and not await self.async_authenticate():
                return None

            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, func, self._client, *args
                )
            except TokenError:
                _LOGGER.warning(
                    "Token expired fetching %s (attempt %d/2), re-authenticating",
                    operation,
                    attempt + 1,
                )
            except Exception as ex:
                _LOGGER.debug(
                    "Failed to get %s (attempt %d/2): %s",
                    operation,
                    attempt + 1,
                    ex,
                    exc_info=True,
                )

            self._reset_auth()

        return None

    async def async_get_grades(self) -> list[dict[str, Any]] | None:
        """Get grades from Librus."""
        from librus_apix.grades import get_grades

        result = await self._async_call("grades", get_grades, "all")
        if result is None:
            return None

        numeric_grades, _average_grades, descriptive_grades = result
        current_semester = _current_semester()
        grades: list[dict[str, Any]] = []

        for subject_grades in numeric_grades:
            for subject, subject_items in subject_grades.items():
                for grade in subject_items:
                    if grade.semester != current_semester:
                        continue
                    grades.append(
                        {
                            "subject": subject,
                            "grade": grade.grade,
                            "date": grade.date,
                            "category": grade.category,
                            "teacher": getattr(grade, "teacher", ""),
                            "semester": grade.semester,
                            "type": "numeric",
                        }
                    )

        for subject_grades in descriptive_grades:
            for subject, subject_items in subject_grades.items():
                for grade in subject_items:
                    if grade.semester != current_semester:
                        continue
                    grade_value = grade.grade.strip()
                    if not grade_value or not grade_value.replace("+", "").replace("-", "").isdigit():
                        continue
                    grades.append(
                        {
                            "subject": subject,
                            "grade": grade.grade,
                            "date": grade.date,
                            "category": (
                                getattr(grade, "desc", "").split("\n")[0]
                                if hasattr(grade, "desc")
                                else ""
                            ),
                            "teacher": getattr(grade, "teacher", ""),
                            "semester": grade.semester,
                            "type": "descriptive",
                        }
                    )

        return grades

    async def async_get_messages(
        self, count: int = 10
    ) -> list[dict[str, Any]] | None:
        """Get latest messages without opening message content."""
        from librus_apix.messages import get_received

        messages = await self._async_call("messages", get_received, 0)
        if messages is None:
            return None

        return [
            {
                "author": message.author,
                "title": message.title,
                "date": message.date,
                "href": message.href,
                "unread": message.unread,
                "has_attachment": message.has_attachment,
            }
            for message in messages[:count]
        ]

    async def async_get_homework(self) -> Any:
        """Get homework assignments for the next 30 days."""
        from librus_apix.homework import get_homework

        today = dt_util.now().date()
        return await self._async_call(
            "homework",
            get_homework,
            today.strftime("%Y-%m-%d"),
            (today + timedelta(days=30)).strftime("%Y-%m-%d"),
        )

    async def async_get_schedule(self) -> list[dict[str, Any]] | None:
        """Get schedule events from the current and next month."""
        from librus_apix.schedule import get_schedule

        today = dt_util.now().date()

        def _fetch(client: Client) -> list[dict[str, Any]]:
            events: list[dict[str, Any]] = []
            months = [
                (today.year, today.month),
                (
                    today.year + 1 if today.month == 12 else today.year,
                    1 if today.month == 12 else today.month + 1,
                ),
            ]
            for year, month in months:
                monthly = get_schedule(client, f"{month:02d}", str(year))
                for day_number, day_events in monthly.items():
                    event_date = date(year, month, int(day_number))
                    if event_date < today:
                        continue
                    for event in day_events:
                        events.append(
                            {
                                "data": event_date.strftime("%Y-%m-%d"),
                                "tydzien": DNI_TYGODNIA_PL.get(
                                    event_date.strftime("%A"),
                                    event_date.strftime("%A"),
                                ),
                                "tytul": event.title,
                                "przedmiot": event.subject,
                                "godzina": event.hour,
                                "numer_lekcji": event.number,
                                "szczegoly": event.data,
                                "href": event.href,
                            }
                        )
            return sorted(events, key=lambda event: event["data"])

        return await self._async_call("schedule", _fetch)

    async def async_get_timetable(self) -> list[dict[str, Any]] | None:
        """Get the current and next week lesson timetable."""
        from librus_apix.timetable import get_timetable

        today = dt_util.now().date()
        monday = today - timedelta(days=today.weekday())

        def _fetch(client: Client) -> list[dict[str, Any]]:
            weeks = []
            for offset in (0, 7):
                start = datetime.combine(
                    monday + timedelta(days=offset), datetime.min.time()
                )
                try:
                    weeks.append(get_timetable(client, start))
                except ParseError as ex:
                    _LOGGER.debug(
                        "No timetable for week starting %s: %s",
                        start.date(),
                        ex,
                    )
            return przetworz_plan(weeks)

        return await self._async_call("timetable", _fetch)

    async def async_get_student_information(self) -> Any:
        """Get student information from Librus."""
        from librus_apix.student_information import get_student_information

        return await self._async_call(
            "student information",
            get_student_information,
        )
