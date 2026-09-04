"""Stream decoded lines from plain text, gzip and xz files. Line numbers start at 1."""

from __future__ import annotations

import gzip
from typing import Iterator, Optional, Tuple

from .jobs import CancellationToken
from .models import COMPRESSION_GZIP, COMPRESSION_NONE, COMPRESSION_XZ, DecodedLine

try:
    import lzma
except ImportError:  # pragma: no cover - plugin_host 3.3
    lzma = None


READ_CHUNK = 64 * 1024


class ReaderError(Exception):
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__("%s: %s" % (path, message))


def lzma_available() -> bool:
    return lzma is not None


def _decode_bytes(raw: bytes, encoding: str) -> Tuple[str, bool]:
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    try:
        return raw.decode(encoding), False
    except UnicodeDecodeError:
        return raw.decode(encoding, errors="replace"), True


def _open_binary(path: str, compression: str):
    handle = open(path, "rb")
    try:
        if compression in (COMPRESSION_GZIP, "gzip"):
            return gzip.GzipFile(fileobj=handle), handle
        if compression in (COMPRESSION_XZ, "xz"):
            if lzma is None:
                handle.close()
                raise ReaderError(path, "lzma_unavailable")
            return lzma.LZMAFile(handle), handle
        return handle, None
    except ReaderError:
        raise
    except OSError as exc:
        handle.close()
        raise ReaderError(path, str(exc))
    except Exception as exc:
        handle.close()
        raise ReaderError(path, str(exc))


def iter_lines(
    path: str,
    compression: str = COMPRESSION_NONE,
    encoding: str = "utf-8",
    max_line_bytes: int = 1024 * 1024,
    cancel: Optional[CancellationToken] = None,
) -> Iterator[DecodedLine]:
    stream = None
    nested = None
    try:
        stream, nested = _open_binary(path, compression)
        yield from _iter_decoded(
            stream,
            encoding=encoding,
            max_line_bytes=max_line_bytes,
            cancel=cancel,
        )
    except ReaderError:
        raise
    except OSError as exc:
        raise ReaderError(path, str(exc))
    except Exception as exc:
        name = type(exc).__name__
        raise ReaderError(path, "%s: %s" % (name, exc))
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if nested is not None:
            try:
                nested.close()
            except Exception:
                pass


def _iter_decoded(
    stream,
    encoding: str,
    max_line_bytes: int,
    cancel: Optional[CancellationToken],
) -> Iterator[DecodedLine]:
    line_no = 0
    buf = b""
    skipping_rest = False
    while True:
        if cancel is not None and cancel.cancelled:
            return
        chunk = stream.read(READ_CHUNK)
        if not chunk:
            break
        buf += chunk
        while True:
            if cancel is not None and cancel.cancelled:
                return
            newline_at = buf.find(b"\n")
            if skipping_rest:
                if newline_at < 0:
                    buf = b""
                    break
                buf = buf[newline_at + 1 :]
                skipping_rest = False
                continue
            if newline_at < 0:
                if max_line_bytes > 0 and len(buf) > max_line_bytes:
                    piece = buf[:max_line_bytes]
                    text, replaced = _decode_bytes(piece, encoding)
                    line_no += 1
                    yield DecodedLine(
                        line_no=line_no,
                        text=text,
                        truncated=True,
                        had_replacements=replaced,
                    )
                    buf = buf[max_line_bytes:]
                    skipping_rest = True
                    continue
                break
            raw_line = buf[:newline_at]
            buf = buf[newline_at + 1 :]
            truncated = False
            if max_line_bytes > 0 and len(raw_line) > max_line_bytes:
                raw_line = raw_line[:max_line_bytes]
                truncated = True
            text, replaced = _decode_bytes(raw_line, encoding)
            line_no += 1
            yield DecodedLine(
                line_no=line_no,
                text=text,
                truncated=truncated,
                had_replacements=replaced,
            )
    if skipping_rest:
        return
    if buf:
        truncated = False
        raw_line = buf
        if max_line_bytes > 0 and len(raw_line) > max_line_bytes:
            raw_line = raw_line[:max_line_bytes]
            truncated = True
        text, replaced = _decode_bytes(raw_line, encoding)
        line_no += 1
        yield DecodedLine(
            line_no=line_no,
            text=text,
            truncated=truncated,
            had_replacements=replaced,
        )
