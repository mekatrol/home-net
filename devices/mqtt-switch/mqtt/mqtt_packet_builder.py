"""MQTT packet encoding and decoding helpers for MicroPython."""

import ustruct as struct


class MQTTPacketBuilder:
    """
    Stateless helper for MQTT wire-format primitives.

    Separating encoding logic from `MQTTClient` keeps protocol operations
    explicit and makes testing simpler for boundary-sensitive fields like
    MQTT's variable-length integer encoding.
    """

    # MQTT Control Packet Types used by the client.
    CONNECT = 0x10
    CONNACK = 0x20
    PUBLISH = 0x30
    PUBACK = 0x40
    SUBSCRIBE = 0x82
    SUBACK = 0x90
    PINGREQ = 0xC0
    PINGRESP = 0xD0
    DISCONNECT = 0xE0

    @staticmethod
    def encode_varlen(value):
        """
        Encode MQTT Remaining Length (base-128 continuation format).

        MQTT uses 7 bits per byte for value and the MSB as a continuation
        marker, so values can span multiple bytes as needed.
        """
        encoded = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                byte |= 0x80
            encoded.append(byte)
            if not value:
                break
        return encoded

    @staticmethod
    def decode_varlen(transport, blocking=True):
        """
        Decode MQTT Remaining Length using bytes read from `transport`.

        The transport object must provide `read(1)` and return a single-byte
        buffer on each call.
        """
        multiplier = 1
        value = 0

        while True:
            byte = transport.read(1, blocking=blocking)
            if byte is None:
                return None
            byte = byte[0]
            value += (byte & 0x7F) * multiplier
            if not (byte & 0x80):
                break
            multiplier <<= 7

        return value

    @staticmethod
    def encode_string(data):
        """
        Encode MQTT UTF-8 string/binary field with 2-byte length prefix.
        """
        return struct.pack("!H", len(data)) + data
