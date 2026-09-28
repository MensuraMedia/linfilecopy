"""Example drives for screenshots, so published images never show the host's disks."""
from __future__ import annotations

from dataclasses import replace

from linfilecopy.engine.drives import DriveInfo
from linfilecopy.model.enums import DriveKind

GB = 1000**3


def demo_drives() -> list[DriveInfo]:
    return [
        DriveInfo("/demo/home", "/dev/nvme0n1p3", "demo-home", "Home", "ext4", 1_000 * GB, ("/home",),
                  DriveKind.INTERNAL, free=612 * GB, capacity=1_000 * GB),
        DriveInfo("/demo/usb", "/dev/sdb1", "5E1A-90C2", "64 GB Stick", "exfat", 64 * GB, ("/media/sam/5E1A-90C2",),
                  DriveKind.REMOVABLE, drive_path="/demo/drives/usb", can_power_off=True, ejectable=True, free=41 * GB, capacity=64 * GB),
        DriveInfo("/demo/t7", "/dev/sdc1", "demo-t7", "T7 Shield", "ext4", 1_000 * GB, ("/media/sam/T7",),
                  DriveKind.REMOVABLE, drive_path="/demo/drives/t7", can_power_off=True, free=60 * GB, capacity=1_000 * GB),
        replace(DriveInfo("/demo/md0", "/dev/md0", "demo-luks", "Archive", "crypto_LUKS", 8_000 * GB, (),
                          DriveKind.ARRAY, encrypted=True, locked=True), array_level="raid1"),
    ]


def install() -> None:
    """Make UDisksClient report the example drives instead of the real ones."""
    from linfilecopy.engine import drives

    drives.UDisksClient.list_drives = lambda self: demo_drives()  # type: ignore[method-assign]
