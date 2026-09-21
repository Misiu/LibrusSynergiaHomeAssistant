"""Tests for the Librus APIX config flow."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from librus_apix.exceptions import AuthorizationError, MaintananceError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.librus_apix.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable custom integrations."""
    return


@pytest.fixture
def librus_client() -> MagicMock:
    """Return a mocked external Librus API client."""
    client = MagicMock()
    client.get_token.return_value = object()
    return client


async def _run_user_flow(
    hass: HomeAssistant, client: MagicMock, password: str = "secret"
):
    data = {CONF_USERNAME: "123456", CONF_PASSWORD: password}
    with patch("librus_apix.client.new_client", return_value=client):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=data,
        )


async def test_user_flow_creates_entry(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Valid credentials create a config entry."""
    result = await _run_user_flow(hass, librus_client)

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Librus APIX (123456)"
    assert result["data"] == {
        CONF_USERNAME: "123456",
        CONF_PASSWORD: "secret",
    }


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Rejected credentials return invalid_auth."""
    librus_client.get_token.side_effect = AuthorizationError("bad credentials")

    result = await _run_user_flow(hass, librus_client, "bad")

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Librus maintenance is treated as a connectivity problem."""
    librus_client.get_token.side_effect = MaintananceError("maintenance")

    result = await _run_user_flow(hass, librus_client)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Unexpected errors are reported separately."""
    librus_client.get_token.side_effect = RuntimeError("boom")

    result = await _run_user_flow(hass, librus_client)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_blocks_duplicate_username(
    hass: HomeAssistant,
) -> None:
    """The same Librus account cannot be configured twice."""
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


async def test_reauth_success_updates_password(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Reauth keeps the username and updates the password."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)

    with patch("librus_apix.client.new_client", return_value=librus_client):
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


async def test_reauth_invalid_password_keeps_form(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Rejected replacement password does not overwrite stored credentials."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)
    librus_client.get_token.side_effect = AuthorizationError("bad credentials")

    with patch("librus_apix.client.new_client", return_value=librus_client):
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
    assert result["errors"] == {"base": "invalid_auth"}
    assert existing.data[CONF_PASSWORD] == "old-secret"



async def test_reconfigure_success_updates_password(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Reconfigure validates and updates the password."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)

    with patch("librus_apix.client.new_client", return_value=librus_client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": existing.entry_id,
            },
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert existing.data[CONF_USERNAME] == "123456"
    assert existing.data[CONF_PASSWORD] == "new-secret"


async def test_reconfigure_invalid_auth_can_recover(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Reconfigure remains open after invalid auth and can then recover."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)
    librus_client.get_token.side_effect = [
        AuthorizationError("bad credentials"),
        object(),
    ]

    with patch("librus_apix.client.new_client", return_value=librus_client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": existing.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "bad-secret"},
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "good-secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert existing.data[CONF_PASSWORD] == "good-secret"


async def test_reconfigure_cannot_connect(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Temporary Librus failure keeps the reconfigure form open."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)
    librus_client.get_token.side_effect = MaintananceError("maintenance")

    with patch("librus_apix.client.new_client", return_value=librus_client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": existing.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert existing.data[CONF_PASSWORD] == "old-secret"



async def test_user_flow_empty_token_is_invalid_auth(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """A falsy token is treated as rejected authentication."""
    librus_client.get_token.return_value = None

    result = await _run_user_flow(hass, librus_client)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_unknown_error_can_recover(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Reauth can recover after an unexpected validation error."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)
    librus_client.get_token.side_effect = [RuntimeError("boom"), object()]

    with patch("librus_apix.client.new_client", return_value=librus_client):
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
            {CONF_PASSWORD: "first-secret"},
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert existing.data[CONF_PASSWORD] == "new-secret"


async def test_reconfigure_unknown_error_can_recover(
    hass: HomeAssistant, librus_client: MagicMock
) -> None:
    """Reconfigure can recover after an unexpected validation error."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Librus APIX (123456)",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "old-secret"},
    )
    existing.add_to_hass(hass)
    librus_client.get_token.side_effect = [RuntimeError("boom"), object()]

    with patch("librus_apix.client.new_client", return_value=librus_client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": existing.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "first-secret"},
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert existing.data[CONF_PASSWORD] == "new-secret"
