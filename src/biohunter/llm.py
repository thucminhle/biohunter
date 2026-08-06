from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests
import yaml


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str


class LLMBackend(Protocol):
    """Anything that can turn a list of chat messages into a response."""

    def chat(self, messages: list[dict], *, model: str, **kwargs) -> LLMResponse: ...


class AnthropicClient:
    """Wraps Anthropic's SDK behind the LLMBackend protocol."""

    def __init__(self) -> None:
        # Imported lazily so a machine without the anthropic package
        # installed can still use the Ollama/MLX backends fine.
        from anthropic import Anthropic

        self._client = Anthropic()  # reads ANTHROPIC_API_KEY from env

    def chat(self, messages: list[dict], *, model: str, **kwargs) -> LLMResponse:
        # Anthropic's API wants the system prompt separate from the
        # messages list, unlike the OpenAI-style shape everything else
        # in this project uses. Pull it out if the caller included one.
        system = None
        convo = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                convo.append(m)

        response = self._client.messages.create(
            model=model,
            max_tokens=kwargs.get("max_tokens", 2000),
            system=system,
            messages=convo,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(text=text, model=model, provider="anthropic")


class OllamaNativeClient:
    """Hits Ollama's NATIVE /api/chat endpoint -- not the OpenAI-compatible
    /v1/chat/completions route OpenAICompatibleClient below uses.

    Added after Step 1 parity debugging (see
    docs/handoffs/2026-08-05-n8n-python-parity-debugging.md): n8n's HTTP
    Request nodes all posted to .../api/chat directly, never to the
    compat shim. An isolated same-prompt timing test found the compat
    endpoint consistently slower than native at the same `think` setting
    (most dramatically at think=false: ~155s vs ~25s for the same real
    skills-selection prompt) -- real overhead in Ollama's OpenAI-
    compatibility layer, not a model-capability difference. Only Ollama
    gets this client; MLX servers (e.g. oMLX) have no native /api/chat
    equivalent and must stay on OpenAICompatibleClient.

    base_url should NOT include a /v1 suffix for this client -- that's
    the compat client's path prefix, not native's. See roles.yaml's
    comment on this for the migration note.
    """

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def chat(self, messages: list[dict], *, model: str, **kwargs) -> LLMResponse:
        # Same timeout-extraction reasoning as OpenAICompatibleClient below.
        timeout = kwargs.pop("timeout", 300)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        # `think` flows through here same as any other kwarg -- callers
        # pass it explicitly (see selection.py/writer.py), this class
        # doesn't need special-case handling for it, just like n8n's
        # HTTP Request node didn't need to -- it just JSON.stringify'd
        # whatever "think" value split-jobs handed it into the body.
        payload.update(kwargs)

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        resp = requests.post(
            f"{self._base_url}/api/chat", json=payload, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        # Native /api/chat's response shape: {"message": {"role":..., "content":...}, "done":..., ...}
        # -- no "choices" wrapper, unlike the OpenAI-compatible shape.
        text = data.get("message", {}).get("content", "")
        return LLMResponse(text=text, model=model, provider=self._base_url)


class OpenAICompatibleClient:
    """One backend for both Ollama and MLX — they expose the same
    /v1/chat/completions schema, just on different ports. Only
    base_url + model differ between the two, so no need for separate
    classes.

    api_key is optional because Ollama doesn't require one but MLX
    servers (e.g. oMLX) can — pass None for servers that don't need it,
    a Bearer token just won't be sent."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def chat(self, messages: list[dict], *, model: str, **kwargs) -> LLMResponse:
        # timeout is an HTTP client setting, not a model parameter — pop
        # it out before the payload.update() below, or it would get sent
        # to the server as a field in the JSON body instead of controlling
        # how long we wait for a response.
        #
        # Default raised from 120s -> 300s. Discovered during Step 1
        # verification (verify-writer against a real posting): when the
        # heading-selection branch falls back to the full catalog (see
        # select_headings()'s no-valid-selection fallback in selection.py),
        # the downstream bullet-selection prompt balloons to cover every
        # heading instead of the 2-3 a good selection would produce, and a
        # 12B local model can genuinely take longer than 120s to respond
        # to that much bigger prompt. This was a real timeout, not a hang
        # -- raising the ceiling is the correct fix, not a band-aid.
        timeout = kwargs.pop("timeout", 300)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        # Pass through anything else the caller supplied (e.g. the n8n
        # workflow's "think" flag) without this class needing to know
        # what it means. NOT YET VERIFIED against a real server that
        # "think" round-trips correctly on the OpenAI-compatible route —
        # test this explicitly during Step 0's verification call.
        payload.update(kwargs)

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        resp = requests.post(
            f"{self._base_url}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return LLMResponse(text=text, model=model, provider=self._base_url)


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: Any) -> Any:
    """roles.yaml uses ${VAR} for things like webhook URLs pulled from
    the environment. Resolve those; leave everything else untouched."""
    if isinstance(value, str):
        match = _ENV_VAR_PATTERN.fullmatch(value)
        if match:
            return os.environ.get(match.group(1), value)
    return value


class LLMClient:
    """Resolves a role name (e.g. "writer_selection") to the right
    backend + model per config/roles.yaml, with an optional per-run
    override merged on top. This is the only thing the rest of
    BioHunter should ever import from this module — Writer, Scorer,
    etc. call .complete(role, messages), never a backend directly.
    """

    def __init__(
        self,
        roles_path: str | Path = "config/roles.yaml",
        overrides: dict[str, str] | None = None,
    ) -> None:
        with open(roles_path) as f:
            self._roles: dict[str, dict] = yaml.safe_load(f)

        # Populated from --model role=provider/model or role=model
        # (wired in cli.py) and wins over whatever roles.yaml says for
        # that role, for this run only.
        self._overrides = overrides or {}

        # Backends are a little expensive to construct (Anthropic does
        # auth setup on init) and safe to share across every role that
        # points at the same provider + base_url, so cache instead of
        # building one per role.
        self._backend_cache: dict[tuple[str, str | None], LLMBackend] = {}

    @property
    def roles(self) -> dict[str, dict]:
        """Read-only view of the loaded roles.yaml, for callers (like the
        CLI's verify-llm command) that need to enumerate role names
        without reaching into a private attribute."""
        return self._roles

    def _get_backend(self, provider: str, base_url: str | None, api_key: str | None) -> LLMBackend:
        key = (provider, base_url, api_key)
        if key not in self._backend_cache:
            if provider == "anthropic":
                self._backend_cache[key] = AnthropicClient()
            elif provider == "ollama":
                if not base_url:
                    raise ValueError(f"provider '{provider}' requires a base_url in roles.yaml")
                # Native /api/chat, not the OpenAI-compat shim -- see
                # OllamaNativeClient's docstring for why this split exists.
                self._backend_cache[key] = OllamaNativeClient(base_url, api_key=api_key)
            elif provider in ("mlx", "openai"):
                if not base_url:
                    raise ValueError(f"provider '{provider}' requires a base_url in roles.yaml")
                self._backend_cache[key] = OpenAICompatibleClient(base_url, api_key=api_key)
            else:
                # Covers opencode / n8n_webhook / anything else listed as
                # an option in roles.yaml's header comment but not yet
                # implemented. Fails loudly and specifically rather than
                # silently doing nothing, only when a role actually tries
                # to use it.
                raise ValueError(
                    f"provider '{provider}' has no backend implementation yet"
                )
        return self._backend_cache[key]

    def complete(self, role: str, messages: list[dict], **kwargs) -> LLMResponse:
        if role not in self._roles:
            raise KeyError(f"no role '{role}' defined in roles.yaml")

        cfg = dict(self._roles[role])  # copy — never mutate the loaded config

        if role in self._overrides:
            override_value = self._overrides[role]
            if "/" in override_value:
                # e.g. "ollama/llama3.1:8b" — swap provider AND model
                provider, model = override_value.split("/", 1)
                cfg["provider"] = provider
                cfg["model"] = model
            else:
                # e.g. "llama3.1:8b" — keep the role's existing provider
                # and base_url, just swap the model name
                cfg["model"] = override_value

        provider = cfg["provider"]
        model = cfg["model"]
        base_url = _resolve_env(cfg.get("base_url"))
        api_key = _resolve_env(cfg.get("api_key"))

        backend = self._get_backend(provider, base_url, api_key)
        return backend.chat(messages, model=model, **kwargs)
