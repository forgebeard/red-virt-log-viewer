from __future__ import annotations

from core.models import DecodedLine
from parsers import choose_parser
from parsers.engine import EngineParser
from parsers.journal import JournalParser
from parsers.qemu import QemuParser
from parsers.vdsm import VdsmParser
from tests.helpers import TempBundleTest


def _lines(text: str):
    return [
        DecodedLine(line_no=index, text=line)
        for index, line in enumerate(text.splitlines(), 1)
    ]


class ParserTests(TempBundleTest):
    def test_engine_header_and_stack(self) -> None:
        text = (
            "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
            "java.lang.RuntimeException: boom\n"
            "\tat org.ovirt.Foo.bar(Foo.java:1)\n"
            "2026-07-13 00:00:09,000+10 ERROR [org.ovirt.engine] (thread) [cid] second\n"
        )
        parsed = EngineParser().parse(_lines(text))
        self.assertEqual(len(parsed.records), 2)
        self.assertEqual(parsed.records[0].start_line, 1)
        self.assertEqual(parsed.records[0].end_line, 3)
        self.assertEqual(parsed.records[0].level, "INFO")
        self.assertIn("RuntimeException", parsed.records[0].preview)
        self.assertEqual(parsed.records[1].level, "ERROR")
        self.assertIsNotNone(parsed.records[0].timestamp_utc_us)

    def test_engine_plus_0330(self) -> None:
        text = "2026-01-01 12:00:00,000+03:30 WARN  [org.ovirt.engine] (t) [] tz\n"
        rec = EngineParser().parse(_lines(text)).records[0]
        self.assertIsNone(rec.time_issue)
        self.assertEqual(rec.timestamp_raw, "2026-01-01 12:00:00,000+03:30")

    def test_header_before_engine_is_issue_then_records(self) -> None:
        text = (
            "header before records\n"
            "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
        )
        parsed = EngineParser().parse(_lines(text))
        self.assertEqual(len(parsed.records), 1)
        self.assertTrue(parsed.issues)

    def test_vdsm_vmid_is_identifier_not_guessed_from_other_uuid(self) -> None:
        disk = "33333333-3333-4333-8333-333333333333"
        vm = "11111111-1111-4111-8111-111111111111"
        text = (
            "2026-08-28 13:01:03,184+0800 INFO  (jsonrpc/2) [api.virt] "
            "START getVM vmId='%s' disk=%s (api:48)\n" % (vm, disk)
        )
        rec = VdsmParser().parse(_lines(text)).records[0]
        types_values = [(i.ident_type, i.value) for i in rec.identifiers]
        self.assertIn(("vm_uuid", vm), types_values)
        self.assertNotIn(("vm_uuid", disk), types_values)

    def test_qemu_launch_block_binds_name_and_uuid(self) -> None:
        block = (
            "2026-05-21 01:35:57.030+0000: starting up libvirt version: 7.6.0\n"
            "LC_ALL=C \\\n"
            "-name guest=vm-demo-01.example.test,debug-threads=on \\\n"
            "-uuid 11111111-1111-4111-8111-111111111111 \\\n"
            "-msg timestamp=on\n"
            "2026-05-21T01:35:57.210151Z qemu-system-x86_64: warning: spice\n"
            "2026-05-21 01:40:00.000+0000: starting up other\n"
            "-name guest=vm-demo-02.example.test \\\n"
            "-uuid 22222222-2222-4222-8222-222222222222\n"
        )
        records = QemuParser().parse(_lines(block)).records
        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first.start_line, 1)
        self.assertEqual(first.end_line, 5)
        names = [i.value for i in first.identifiers if i.ident_type == "vm_name"]
        uuids = [i.value for i in first.identifiers if i.ident_type == "vm_uuid"]
        self.assertEqual(names, ["vm-demo-01.example.test"])
        self.assertEqual(uuids, ["11111111-1111-4111-8111-111111111111"])
        third = records[2]
        names2 = [i.value for i in third.identifiers if i.ident_type == "vm_name"]
        uuids2 = [i.value for i in third.identifiers if i.ident_type == "vm_uuid"]
        self.assertEqual(names2, ["vm-demo-02.example.test"])
        self.assertEqual(uuids2, ["22222222-2222-4222-8222-222222222222"])
        self.assertNotEqual(uuids[0], uuids2[0])

    def test_journal_skips_boot_and_wrapper(self) -> None:
        text = (
            "-----info journalctl -p err -----\n"
            "\n"
            "Oct 10 12:50:50 host-demo systemd[1]: Failed to start x\n"
            "-- Boot abcdef --\n"
            "Oct 10 13:39:37 host-demo sshd[1]: error: disconnect\n"
        )
        parsed = JournalParser().parse(_lines(text))
        self.assertEqual(len(parsed.records), 2)
        self.assertEqual(parsed.records[0].time_issue, "missing_year_and_timezone")
        self.assertIsNone(parsed.records[0].timestamp_utc_us)
        self.assertEqual(parsed.records[0].level, "unknown")
        dated = JournalParser().parse(_lines(text), journal_year=2026, journal_utc_offset="Z")
        self.assertIsNotNone(dated.records[0].timestamp_utc_us)
        self.assertIsNone(dated.records[0].time_issue)

    def test_choose_parser_engine(self) -> None:
        text = "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
        assessment = choose_parser(_lines(text), relative_path="ovirt-engine/engine.log")
        self.assertEqual(assessment.parser_id, "engine")

    def test_header_then_engine_still_assessed(self) -> None:
        text = (
            "not a log yet\n"
            "\n"
            "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
        )
        assessment = choose_parser(_lines(text), component_hint="engine")
        self.assertEqual(assessment.parser_id, "engine")
