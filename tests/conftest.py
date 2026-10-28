"""Unit tests must never read or mutate the configured R2 bucket."""
import sys
import pytest


@pytest.fixture(autouse=True)
def disable_real_r2(monkeypatch):
    for name in ('backend.r2_client', 'r2_client'):
        module = sys.modules.get(name)
        if module is not None:
            monkeypatch.setattr(module, 'get_r2_client', lambda: None)
