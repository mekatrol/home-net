"""Socket and TLS transport layer for the MicroPython MQTT client."""

import usocket as socket


DEFAULT_SOCKET_TIMEOUT_SECONDS = 10


class MQTTTransport:
    """
    Thin transport abstraction used by `MQTTClient`.

    This class intentionally knows nothing about MQTT packet formats.
    Its job is to provide a stable API for socket lifecycle management,
    TLS wrapping, and raw byte-oriented I/O operations.
    """

    def __init__(
        self,
        server,
        port,
        use_ssl=False,
        ssl_params=None,
        socket_timeout=DEFAULT_SOCKET_TIMEOUT_SECONDS,
    ):
        if ssl_params is None:
            ssl_params = {}

        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.ssl_params = ssl_params
        self.socket_timeout = socket_timeout
        self.sock = None
        self._buffer = bytearray()
        self._read_transaction = None
        self.read_was_incomplete = False

    def connect(self):
        """
        Open a TCP socket to the configured broker and optionally wrap in TLS.

        Address resolution is performed at connect-time to avoid early failures
        during object construction and to match original runtime semantics.
        """
        self.close()
        self.sock = socket.socket()
        self.sock.settimeout(self.socket_timeout)

        try:
            print("MQTT resolving host:", self.server)
            addr = socket.getaddrinfo(self.server, self.port)[0][-1]
            print("MQTT TCP connecting")
            self.sock.connect(addr)
            print("MQTT TCP connected")

            if self.use_ssl:
                import ussl

                self.sock = ussl.wrap_socket(self.sock, **self.ssl_params)
                self.sock.settimeout(self.socket_timeout)
        except Exception:
            self.close()
            raise

    def write(self, data):
        """Write raw bytes to the broker socket."""
        self.sock.write(data)

    def read(self, n, blocking=True):
        """
        Read exactly `n` bytes from the broker socket.

        In non-blocking mode this returns `None` until the full byte count is
        available, while preserving any partial packet bytes in an internal
        buffer so subsequent polls can resume cleanly.
        """
        while len(self._buffer) < n:
            chunk = self.sock.read(n - len(self._buffer))

            if chunk is None:
                if not blocking:
                    self.read_was_incomplete = True
                    return None
                continue

            if chunk == b"":
                if not self._buffer:
                    return b""
                raise OSError(-1)

            self._buffer.extend(chunk)

            if not blocking and len(self._buffer) < n:
                self.read_was_incomplete = True
                return None

        data = bytes(self._buffer[:n])
        self._buffer = bytearray(self._buffer[n:])
        if self._read_transaction is not None:
            self._read_transaction += data
        return data

    def begin_read_transaction(self):
        """
        Start tracking consumed bytes so an incomplete non-blocking read can be
        retried without losing the beginning of an MQTT packet.
        """
        self._read_transaction = b""
        self.read_was_incomplete = False

    def commit_read_transaction(self):
        """Discard the bytes tracked for a completed packet read."""
        self._read_transaction = None
        self.read_was_incomplete = False

    def rollback_read_transaction(self):
        """Restore bytes consumed while attempting to read an incomplete packet."""
        if self._read_transaction:
            self._buffer = bytearray(self._read_transaction) + self._buffer
        self._read_transaction = None
        self.read_was_incomplete = False

    def setblocking(self, flag):
        """Enable or disable blocking mode on the underlying socket."""
        if flag:
            self.sock.settimeout(self.socket_timeout)
        else:
            self.sock.setblocking(False)

    def close(self):
        """Close the broker socket."""
        self._buffer = bytearray()
        self._read_transaction = None
        self.read_was_incomplete = False
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None
