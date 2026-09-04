from __future__ import annotations

from core.jobs import CancellationToken
from core.readers import ReaderError, iter_lines
from tests.helpers import SAMPLE_TEXT, TempBundleTest, write_gzip, write_text, write_xz


class ReaderTests(TempBundleTest):
    def _assert_same_lines(self, plain: str, gz: str, xz: str) -> None:
        plain_lines = list(iter_lines(plain))
        gz_lines = list(iter_lines(gz, compression="gzip"))
        xz_lines = list(iter_lines(xz, compression="xz"))
        self.assertEqual([line.line_no for line in plain_lines], [1, 2, 3, 4])
        self.assertEqual(
            [line.text for line in plain_lines],
            [line.text for line in gz_lines],
        )
        self.assertEqual(
            [line.text for line in plain_lines],
            [line.text for line in xz_lines],
        )
        self.assertEqual(plain_lines[-1].text, "omega last line")

    def test_plain_gzip_xz_line_numbers_match(self) -> None:
        plain = self.path("a.log")
        gz = self.path("a.log.gz")
        xz = self.path("a.log.xz")
        write_text(plain, SAMPLE_TEXT)
        write_gzip(gz, SAMPLE_TEXT)
        write_xz(xz, SAMPLE_TEXT)
        self._assert_same_lines(plain, gz, xz)

    def test_crlf_and_missing_final_newline(self) -> None:
        path = self.path("crlf.log")
        with open(path, "wb") as handle:
            handle.write(b"one\r\ntwo")
        lines = list(iter_lines(path))
        self.assertEqual([line.text for line in lines], ["one", "two"])
        self.assertEqual([line.line_no for line in lines], [1, 2])

    def test_long_line_truncated_flag(self) -> None:
        path = self.path("long.log")
        write_text(path, "a" * 50 + "\nshort\n")
        lines = list(iter_lines(path, max_line_bytes=10))
        self.assertTrue(lines[0].truncated)
        self.assertEqual(len(lines[0].text), 10)
        self.assertEqual(lines[1].text, "short")
        self.assertEqual(lines[1].line_no, 2)

    def test_truncated_gzip_raises(self) -> None:
        gz = self.path("bad.gz")
        write_gzip(gz, SAMPLE_TEXT)
        with open(gz, "rb") as handle:
            data = handle.read()
        with open(gz, "wb") as handle:
            handle.write(data[:8])
        with self.assertRaises(ReaderError):
            list(iter_lines(gz, compression="gzip"))

    def test_cancel_stops_iteration(self) -> None:
        path = self.path("many.log")
        write_text(path, "\n".join("line-%s" % i for i in range(1000)) + "\n")
        token = CancellationToken()
        seen = 0
        for line in iter_lines(path, cancel=token):
            seen += 1
            if seen >= 5:
                token.cancel()
        self.assertLess(seen, 1000)
