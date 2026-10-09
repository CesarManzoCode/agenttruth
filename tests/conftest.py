"""Test configuration: offline tests cannot open sockets (contract §14 common rules, K1-C7).

Every test not marked ``live`` runs with socket connect/bind, ``socket.create_connection`` and
``socket.getaddrinfo`` replaced by a function that raises :class:`SocketBlockedError`. Tests marked
``live`` are deselected unless ``AT_LIVE=1``.
"""

from __future__ import annotations

import os
import socket
from typing import Any, NoReturn

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SocketBlockedError(RuntimeError):
    """Raised when an offline test tries to use the network."""


def _blocked(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise SocketBlockedError("offline tests must not use the network (mark live tests with @pytest.mark.live)")


def pytest_report_header(config: pytest.Config) -> str:
    return "agenttruth socket guard: enabled (offline tests cannot open sockets)"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("AT_LIVE") == "1":
        return
    live = [item for item in items if item.get_closest_marker("live")]
    if live:
        config.hook.pytest_deselected(items=live)
        items[:] = [item for item in items if not item.get_closest_marker("live")]


@pytest.fixture(autouse=True)
def _socket_guard(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
        monkeypatch.setattr(socket.socket, "bind", _blocked)
        monkeypatch.setattr(socket, "create_connection", _blocked)
        monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.fixture(autouse=True)
def _repo_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from the repository root (paths like ``datasets/ds0.spec.yaml`` resolve)."""
    monkeypatch.chdir(REPO)
