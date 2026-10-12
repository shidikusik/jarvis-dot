import base64
import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import wave

import pytest

from jarvis import cloud
from jarvis.cloud import GeminiCommandRecognizer, GeminiError, pcm_to_wav
from jarvis.commands import defaults, match_phrase


SYNTHETIC_KEY = "AIza" + "x" * 35
PCM = b"\0\0" * 16000


def response(transcript="Джарвис, который час?", addressed=True, command_ids=None, **fields):
    result = dict(transcript=transcript, addressed=addressed,
                  command_ids=["time"] if command_ids is None else command_ids)
    result.update(fields)
    return json.dumps({"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": json.dumps(result, ensure_ascii=False)}]}}]}).encode()


def client_with_response(payload):
    return GeminiCommandRecognizer(SYNTHETIC_KEY, transport=lambda request, timeout: payload)


def test_import_and_construction_do_not_use_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network before recognize")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert GeminiCommandRecognizer(SYNTHETIC_KEY)


def test_request_uses_fixed_header_auth_bounded_wav_and_no_actions():
    calls = []
    def transport(request, timeout):
        calls.append((request, timeout))
        return response()
    client = GeminiCommandRecognizer(SYNTHETIC_KEY, transport=transport)
    text = client.recognize(PCM, 16000, "джарвис который час", defaults())
    assert text == "джарвис который час"
    request, timeout = calls[0]
    assert request.method == "POST"
    assert request.full_url == cloud.ENDPOINT
    assert not urllib.parse.urlsplit(request.full_url).query
    assert request.get_header("X-goog-api-key") == SYNTHETIC_KEY
    assert timeout <= 30
    assert SYNTHETIC_KEY not in request.data.decode()
    payload = json.loads(request.data)
    assert "tools" not in payload and "toolConfig" not in payload
    context = json.loads(payload["contents"][0]["parts"][0]["text"])
    assert all(set(command) == {"id", "title", "phrases"} for command in context["enabled_commands"])
    assert "notepad.exe" not in request.data.decode()
    audio = payload["contents"][0]["parts"][1]["inlineData"]
    assert audio["mimeType"] == "audio/wav"
    with wave.open(io.BytesIO(base64.b64decode(audio["data"]))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(wav.getnframes()) == PCM


def test_chain_still_uses_existing_confirmation():
    client = client_with_response(response("Джарвис, скажи время и заблокируй компьютер", command_ids=["time", "lock"]))
    text = client.recognize(PCM, 16000, "", defaults())
    match = match_phrase(text, defaults())
    assert [c["id"] for c in match.commands] == ["time", "lock"]
    assert match.needs_confirmation


@pytest.mark.parametrize("payload", [
    response("Музыка играет на фоне", addressed=False, command_ids=[]),
    response("Который час?", addressed=True),
    response("Он сказал Джарвис который час", addressed=True),
    response("Джарвис не блокируй компьютер", command_ids=["lock"]),
    response("Джарвис отмена", command_ids=["lock"]),
    response(command_ids=["invented-shell"]),
    response(command_ids=["time"] * 6),
    response(addressed="true"),
    response(command_ids="time"),
    response(command_ids=[True]),
    response(extra_actions=["rm"]),
    response(transcript="Джарвис " + "x" * 1001),
], ids=["background", "no_wake", "incidental_wake", "negation", "cancel",
        "unknown_id", "too_many_ids", "bool_type", "list_type", "id_type",
        "extra_fields", "long_transcript"])
def test_background_negation_unknown_and_malformed_never_become_commands(payload):
    client = client_with_response(payload)
    try:
        recognized = client.recognize(PCM, 16000, "джарвис который час", defaults())
    except GeminiError as error:
        assert error.code == "response"
    else:
        assert recognized == ""


def test_disabled_command_cannot_be_selected():
    commands = defaults()
    commands[0]["enabled"] = False
    client = client_with_response(response())
    assert client.recognize(PCM, 16000, "", commands) == ""


def test_rejects_unsafe_catalog_before_network():
    commands = defaults()
    commands[0]["actions"] = [{"type": "shell", "value": "not allowed"}]
    def forbidden(*args):
        raise AssertionError("Invalid commands must not be sent")
    client = GeminiCommandRecognizer(SYNTHETIC_KEY, transport=forbidden)
    with pytest.raises(GeminiError) as raised:
        client.recognize(PCM, 16000, "", commands)
    assert raised.value.code == "invalid_catalog"


@pytest.mark.parametrize("pcm,rate", [(b"", 16000), (b"x", 16000), (PCM, 0),
                                      (PCM, True), (PCM, 192000),
                                      (b"\0\0" * (16000 * 12 + 1), 16000)],
                         ids=["empty", "odd_bytes", "zero_rate", "boolean_rate", "high_rate", "too_long"])
def test_audio_bounds(pcm, rate):
    with pytest.raises(GeminiError) as raised:
        pcm_to_wav(pcm, rate)
    assert raised.value.code == "invalid_audio"


def test_exact_twelve_second_audio_is_valid():
    assert pcm_to_wav(b"\0\0" * (16000 * 12), 16000).startswith(b"RIFF")


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "auth"), (429, "quota"), (500, "response")])
def test_provider_errors_are_sanitized_and_never_retried(status, code):
    calls = []
    def failing(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("https://example/?key=" + SYNTHETIC_KEY,
            status, "private provider text " + SYNTHETIC_KEY, {}, io.BytesIO(SYNTHETIC_KEY.encode()))
    client = GeminiCommandRecognizer(SYNTHETIC_KEY, transport=failing)
    with pytest.raises(GeminiError) as raised:
        client.recognize(PCM, 16000, "", defaults())
    assert raised.value.code == code
    assert SYNTHETIC_KEY not in str(raised.value)
    assert "private provider text" not in str(raised.value)
    assert raised.value.__suppress_context__
    assert len(calls) == 1


def test_network_exception_is_sanitized():
    def failing(request, timeout):
        raise OSError("secret " + SYNTHETIC_KEY)
    client = GeminiCommandRecognizer(SYNTHETIC_KEY, transport=failing)
    with pytest.raises(GeminiError) as raised:
        client.recognize(PCM, 16000, "", defaults())
    assert raised.value.code == "network"
    assert SYNTHETIC_KEY not in str(raised.value)
    assert raised.value.__suppress_context__


def test_local_rate_limit_counts_failures_and_hourly_window(monkeypatch):
    clock = [100.]
    calls = []
    monkeypatch.setattr(cloud.time, "monotonic", lambda: clock[0])
    def transport(request, timeout):
        calls.append(request)
        return response()
    client = GeminiCommandRecognizer(SYNTHETIC_KEY, hourly_limit=2, transport=transport)
    assert client.recognize(PCM, 16000, "", defaults())
    with pytest.raises(GeminiError, match="локальный лимит"):
        client.recognize(PCM, 16000, "", defaults())
    clock[0] += 3
    assert client.recognize(PCM, 16000, "", defaults())
    clock[0] += 3
    with pytest.raises(GeminiError, match="локальный лимит"):
        client.recognize(PCM, 16000, "", defaults())
    clock[0] += 3600
    assert client.recognize(PCM, 16000, "", defaults())
    assert len(calls) == 3


def test_non_stop_and_safety_block_responses_cannot_execute():
    for payload in [b'{"promptFeedback":{"blockReason":"SAFETY"}}',
                    b'{"candidates":[{"finishReason":"MAX_TOKENS"}]}']:
        assert client_with_response(payload).recognize(PCM, 16000, "", defaults()) == ""


def test_no_redirect_can_forward_key():
    request = urllib.request.Request(cloud.ENDPOINT, headers={"x-goog-api-key": SYNTHETIC_KEY})
    assert cloud._NoRedirects().redirect_request(request, None, 302, "Redirect", {}, "https://example.com/") is None


def test_oversized_response_is_sanitized():
    client = client_with_response(b"x" * (cloud.MAX_RESPONSE_BYTES + 1))
    with pytest.raises(GeminiError) as raised:
        client.recognize(PCM, 16000, "", defaults())
    assert raised.value.code == "response"
