"""Shared helpers for synthetic fixtures. gzip/xz copies are built in tests."""

from __future__ import annotations

import gzip
import os
import tarfile
import tempfile
import unittest

from core.models import SessionSettings

try:
    import lzma
except ImportError:
    lzma = None


SAMPLE_TEXT = (
    "header before records\n"
    "alpha line two\n"
    "literal .* not a regex\n"
    "omega last line\n"
)


def write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="\n") as handle:
        handle.write(text)


def write_gzip(path: str, text: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


def write_xz(path: str, text: str) -> None:
    if lzma is None:
        raise unittest.SkipTest("lzma is not available")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with lzma.open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


class TempBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self.settings = SessionSettings()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)
