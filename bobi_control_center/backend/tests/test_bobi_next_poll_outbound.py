from __future__ import annotations

import httpx
import pytest

from app.bobi_next.poll_interactions import PollInteractionStore
from app.bobi_next.poll_outbound import send_registered_poll
from app.bobi_next.waha_adapter import WahaTransport


class RecordingHttpClient:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.responses = list(responses or [])

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        data = self.responses.pop(0) if self.responses else {}
        request = httpx.Request(method, url)
        return httpx.Response(200, json=data, request=request)


@pytest.mark.asyncio
async def test_waha_send_poll_uses_documented_payload_and_returns_provider_id() -> None:
    client = RecordingHttpClient([{"id": "true_chat_PROVIDER_POLL"}])
    transport = WahaTransport(
        base_url="http://waha:3000",
        session="default",
        api_key="secret",
        client=client,
    )

    provider_id = await transport.send_poll(
        "1@c.us",
        "Proceed?",
        ("Yes", "No"),
        multiple_answers=False,
    )

    assert provider_id == "true_chat_PROVIDER_POLL"
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url.endswith("/api/sendPoll")
    assert kwargs["headers"]["X-Api-Key"] == "secret"
    assert kwargs["json"] == {
        "session": "default",
        "chatId": "1@c.us",
        "poll": {
            "name": "Proceed?",
            "options": ["Yes", "No"],
            "multipleAnswers": False,
        },
    }


@pytest.mark.asyncio
async def test_waha_send_poll_fails_closed_when_provider_returns_no_id() -> None:
    client = RecordingHttpClient([{}])
    transport = WahaTransport(
        base_url="http://waha:3000",
        session="default",
        client=client,
    )

    with pytest.raises(RuntimeError, match="waha_poll_message_id_missing"):
        await transport.send_poll("1@c.us", "Proceed?", ("Yes", "No"))


class FakePollTransport:
    def __init__(self, provider_id: str = "poll-provider-1") -> None:
        self.provider_id = provider_id
        self.calls: list[tuple[str, str, tuple[str, ...], bool]] = []

    async def send_poll(
        self,
        chat_id: str,
        question: str,
        options: tuple[str, ...] | list[str],
        *,
        multiple_answers: bool = False,
    ) -> str:
        normalized = tuple(options)
        self.calls.append((chat_id, question, normalized, multiple_answers))
        return self.provider_id


@pytest.mark.asyncio
async def test_send_registered_poll_persists_exact_provider_id_and_stable_keys(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    transport = FakePollTransport("provider-poll-abc")
    try:
        interaction = await send_registered_poll(
            transport,
            store,
            provider="waha-main",
            chat_id="1@c.us",
            user_key="u1",
            question="Choose a mode",
            option_keys={"Home": "mode_home", "Away": "mode_away"},
            context_key="presence-mode",
            now_ts=100,
        )

        assert interaction.poll_message_id == "provider-poll-abc"
        assert interaction.option_keys == {
            "Home": "mode_home",
            "Away": "mode_away",
        }
        assert interaction.context_key == "presence-mode"
        assert transport.calls == [
            (
                "1@c.us",
                "Choose a mode",
                ("Home", "Away"),
                False,
            )
        ]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_send_registered_poll_validates_before_network_send(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    transport = FakePollTransport()
    try:
        with pytest.raises(ValueError, match="poll_option_keys_not_unique"):
            await send_registered_poll(
                transport,
                store,
                provider="waha-main",
                chat_id="1@c.us",
                user_key="u1",
                question="Choose",
                option_keys={"A": "same", "B": "same"},
            )
        assert transport.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_send_registered_poll_does_not_register_without_provider_id(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    transport = FakePollTransport("")
    try:
        with pytest.raises(RuntimeError, match="poll_provider_message_id_missing"):
            await send_registered_poll(
                transport,
                store,
                provider="waha-main",
                chat_id="1@c.us",
                user_key="u1",
                question="Choose",
                option_keys={"A": "a"},
            )
        assert store.get("waha-main", "") is None
    finally:
        store.close()
