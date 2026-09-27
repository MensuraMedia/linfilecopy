import os
import tempfile
import threading
import time
import unittest

from linfilecopy.engine.watcher import FolderWatcher


class WatcherTest(unittest.TestCase):
    def test_debounced_recursive_and_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "a"))
            hits = []
            event = threading.Event()

            def on_change() -> None:
                hits.append(time.monotonic())
                event.set()

            w = FolderWatcher([root], on_change, debounce=0.3)
            w.start()
            try:
                for i in range(5):                                   # a burst -> one callback
                    open(os.path.join(root, "a", f"f{i}"), "w").close()
                self.assertTrue(event.wait(3))
                time.sleep(0.5)
                self.assertEqual(len(hits), 1)
                event.clear()
                os.makedirs(os.path.join(root, "new", "deep"))       # new folders are watched
                time.sleep(0.2)
                event.wait(2)
                event.clear()
                open(os.path.join(root, "new", "deep", "x"), "w").close()
                self.assertTrue(event.wait(3))
                event.clear()
                w.suppress(1.0)                                      # our own writes are ignored
                open(os.path.join(root, "a", "ours"), "w").close()
                self.assertFalse(event.wait(0.8))
                event.clear()
                os.makedirs(os.path.join(root, ".lfc-trash", "x"))   # internal folders are ignored
                time.sleep(1.2)
                self.assertFalse(event.is_set())
            finally:
                w.stop()


if __name__ == "__main__":
    unittest.main()
