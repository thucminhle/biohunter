"""
llm.py -- 2026-08-23 addition: token usage / generation-speed capture for
the token-usage mini-dashboard (see dashboard.py's module docstring,
2026-08-23 entry, which explicitly deferred this pending llm.py being
available to edit).

Nothing about the PUBLIC call shape changes: every existing caller
(selection.py's 6 call sites, critic.py's 1, scorer.py's 1) calls
llm.complete(role, messages, ...) exactly as before and only ever reads
response.text -- none of them need to change. Two additions only:

1. LLMResponse gains three new OPTIONAL fields (prompt_tokens,
   completion_tokens, elapsed_seconds), populated best-effort per
   backend from whatever that API actually returns. All three default
   to None -- a backend/server that doesn't report usage (some MLX
   servers, per OpenAICompatibleClient's existing "NOT YET VERIFIED"
   comment) degrades to None fields, not a crash or a fabricated 0.
2. LLMClient.__init__ takes an optional `usage_callback` -- if given,
   it's invoked as usage_callback(role, response) after every
   backend.chat() call, success or not attempted otherwise. This is the
   ONLY new integration point a caller needs: dashboard.py passes a
   closure that accumulates into a job dict via _set_job(), matching
   the same optional-callback pattern on_step already uses in
   writer.py/revision.py. None (the default) is a no-op for every
   existing caller -- CLI, tests, etc. -- zero behavior change.

Per-backend usage sourcing, each best-effort and independently:
- AnthropicClient: response.usage.input_tokens / .output_tokens (the
  Anthropic SDK always returns this on messages.create()). No
  elapsed_seconds from the SDK response itself; wall-clock timed around
  the call instead, same technique used for the other two backends.
- OllamaNativeClient: native /api/chat's response body carries
  prompt_eval_count / eval_count (token counts) and eval_duration (
  nanoseconds, generation time only -- excludes prompt-eval time,
  which is what a "tokens/sec generation speed" stat actually wants).
  All three are OPTIONAL per Ollama's own docs depending on server
  version/model -- .get() throughout, never indexed.
- OpenAICompatibleClient: OpenAI-compatible /v1/chat/completions
  SHOULD return a top-level "usage": {"prompt_tokens":..,
  "completion_tokens":..} block, but per this module's own prior
  comment this has never been verified against a real MLX/oMLX server
  -- .get()'d defensively, None fields if absent rather than assuming
  the shape.

elapsed_seconds is wall-clock timed around the HTTP call in every
backend (not trusted to any single API's self-reported duration field,
which not all three expose), so it's directly comparable across
backends for a "tokens/sec" computation regardless of provider.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import requests
import yaml


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    # New 2026-08-23, all optional -- see module docstring for per-backend
    # sourcing and why None (not 0) is the "unknown" value throughout.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_seconds: float | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    @property
    def tokens_per_second(self) -> float | None:
        """Completion-token generation speed -- the number most people
        mean by 'tokens/sec'. None if either completion_tokens or
        elapsed_seconds is unknown, or elapsed_seconds is ~0 (avoids a
        divide-by-zero on a suspiciously-instant response rather than
        reporting a meaningless huge number)."""
        if self.completion_tokens is None or not self.elapsed_seconds:
            return None
        if self.elapsed_seconds <= 0:
            return None
        return self.completion_tokens / self.elapsed_seconds


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

        start = time.monotonic()
        response = self._client.messages.create(
            model=model,
            max_tokens=kwargs.get("max_tokens", 2000),
            system=system,
            messages=convo,
        )
        elapsed = time.monotonic() - start

        text = "".join(block.text for block in response.content if block.type == "text")

        # response.usage is always present on a successful messages.create()
        # call per the Anthropic SDK's own contract, but .get()-style
        # defensive access costs nothing and matches this module's
        # treatment of the other two (less reliable) backends.
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None) if usage else None
        completion_tokens = getattr(usage, "output_tokens", None) if usage else None

        return LLMResponse(
            text=text, model=model, provider="anthropic",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            elapsed_seconds=elapsed,
        )


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

        # json_mode is a backend-agnostic flag (see LLMBackend callers in
        # selection.py) -- this class is the one that knows Ollama's native
        # /api/chat spells it "format": "json". Added 2026-08-06 after a
        # real-posting run showed writer_selection (gemma4:12b-mlx) silently
        # returning non-conforming JSON on the skills/summary/heading/bullet
        # branches (a whole catalog echoed back as one string, "None" where
        # a label was expected, etc.) with no error -- format:"json" makes
        # Ollama constrain generation to valid JSON instead of hoping the
        # model complies from instructions alone.
        json_mode = kwargs.pop("json_mode", False)

        # See LLMClient.complete()'s num_ctx comment. Ollama's native
        # /api/chat takes this nested under "options", not as a
        # top-level field -- easy to get wrong by just payload.update()-
        # ing it in with everything else, hence the explicit pop+nest.
        num_ctx = kwargs.pop("num_ctx", None)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        if num_ctx is not None:
            payload["options"] = {"num_ctx": num_ctx}
        # `think` flows through here same as any other kwarg -- callers
        # pass it explicitly (see selection.py/writer.py), this class
        # doesn't need special-case handling for it, just like n8n's
        # HTTP Request node didn't need to -- it just JSON.stringify'd
        # whatever "think" value split-jobs handed it into the body.
        payload.update(kwargs)

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        start = time.monotonic()
        resp = requests.post(
            f"{self._base_url}/api/chat", json=payload, headers=headers, timeout=timeout
        )
        wall_elapsed = time.monotonic() - start
        resp.raise_for_status()
        data = resp.json()
        # Native /api/chat's response shape: {"message": {"role":..., "content":...}, "done":..., ...}
        # -- no "choices" wrapper, unlike the OpenAI-compatible shape.
        text = data.get("message", {}).get("content", "")

        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        # eval_duration is nanoseconds and covers GENERATION only (excludes
        # prompt eval), which is exactly what a tokens/sec generation-speed
        # stat wants -- prefer it over wall_elapsed when present. Falls back
        # to wall-clock (includes prompt eval + network) if the server
        # didn't report it, so tokens_per_second still degrades gracefully
        # rather than going fully None.
        eval_duration_ns = data.get("eval_duration")
        elapsed = (eval_duration_ns / 1e9) if eval_duration_ns else wall_elapsed

        return LLMResponse(
            text=text, model=model, provider=self._base_url,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            elapsed_seconds=elapsed,
        )


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

        # See OllamaNativeClient.chat()'s json_mode comment -- same
        # backend-agnostic flag, this class's dialect for it is OpenAI's
        # response_format field rather than Ollama's format field.
        # NOT YET VERIFIED against a real MLX/oMLX server -- test this
        # explicitly if/when a role actually routes through this client.
        json_mode = kwargs.pop("json_mode", False)

        # num_ctx is Ollama-native-only (see OllamaNativeClient.chat()) --
        # pop and drop it here so a role accidentally routed through this
        # backend doesn't send a bogus top-level "num_ctx" field to an
        # OpenAI-compatible server, which has no per-request equivalent
        # (context length is server/model config, not a request field).
        kwargs.pop("num_ctx", None)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # Pass through anything else the caller supplied (e.g. the n8n
        # workflow's "think" flag) without this class needing to know
        # what it means. NOT YET VERIFIED against a real server that
        # "think" round-trips correctly on the OpenAI-compatible route —
        # test this explicitly during Step 0's verification call.
        payload.update(kwargs)

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        start = time.monotonic()
        resp = requests.post(
            f"{self._base_url}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
        elapsed = time.monotonic() - start
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        # Best-effort only -- see module docstring, this shape is not
        # confirmed against a real MLX/oMLX server yet. .get() throughout,
        # never indexed, so an absent/differently-shaped usage block
        # degrades to None fields rather than a KeyError.
        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        return LLMResponse(
            text=text, model=model, provider=self._base_url,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            elapsed_seconds=elapsed,
        )


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
        usage_callback: Callable[[str, LLMResponse], None] | None = None,
    ) -> None:
        with open(roles_path) as f:
            self._roles: dict[str, dict] = yaml.safe_load(f)

        # Populated from --model role=provider/model or role=model
        # (wired in cli.py) and wins over whatever roles.yaml says for
        # that role, for this run only.
        self._overrides = overrides or {}

        # New 2026-08-23: optional per-instance hook, called as
        # usage_callback(role, response) after every complete() call
        # that got a response back (i.e. not called if backend.chat()
        # itself raised -- a failed call has no usage to report).
        # dashboard.py's job runners pass a closure here that
        # accumulates into that job's dict via _set_job(); every other
        # existing caller (CLI, tests) passes nothing and gets the
        # exact same behavior as before this feature existed.
        self._usage_callback = usage_callback

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

        # num_ctx is role-level config (like base_url/api_key), not
        # something every selection.py call needs to remember to pass.
        # Added 2026-08-07: Ollama's own default context window per
        # request can be far smaller than a model's advertised max
        # (historically 2048-4096 tokens) unless explicitly set --
        # meaning a role could be pointed at a 256K-context model and
        # still silently truncate a long catalog+critique prompt if
        # nothing sets num_ctx. Only meaningful for the ollama provider
        # today (see OllamaNativeClient.chat()); other backends pop and
        # ignore it. kwargs wins if a caller already passed one.
        num_ctx = cfg.get("num_ctx")
        if num_ctx is not None:
            kwargs.setdefault("num_ctx", num_ctx)

        backend = self._get_backend(provider, base_url, api_key)
        response = backend.chat(messages, model=model, **kwargs)

        if self._usage_callback is not None:
            # Best-effort, same posture as _persist_job()'s try/except in
            # dashboard.py: a broken callback (e.g. a dashboard bug in the
            # accumulation closure) must never take down the actual LLM
            # call that already succeeded and whose text a caller is
            # about to use.
            try:
                self._usage_callback(role, response)
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "usage_callback raised for role '%s' -- ignoring, response is still returned", role
                )

        return response
