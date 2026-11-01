from datetime import UTC, datetime, timedelta

import pytest

from api.watch.frameworks import MetricSample
from api.watch.usage import UsageHistory
from api.watch.vllm import VLLM
from tests.watch_samples import METRICS_OLD, METRICS_V011

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)


def s(prompt: float, gen: float, ttft_sum: float, ttft_count: float) -> MetricSample:
    return MetricSample(2.0, 0.0, 0.5, prompt, gen, ttft_sum, ttft_count)


def test_reads_vllm_metrics() -> None:
    sample = VLLM().read_metrics(METRICS_V011)
    assert (sample.running, sample.waiting) == (12.0, 3.0)
    assert sample.kv_cache == pytest.approx(0.6)
    assert (sample.prompt_tokens, sample.generation_tokens, sample.ttft_sum, sample.ttft_count) == (
        5000.0, 1200.0, 8.0, 20.0)
    old = VLLM().read_metrics(METRICS_OLD)
    assert (old.kv_cache, old.ttft_count) == (0.25, None)


def test_usage_rates_and_ttft_window() -> None:
    history = UsageHistory(length=90)
    first = history.add(s(1000, 100, 1.0, 4), T0)
    assert (first.running, first.kv_cache_percent, first.tokens_out_per_s, first.ttft_seconds) == (2.0, 50.0, None, None)
    second = history.add(s(1500, 300, 3.0, 8), T0 + timedelta(seconds=10))
    assert (second.tokens_in_per_s, second.tokens_out_per_s, second.ttft_seconds) == (50.0, 20.0, 0.5)
    third = history.add(s(1500, 300, 4.0, 10), T0 + timedelta(seconds=70))  # the first reading left the window
    assert third.ttft_seconds == 0.5
    assert [p.at for p in history.points] == [T0, T0 + timedelta(seconds=10), T0 + timedelta(seconds=70)]


def test_counter_reset_skips_interval() -> None:  # Review Focus 4
    history = UsageHistory(length=3)
    history.add(s(5000, 900, 2.0, 10), T0)
    reset = history.add(s(40, 10, 0.1, 1), T0 + timedelta(seconds=10))
    assert (reset.tokens_in_per_s, reset.tokens_out_per_s, reset.ttft_seconds) == (None, None, None)
    after = history.add(s(140, 60, 0.4, 3), T0 + timedelta(seconds=20))
    assert (after.tokens_in_per_s, after.tokens_out_per_s) == (10.0, 5.0)
    assert after.ttft_seconds == pytest.approx(0.15)
    history.add(s(240, 110, 0.4, 3), T0 + timedelta(seconds=30))
    assert len(history.points) == 3
