"""High-level MQTT 3.1.1 client for MicroPython."""

import ustruct as struct

try:
    # Package-style imports (preferred when `libs/mqtt` is a package).
    from .mqtt_exception import MQTTException
    from .mqtt_packet_builder import MQTTPacketBuilder
    from .mqtt_transport import MQTTTransport
except ImportError:
    # Fallback for environments that place modules flat on sys.path.
    from mqtt_exception import MQTTException
    from mqtt_packet_builder import MQTTPacketBuilder
    from mqtt_transport import MQTTTransport


class MQTTClient:
    """
    MQTT client implementation focused on constrained MicroPython targets.

    Design goals:
    - Keep packet-level logic explicit and easy to audit.
    - Keep memory usage small by streaming reads/writes directly to socket.
    - Support core workflows (connect, publish, subscribe, keepalive ping).
    """

    def __init__(
        self,
        client_id,
        server,
        port=0,
        user=None,
        password=None,
        keepalive=0,
        ssl=False,
        ssl_params=None,
    ):
        if port == 0:
            port = 8883 if ssl else 1883

        self.transport = MQTTTransport(server, port, ssl, ssl_params)

        self.client_id = client_id
        self.user = user
        self.pswd = password
        self.keepalive = keepalive

        self.cb = None
        self.pid = 0

        # Last Will and Testament state (optional).
        self.lw_topic = None
        self.lw_msg = None
        self.lw_qos = 0
        self.lw_retain = False

    def _next_pid(self):
        """
        Return next non-zero packet identifier (MQTT PID range 1..65535).
        """
        self.pid = (self.pid + 1) & 0xFFFF
        if self.pid == 0:
            self.pid = 1
        return self.pid

    def set_callback(self, f):
        """
        Register callback called as `callback(topic, msg)` on incoming publish.
        """
        self.cb = f

    def set_last_will(self, topic, msg, retain=False, qos=0):
        """
        Configure Last Will payload included in subsequent CONNECT packet.
        """
        assert 0 <= qos <= 2
        assert topic

        self.lw_topic = topic
        self.lw_msg = msg
        self.lw_qos = qos
        self.lw_retain = retain

    def connect(self, clean_session=True):
        """
        Establish connection and send MQTT CONNECT.

        Returns broker's `session present` bit from CONNACK flags.
        """
        self.transport.connect()

        # Variable header: protocol name/version, flags, keepalive.
        variable = bytearray(b"\x00\x04MQTT\x04")
        flags = 0

        if clean_session:
            flags |= 0x02

        if self.user is not None:
            # Preserve original behavior: if user is set, username+password
            # flags are both enabled and password is always serialized.
            flags |= 0x80 | 0x40

        if self.lw_topic:
            flags |= 0x04
            flags |= (self.lw_qos & 0x03) << 3
            if self.lw_retain:
                flags |= 0x20

        variable.append(flags)
        variable.extend(struct.pack("!H", self.keepalive))

        # Compute payload size before writing fixed header.
        payload_size = 2 + len(self.client_id)

        if self.lw_topic:
            payload_size += 2 + len(self.lw_topic)
            payload_size += 2 + len(self.lw_msg)

        if self.user is not None:
            payload_size += 2 + len(self.user)
            payload_size += 2 + len(self.pswd)

        remaining = len(variable) + payload_size

        fixed = bytearray([MQTTPacketBuilder.CONNECT])
        fixed.extend(MQTTPacketBuilder.encode_varlen(remaining))

        self.transport.write(fixed)
        self.transport.write(variable)

        # Payload fields are serialized in MQTT-defined order.
        self.transport.write(MQTTPacketBuilder.encode_string(self.client_id))

        if self.lw_topic:
            self.transport.write(MQTTPacketBuilder.encode_string(self.lw_topic))
            self.transport.write(MQTTPacketBuilder.encode_string(self.lw_msg))

        if self.user is not None:
            self.transport.write(MQTTPacketBuilder.encode_string(self.user))
            self.transport.write(MQTTPacketBuilder.encode_string(self.pswd))

        # CONNACK is 4 bytes for MQTT 3.1.1: type, rem_len, flags, rc.
        resp = self.transport.read(4)

        if resp[0] != MQTTPacketBuilder.CONNACK or resp[1] != 0x02:
            raise MQTTException("Invalid CONNACK")

        if resp[3] != 0:
            raise MQTTException(resp[3])

        return resp[2] & 1

    def disconnect(self):
        """Send DISCONNECT and close transport."""
        try:
            self.transport.write(b"\xE0\x00")
        finally:
            self.transport.close()

    def ping(self):
        """Send PINGREQ keepalive packet."""
        self.transport.write(b"\xC0\x00")

    def publish(self, topic, msg, retain=False, qos=0):
        """
        Publish message on `topic`.

        QoS 0: fire-and-forget.
        QoS 1: block until matching PUBACK arrives.
        QoS 2: intentionally not implemented.
        """
        header = 0x30 | (qos << 1) | retain

        remaining = 2 + len(topic) + len(msg)
        pid = None

        if qos > 0:
            remaining += 2
            pid = self._next_pid()

        fixed = bytearray([header])
        fixed.extend(MQTTPacketBuilder.encode_varlen(remaining))

        self.transport.write(fixed)
        self.transport.write(MQTTPacketBuilder.encode_string(topic))

        if qos > 0:
            self.transport.write(struct.pack("!H", pid))

        self.transport.write(msg)

        if qos == 1:
            while True:
                op = self.wait_msg()
                if op == MQTTPacketBuilder.PUBACK:
                    self.transport.read(1)  # Remaining length byte.
                    rcv_pid = struct.unpack("!H", self.transport.read(2))[0]
                    if rcv_pid == pid:
                        return

        elif qos == 2:
            raise NotImplementedError("QoS 2 not supported")

    def subscribe(self, topic, qos=0):
        """
        Subscribe to a topic filter and wait for corresponding SUBACK.
        """
        assert self.cb is not None, "Callback required"

        pid = self._next_pid()
        remaining = 2 + 2 + len(topic) + 1

        packet = bytearray([MQTTPacketBuilder.SUBSCRIBE])
        packet.extend(MQTTPacketBuilder.encode_varlen(remaining))
        packet.extend(struct.pack("!H", pid))

        self.transport.write(packet)
        self.transport.write(MQTTPacketBuilder.encode_string(topic))
        self.transport.write(bytes([qos]))

        while True:
            op = self.wait_msg()
            if op == MQTTPacketBuilder.SUBACK:
                resp = self.transport.read(4)
                rcv_pid = struct.unpack("!H", resp[1:3])[0]
                if rcv_pid != pid:
                    continue
                if resp[3] == 0x80:
                    raise MQTTException("Subscription failed")
                return

    def wait_msg(self, blocking=True):
        """
        Block until any MQTT packet is received and process if needed.

        Returns packet type for non-PUBLISH packets, or PUBLISH opcode when a
        publish was processed. Returns `PINGRESP` for keepalive ping responses.
        """
        res = self.transport.read(1, blocking=blocking)

        if res is None:
            return None
        if res == b"":
            raise OSError(-1)

        if res == b"\xD0":  # PINGRESP
            remaining = self.transport.read(1, blocking=blocking)
            if remaining is None:
                return None
            return MQTTPacketBuilder.PINGRESP

        op = res[0]

        if op & 0xF0 != 0x30:
            return op

        remaining = MQTTPacketBuilder.decode_varlen(
            self.transport,
            blocking=blocking,
        )
        if remaining is None:
            return None

        topic_len_data = self.transport.read(2, blocking=blocking)
        if topic_len_data is None:
            return None
        topic_len = struct.unpack("!H", topic_len_data)[0]

        topic = self.transport.read(topic_len, blocking=blocking)
        if topic is None:
            return None
        remaining -= topic_len + 2

        pid = None
        if op & 0x06:
            pid_data = self.transport.read(2, blocking=blocking)
            if pid_data is None:
                return None
            pid = struct.unpack("!H", pid_data)[0]
            remaining -= 2

        msg = self.transport.read(remaining, blocking=blocking)
        if msg is None:
            return None

        if self.cb:
            self.cb(topic, msg)

        if (op & 0x06) == 0x02:
            ack = bytearray(b"\x40\x02")
            ack.extend(struct.pack("!H", pid))
            self.transport.write(ack)

        elif (op & 0x06) == 0x04:
            raise NotImplementedError("QoS 2 not supported")

        return op

    def check_msg(self):
        """
        Poll for available packet without permanently switching socket mode.
        """
        self.transport.setblocking(False)
        self.transport.begin_read_transaction()
        try:
            result = self.wait_msg(blocking=False)
            if self.transport.read_was_incomplete:
                self.transport.rollback_read_transaction()
            else:
                self.transport.commit_read_transaction()
            return result
        except Exception:
            self.transport.commit_read_transaction()
            raise
        finally:
            self.transport.setblocking(True)
