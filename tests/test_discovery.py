from __future__ import annotations

import os
import tarfile

from core.discovery import classify_file, component_hint_from_path, discover_bundle, name_kind
from core.models import (
    STATUS_EMPTY,
    STATUS_GZIP,
    STATUS_TEXT,
    STATUS_UNSUPPORTED_BINARY,
    STATUS_UNSUPPORTED_CONTAINER,
    STATUS_XZ,
    Bundle,
)
from tests.helpers import TempBundleTest, write_gzip, write_text, write_xz


class DiscoveryTests(TempBundleTest):
    def test_component_hints(self) -> None:
        self.assertEqual(
            component_hint_from_path("rv_info/logs/ovirt-engine/engine.log"),
            "engine",
        )
        self.assertEqual(component_hint_from_path("log/vdsm/vdsm.log"), "vdsm")
        self.assertEqual(
            component_hint_from_path("var/log/libvirt/qemu/vm-demo.log"),
            "qemu",
        )
        self.assertEqual(
            component_hint_from_path("rv_info/journalctl/journalctl_p_err.txt"),
            "journal",
        )
        self.assertEqual(component_hint_from_path("qemu-vm.log"), "qemu")
        self.assertEqual(component_hint_from_path("notes.txt"), "unknown")

    def test_name_kind_prefers_container_over_gzip(self) -> None:
        self.assertEqual(name_kind("dump.tar.gz"), "container")
        self.assertEqual(name_kind("vdsm.log.1.gz"), "gzip")
        self.assertEqual(name_kind("vdsm.log.1.xz"), "xz")

    def test_walk_classifies_mixed_tree(self) -> None:
        write_text(self.path("rv_info", "logs", "ovirt-engine", "engine.log"), "INFO engine\n")
        write_text(self.path("log", "vdsm", "vdsm.log"), "INFO vdsm\n")
        write_text(self.path("var", "log", "libvirt", "qemu", "vm.log"), "qemu start\n")
        write_text(self.path("rv_info", "journalctl", "out.txt"), "Jul 12 13:26:46 host msg\n")
        write_text(self.path("support folder", "файл.log"), "unicode path\n")
        write_text(self.path("empty.log"), "")
        write_gzip(self.path("log", "vdsm", "vdsm.log.1.gz"), "gz line\n")
        write_xz(self.path("log", "vdsm", "vdsm.log.1.xz"), "xz line\n")
        with open(self.path("blob.bin"), "wb") as handle:
            handle.write(b"\x00\x01\x02binary")
        archive = self.path("nested.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            info_path = self.path("rv_info", "logs", "ovirt-engine", "engine.log")
            tar.add(info_path, arcname="engine.log")
        write_text(self.path("header.log"), "header before records\nreal event\n")

        bundle = Bundle(bundle_id="b1", root_path=self.root, label="t")
        files = discover_bundle(bundle)
        by_rel = {item.relative_path: item for item in files}

        self.assertEqual(by_rel["rv_info/logs/ovirt-engine/engine.log"].status, STATUS_TEXT)
        self.assertEqual(by_rel["rv_info/logs/ovirt-engine/engine.log"].component_hint, "engine")
        self.assertEqual(by_rel["log/vdsm/vdsm.log"].component_hint, "vdsm")
        self.assertEqual(by_rel["var/log/libvirt/qemu/vm.log"].component_hint, "qemu")
        self.assertEqual(by_rel["rv_info/journalctl/out.txt"].component_hint, "journal")
        self.assertEqual(by_rel["empty.log"].status, STATUS_EMPTY)
        self.assertEqual(by_rel["log/vdsm/vdsm.log.1.gz"].status, STATUS_GZIP)
        self.assertEqual(by_rel["log/vdsm/vdsm.log.1.xz"].status, STATUS_XZ)
        self.assertEqual(by_rel["blob.bin"].status, STATUS_UNSUPPORTED_BINARY)
        self.assertEqual(by_rel["nested.tar.gz"].status, STATUS_UNSUPPORTED_CONTAINER)
        self.assertIn("support folder/файл.log", by_rel)
        self.assertTrue(by_rel["header.log"].searchable)

    def test_skips_symlinked_directory(self) -> None:
        write_text(self.path("real", "a.log"), "inside\n")
        write_text(self.path("outside.log"), "secret\n")
        link = self.path("linkdir")
        try:
            os.symlink(self.path("real"), link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        bundle = Bundle(bundle_id="b1", root_path=self.root, label="t")
        files = discover_bundle(bundle)
        rels = [item.relative_path for item in files]
        self.assertNotIn("linkdir/a.log", rels)

    def test_empty_gzip_name_is_empty_by_size(self) -> None:
        path = self.path("vdsm.log.gz")
        write_text(path, "")
        item = classify_file(path, "vdsm.log.gz", "b1")
        self.assertEqual(item.status, STATUS_EMPTY)
