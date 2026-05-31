"""Exception definitions for the MicroPython MQTT client."""


class MQTTException(Exception):
    """
    MQTT protocol-level error.

    Raised when broker responses are invalid, malformed, or explicitly
    indicate protocol failures such as a rejected connection or subscription.
    """

