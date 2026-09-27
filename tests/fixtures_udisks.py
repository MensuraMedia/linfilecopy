"""Recorded/synthetic UDisks2 GetManagedObjects data (serials anonymised)."""
UD = "org.freedesktop.UDisks2"
B = "/org/freedesktop/UDisks2/block_devices/"
D = "/org/freedesktop/UDisks2/drives/"


def dev(path: str) -> list[int]:
    return list(path.encode()) + [0]


def block(device, uuid, fstype, usage, size, drive="/", label="", mounts=None, crypt=None, backing="/",
          mdraid="/", ignore=False, system=True):
    ifaces = {f"{UD}.Block": {"Device": dev(device), "IdUUID": uuid, "IdType": fstype, "IdUsage": usage,
                              "IdLabel": label, "Size": size, "Drive": drive, "CryptoBackingDevice": backing,
                              "MDRaid": mdraid, "HintIgnore": ignore, "HintSystem": system, "HintName": ""}}
    if mounts is not None:
        ifaces[f"{UD}.Filesystem"] = {"MountPoints": [dev(m) for m in mounts]}
    if crypt is not None:
        ifaces[f"{UD}.Encrypted"] = {"CleartextDevice": crypt}
    return ifaces


OBJECTS = {
    D + "SSD": {f"{UD}.Drive": {"Model": "512GB SSD", "Vendor": "", "Removable": False, "Ejectable": False,
                                "ConnectionBus": "", "CanPowerOff": False}},
    D + "USB": {f"{UD}.Drive": {"Model": "USB DISK 3.0", "Vendor": "", "Removable": True, "Ejectable": True,
                                "ConnectionBus": "usb", "CanPowerOff": True}},
    D + "T7": {f"{UD}.Drive": {"Model": "T7 Shield", "Vendor": "Samsung", "Removable": False, "Ejectable": False,
                               "ConnectionBus": "usb", "CanPowerOff": True}},
    B + "loop0": block("/dev/loop0", "", "squashfs", "filesystem", 1000, mounts=["/snap/x"]),
    B + "nvme0n1p1": block("/dev/nvme0n1p1", "4A28-89EB", "vfat", "filesystem", 104857600, D + "SSD", "EFI",
                           ["/boot/efi"], ignore=True),
    B + "nvme0n1p2": block("/dev/nvme0n1p2", "c6c1", "ext4", "filesystem", 214748364800, D + "SSD", "", ["/"]),
    B + "nvme0n1p3": block("/dev/nvme0n1p3", "e1ee", "swap", "other", 17179869184, D + "SSD"),
    B + "nvme1n1p1": block("/dev/nvme1n1p1", "5edb", "ext4", "filesystem", 2000397868544, D + "SSD", "", ["/home"]),
    B + "sda1": block("/dev/sda1", "B49B-37C5", "exfat", "filesystem", 62025367552, D + "USB", "",
                      ["/media/user/B49B-37C5"], system=False),
    B + "sdb1": block("/dev/sdb1", "t7-uuid", "ext4", "filesystem", 1000204886016, D + "T7", "T7 Shield", [],
                      system=False),
    # RAID 1 array with a locked LUKS container
    "/org/freedesktop/UDisks2/mdraid/md0": {f"{UD}.MDRaid": {"Level": "raid1", "Name": "host:archive"}},
    B + "md0": block("/dev/md0", "luks-uuid", "crypto_LUKS", "crypto", 8001563222016, "/", "", crypt="/",
                     mdraid="/org/freedesktop/UDisks2/mdraid/md0"),
}

UNLOCKED = dict(OBJECTS)
UNLOCKED[B + "md0"] = block("/dev/md0", "luks-uuid", "crypto_LUKS", "crypto", 8001563222016, "/", "",
                            crypt=B + "dm_2d0", mdraid="/org/freedesktop/UDisks2/mdraid/md0")
UNLOCKED[B + "dm_2d0"] = block("/dev/dm-0", "archive-fs", "ext4", "filesystem", 8001546444800, "/", "Archive",
                               ["/mnt/archive"], backing=B + "md0")
