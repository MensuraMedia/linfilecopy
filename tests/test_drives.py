import unittest

from linfilecopy.engine import drives as dv
from linfilecopy.engine.filesystems import capabilities_for, fs_type_for_path, parse_mountinfo
from linfilecopy.model.enums import DriveKind
from linfilecopy.model.job import Endpoint
from tests.fixtures_udisks import OBJECTS, UNLOCKED


class ParseTest(unittest.TestCase):
    def test_kinds_labels_and_filtering(self) -> None:
        ds = dv.parse_managed_objects(OBJECTS)
        by_dev = {d.device: d for d in ds}
        self.assertNotIn("/dev/loop0", by_dev)          # loop devices skipped
        self.assertNotIn("/dev/nvme0n1p3", by_dev)      # swap skipped
        self.assertEqual(by_dev["/dev/nvme0n1p2"].label, "System")
        self.assertEqual(by_dev["/dev/nvme1n1p1"].label, "Home")
        usb = by_dev["/dev/sda1"]
        self.assertEqual((usb.kind, usb.label, usb.fs_type), (DriveKind.REMOVABLE, "62 GB Volume", "exfat"))
        self.assertTrue(usb.can_power_off)
        self.assertEqual(by_dev["/dev/sdb1"].kind, DriveKind.REMOVABLE)  # USB bus, not flagged removable
        self.assertTrue(by_dev["/dev/nvme0n1p1"].system)
        arr = by_dev["/dev/md0"]
        self.assertEqual((arr.kind, arr.encrypted, arr.locked, arr.label), (DriveKind.ARRAY, True, True, "archive"))

    def test_visible_hides_system(self) -> None:
        ds = dv.parse_managed_objects(OBJECTS)
        self.assertNotIn("/dev/nvme0n1p1", [d.device for d in dv.visible_drives(ds)])
        self.assertIn("/dev/nvme0n1p1", [d.device for d in dv.visible_drives(ds, show_system=True)])

    def test_unlocked_container_replaced_by_cleartext_fs(self) -> None:
        ds = dv.parse_managed_objects(UNLOCKED)
        devs = [d.device for d in ds]
        self.assertNotIn("/dev/md0", devs)
        fs = next(d for d in ds if d.device == "/dev/dm-0")
        self.assertEqual((fs.label, fs.kind, fs.container_uuid), ("Archive", DriveKind.ARRAY, "luks-uuid"))

    def test_order_internal_first(self) -> None:
        kinds = [d.kind for d in dv.parse_managed_objects(OBJECTS)]
        self.assertEqual(kinds, sorted(kinds, key=[DriveKind.INTERNAL, DriveKind.REMOVABLE, DriveKind.ARRAY].index))


class EndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.drives = dv.parse_managed_objects(OBJECTS)

    def test_endpoint_for_path_on_usb(self) -> None:
        ep = dv.endpoint_for_path("/media/user/B49B-37C5/Documents", self.drives)
        self.assertEqual((ep.volume_uuid, ep.relative_path, ep.kind), ("B49B-37C5", "Documents", DriveKind.REMOVABLE))

    def test_endpoint_on_root_is_plain(self) -> None:
        ep = dv.endpoint_for_path("/srv/data", self.drives)
        self.assertIsNone(ep.volume_uuid)
        self.assertEqual(ep.fs_type, "ext4")

    def test_resolve_follows_new_mount_point(self) -> None:
        ep = Endpoint("/media/old/B49B-37C5/Documents", "B49B-37C5", "62 GB Volume", "Documents")
        res = dv.resolve_endpoint(ep, self.drives)
        self.assertEqual((res.state, res.path), (dv.EndpointState.READY, "/media/user/B49B-37C5/Documents"))

    def test_resolve_states(self) -> None:
        self.assertEqual(dv.resolve_endpoint(Endpoint("/x", "gone"), self.drives).state, dv.EndpointState.MISSING)
        self.assertEqual(dv.resolve_endpoint(Endpoint("/x", "t7-uuid"), self.drives).state, dv.EndpointState.NOT_MOUNTED)
        locked = dv.resolve_endpoint(Endpoint("/mnt/archive/sam", "archive-fs", container_uuid="luks-uuid"), self.drives)
        self.assertEqual(locked.state, dv.EndpointState.LOCKED)
        self.assertEqual(locked.container.uuid, "luks-uuid")
        self.assertEqual(dv.resolve_endpoint(Endpoint("/plain"), self.drives).state, dv.EndpointState.READY)


class FilesystemTest(unittest.TestCase):
    MOUNTINFO = (
        "22 1 259:2 / / rw,relatime shared:1 - ext4 /dev/nvme0n1p2 rw\n"
        "30 22 259:5 / /home rw,relatime shared:2 - ext4 /dev/nvme1n1p1 rw\n"
        "88 30 8:1 / /media/user/My\\040Stick rw,nosuid - exfat /dev/sda1 rw\n"
    )

    def test_mountinfo_and_escapes(self) -> None:
        mounts = parse_mountinfo(self.MOUNTINFO)
        self.assertEqual(mounts[2].mount_point, "/media/user/My Stick")
        self.assertEqual(fs_type_for_path("/media/user/My Stick/a/b", mounts), "exfat")
        self.assertEqual(fs_type_for_path("/home/sam", mounts), "ext4")
        self.assertEqual(fs_type_for_path("/etc", mounts), "ext4")

    def test_capabilities(self) -> None:
        self.assertTrue(capabilities_for("ext4").full)
        fat = capabilities_for("vfat")
        self.assertEqual(fat.max_file_size, 4 * 1024**3 - 1)
        self.assertIn("files over 4 GB", fat.summary())
        self.assertEqual(capabilities_for("fuseblk").label, "NTFS")
        self.assertEqual(capabilities_for(None).fs_type, "unknown")


class FriendlyErrorTest(unittest.TestCase):
    def test_messages(self) -> None:
        self.assertIn("busy", dv._friendly("GDBus.Error:org.freedesktop.UDisks2.Error.DeviceBusy: target is busy"))
        self.assertIn("passphrase", dv._friendly("Error unlocking: Failed to activate device: Operation not permitted"))


if __name__ == "__main__":
    unittest.main()
