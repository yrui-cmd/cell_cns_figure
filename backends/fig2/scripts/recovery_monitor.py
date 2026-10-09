"""Resident, windowless recovery supervisor for already registered orders."""
import os
from pathlib import Path
import threading
import time

import client


def monitor(registry=None, *, stop=None, interval=30):
    registry = Path(registry) if registry is not None else client.LOCAL
    stop = stop if stop is not None else threading.Event()
    try:
        lock = client.Lock(registry / 'recovery-monitor.lock')
        lock.__enter__()
    except client.ClientError:
        return 0  # One supervisor per branch, including repeated setup calls.
    try:
        while not stop.is_set():
            status = {'pid': os.getpid(), 'at': time.time(), 'mode': 'resident', 'error': None}
            try:
                status.update(client.recover(registry))
            except Exception as exc:
                # Keep monitoring after an unreadable registry or transient I/O error.
                status['error'] = type(exc).__name__
            try:
                client.write(registry / 'recovery-monitor.json', status)
            except OSError:
                pass
            stop.wait(interval)
        return 0
    finally:
        lock.__exit__(None, None, None)


if __name__ == '__main__':
    raise SystemExit(monitor())
