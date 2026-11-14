"""vLLM: how its containers look, where it listens, and what its endpoints say."""

import json
import shlex
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from api.watch.frameworks import Container, Get, InstanceInfo, InstanceSpec, MetricSample

DEFAULT_PORT = 8000


def _words(command: list[str]) -> list[str]:
    """The command as separate words, also when a shell runs it as one string (sh -c "vllm serve ...")."""
    words: list[str] = []
    for part in command:
        words.extend(shlex.split(part) if " " in part and "vllm" in part else [part])
    return words


def _flags(words: list[str]) -> dict[str, str]:
    """`--name value` and `--name=value` flags. The last one wins, as with argparse."""
    flags: dict[str, str] = {}
    for i, word in enumerate(words):
        if not word.startswith("--"):
            continue
        name, sep, value = word.partition("=")
        if not sep:
            following = words[i + 1] if i + 1 < len(words) else ""
            value = "" if following.startswith("-") else following
        flags[name] = value
    return flags


def _served_model(words: list[str]) -> str | None:
    """The model given as `vllm serve <model>`."""
    for i in range(1, len(words) - 1):
        if words[i] == "serve" and words[i - 1].rsplit("/", 1)[-1] == "vllm" and not words[i + 1].startswith("-"):
            return words[i + 1]
    return None


def _int(text: object) -> int | None:
    try:
        return int(text)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _from_json(body: str, pick: Callable[[Any], Any]) -> Any:
    try:
        return pick(json.loads(body))
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _metric_values(text: str) -> dict[str, list[float]]:
    """Every value of every metric in Prometheus text format, one per label set."""
    values: dict[str, list[float]] = defaultdict(list)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        brace, space = line.find("{"), line.find(" ")
        if brace != -1 and (space == -1 or brace < space):
            name, rest = line[:brace], line[line.rindex("}") + 1:].split()
        else:
            name, *rest = line.split()
        if rest:
            try:
                values[name].append(float(rest[0]))
            except ValueError:
                pass
    return values


class VLLM:
    name = "vllm"
    health_path = "/health"
    metrics_path = "/metrics"

    def recognises(self, image: str, command: str) -> bool:
        return "vllm" in image.lower() or "vllm serve" in command or "vllm.entrypoints" in command

    def describe(self, container: Container) -> InstanceSpec:
        words = _words(container.command)
        flags = _flags(words)
        return InstanceSpec(
            port=_int(flags.get("--port")) or DEFAULT_PORT,
            model=flags.get("--served-model-name") or flags.get("--model") or _served_model(words),
            max_model_len=_int(flags.get("--max-model-len")),
            api_key=flags.get("--api-key") or container.env.get("VLLM_API_KEY"),
            host=flags.get("--host") or None,
        )

    async def read_info(self, get: Get, spec: InstanceSpec) -> InstanceInfo:
        """The version and the served model. --api-key locks /v1/... but not /version."""
        version = model = max_model_len = None
        response = await get("/version", {})
        if response.status == 200:
            version = _from_json(response.body, lambda body: str(body["version"]))
        headers = {"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}
        response = await get("/v1/models", headers)
        if response.status == 200:
            model = _from_json(response.body, lambda body: str(body["data"][0]["id"]))
            max_model_len = _from_json(response.body, lambda body: _int(body["data"][0]["max_model_len"]))
        return InstanceInfo(version=version, model=model, max_model_len=max_model_len)

    def read_metrics(self, text: str) -> MetricSample:
        """Several engines (data parallel) export one series each: they're added up, except KV
        cache, which is their average. Names differ between versions, hence the fallbacks."""
        values = _metric_values(text)

        def total(*names: str) -> float | None:
            return next((sum(values[name]) for name in names if name in values), None)

        def mean(*names: str) -> float | None:
            return next((sum(values[name]) / len(values[name]) for name in names if name in values), None)

        return MetricSample(
            running=total("vllm:num_requests_running"),
            waiting=total("vllm:num_requests_waiting"),
            # vLLM from about v0.10 reports kv_cache_usage_perc, earlier versions gpu_cache_usage_perc.
            kv_cache=mean("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),
            prompt_tokens=total("vllm:prompt_tokens_total", "vllm:prompt_tokens"),
            generation_tokens=total("vllm:generation_tokens_total", "vllm:generation_tokens"),
            ttft_sum=total("vllm:time_to_first_token_seconds_sum"),
            ttft_count=total("vllm:time_to_first_token_seconds_count"),
        )
