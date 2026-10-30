"""Concurrent byte rates, reuse and retry accounting without timing sleeps."""
from core.transfer_metrics import TransferMeter


def test_concurrent_files_have_independent_rates_and_aggregate_correctly():
    clock = [0.0]
    meter = TransferMeter(lambda: clock[0])
    for key in ('a', 'b'):
        meter.feed(dict(key=key, name=key, state='pending', done=0))
        meter.feed(dict(key=key, name=key, state='downloading', done=0))
    clock[0] = 1.0
    first = meter.feed(dict(key='a', name='a', state='downloading', done=1024))
    second = meter.feed(dict(key='b', name='b', state='downloading', done=2048))
    assert first['speed'] == 1024
    assert second['speed'] == 2048
    assert second['task_speed'] == 3072
    assert meter.feed(dict(key='a', name='a', state='verified', done=1024))['task_speed'] == 3072
    clock[0] = 4.0
    assert meter.feed(dict(key='c', name='c', state='cached', done=10000000))['task_speed'] == 0


def test_retry_reset_and_cached_bytes_do_not_inflate_network_speed():
    clock = [0.0]
    meter = TransferMeter(lambda: clock[0])
    meter.feed(dict(name='a', state='downloading', done=0))
    clock[0] = 1
    assert meter.feed(dict(name='a', state='downloading', done=4096))['speed'] == 4096
    assert meter.feed(dict(name='a', state='retrying', done=0))['speed'] == 0
    meter.feed(dict(name='a', state='downloading', done=0))
    clock[0] = 2
    assert meter.feed(dict(name='a', state='downloading', done=1024))['speed'] == 1024
    assert meter.feed(dict(name='a', state='cached', done=4096))['speed'] == 0


def test_partial_offset_and_fast_completion_are_accounted_as_network_bytes_only():
    clock = [0.0]
    meter = TransferMeter(lambda: clock[0])
    meter.feed(dict(name='small', state='downloading', done=1000000))
    clock[0] = .5
    completed = meter.feed(dict(name='small', state='verified', done=1001024))
    assert completed['task_speed'] == 2048
    assert completed['speed'] == 0
    cached = meter.feed(dict(name='cached', state='cached', done=10000000))
    assert cached['task_speed'] == 2048
