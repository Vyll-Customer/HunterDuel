import socket
import time
import unittest

from network import NetworkPeer


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class NetworkTests(unittest.TestCase):
    def test_host_and_client_exchange_messages(self):
        port = free_port()
        host = NetworkPeer("host", port=port)
        client = NetworkPeer("client", "127.0.0.1", port)
        host.start()
        client.start()
        self.assertTrue(host.connected.wait(2))
        self.assertTrue(client.connected.wait(2))
        host.send({"type": "state", "frame": 7})
        client.send({"type": "intent", "light": True})
        deadline = time.time() + 2
        host_messages, client_messages = [], []
        while time.time() < deadline and (not host_messages or not client_messages):
            time.sleep(0.02)
            host_messages.extend(host.drain())
            client_messages.extend(client.drain())
        host.close()
        client.close()
        self.assertTrue(any(m.get("type") == "intent" for m in host_messages))
        self.assertTrue(any(m.get("type") == "state" for m in client_messages))


if __name__ == "__main__":
    unittest.main()

