"""Testy config flow Librus APIX."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.librus_apix.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def test_user_flow_tworzony_po_poprawnym_logowaniu(hass):
    """Poprawne dane tworza wpis config entry."""
    data = {CONF_USERNAME: "123456", CONF_PASSWORD: "secret"}

    with patch(
        "custom_components.librus_apix.config_flow.validate_input",
        AsyncMock(return_value={"title": "Librus APIX (123456)"}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=data,
        )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Librus APIX (123456)"
    assert result["data"] == data


async def test_user_flow_blad_logowania_pokazuje_cannot_connect(hass):
    """Nieudane logowanie wraca do formularza zamiast tworzyc wpis."""
    data = {CONF_USERNAME: "123456", CONF_PASSWORD: "bad"}

    with patch(
        "custom_components.librus_apix.config_flow.validate_input",
        AsyncMock(side_effect=ValueError("Cannot connect")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=data,
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_blokuje_drugi_wpis_dla_tego_samego_login(hass):
    """Jedno konto Librus nie powinno zostac dodane dwa razy."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "new-secret"},
    )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"



async def test_reauth_success_updates_password(hass):
    """Reauth zachowuje login i aktualizuje tylko haslo."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)

    with patch(
        "custom_components.librus_apix.config_flow.validate_input",
        AsyncMock(return_value={"title": "Librus APIX (123456)"}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": existing.entry_id,
            },
            data=dict(existing.data),
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert existing.data[CONF_USERNAME] == "123456"
    assert existing.data[CONF_PASSWORD] == "new-secret"


async def test_reauth_bad_password_keeps_form(hass):
    """Niepoprawne nowe haslo nie konczy reauth."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)

    with patch(
        "custom_components.librus_apix.config_flow.validate_input",
        AsyncMock(side_effect=ValueError("Cannot connect")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": existing.entry_id,
            },
            data=dict(existing.data),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "still-bad"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}
    assert existing.data[CONF_PASSWORD] == "old-secret"
