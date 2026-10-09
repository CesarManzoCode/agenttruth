"""The socket guard is active for offline tests (K1-C7 'no network used by offline tests')."""

import socket

import pytest
from conftest import SocketBlockedError


def test_offline_tests_cannot_open_sockets() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
    with pytest.raises(SocketBlockedError):
        socket.getaddrinfo("example.com", 443)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(SocketBlockedError):
            sock.connect(("192.0.2.1", 80))
        with pytest.raises(SocketBlockedError):
            sock.bind(("127.0.0.1", 0))
    finally:
        sock.close()
