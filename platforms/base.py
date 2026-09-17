from __future__ import annotations

import abc

from core.downloader import Downloader


class BasePlatform(abc.ABC):
    def __init__(self, token: str, downloader: Downloader):
        self.token = token
        self.downloader = downloader

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...
