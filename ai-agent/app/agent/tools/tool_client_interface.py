from abc import ABC, abstractmethod


class ToolClientInterface(ABC):
    @abstractmethod
    async def call(self, name: str, arguments: dict): ...
