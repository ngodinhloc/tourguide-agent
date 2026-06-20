from typing import Protocol


class ConsumerMessage(Protocol):
    body: bytes
