# Correlation fixtures (synthetic)

QEMU launch blocks and VDSM `vmId` lines used by `tests/test_entities.py`.

- Two launches share the guest name `vm-demo-01.example.test` and have different UUIDs.
- VDSM mentions those UUIDs as `vmId`. A disk UUID in the same line is not a VM.
- `qemu-name-only.log` has a guest name and no `-uuid`.
