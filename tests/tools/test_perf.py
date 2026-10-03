"""Agregação e parsers do script de desempenho (tools/perf.py, tarefa 1.18)."""

from __future__ import annotations

import pytest

from tools.perf import (
    cpu_percent,
    parse_docker_stats,
    parse_memory_stat,
    parse_size_mb,
    parse_smaps_rollup,
    percentile,
    summarize,
)


def test_percentile_interpolates_like_numpy() -> None:
    xs = list(range(1, 11))  # 1..10
    assert percentile(xs, 90) == pytest.approx(9.1)
    assert percentile(xs, 50) == pytest.approx(5.5)
    assert percentile(xs, 0) == 1
    assert percentile(xs, 100) == 10
    assert percentile([7.0], 90) == 7.0
    assert percentile([3, 1, 2], 50) == 2  # ordena antes


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 90)
    with pytest.raises(ValueError):
        percentile([1], 101)


def test_summarize() -> None:
    s = summarize([1.0, 2.0, 3.0, 4.0])
    assert (s.n, s.mean, s.max) == (4, 2.5, 4.0)
    assert s.p90 == pytest.approx(3.7)
    assert "p90 3.70" in s.fmt()


def test_cpu_percent() -> None:
    assert cpu_percent(1_000_000, 1_100_000, 5.0) == pytest.approx(2.0)  # 0,1 s em 5 s
    assert cpu_percent(10, 5, 1.0) == 0  # contador reiniciado não dá negativo
    with pytest.raises(ValueError):
        cpu_percent(0, 1, 0)


def test_parse_sizes_and_docker_stats() -> None:
    assert parse_size_mb("166.8MiB") == pytest.approx(174.9, abs=0.1)
    assert parse_size_mb("1GB") == 1000
    assert parse_size_mb("512kB") == pytest.approx(0.512)
    with pytest.raises(ValueError):
        parse_size_mb("muito")
    line = '{"CPUPerc":"3.61%","MemUsage":"100MiB / 256MiB","Name":"magi-pg"}'
    cpu, mem = parse_docker_stats(line)
    assert cpu == pytest.approx(3.61)
    assert mem == pytest.approx(104.86, abs=0.01)


def test_parse_smaps_rollup() -> None:
    text = "55e0-7ff [rollup]\nRss:              102400 kB\nPss:               51200 kB\nShared_Clean: 1 kB\n"
    rss, pss = parse_smaps_rollup(text)
    assert rss == pytest.approx(104.8576)
    assert pss == pytest.approx(52.4288)
    assert parse_smaps_rollup("") == (0.0, 0.0)


def test_parse_memory_stat() -> None:
    st = parse_memory_stat("anon 16224256\nfile 133906432\nshmem 37662720\n\n")
    assert st == {"anon": 16224256, "file": 133906432, "shmem": 37662720}
