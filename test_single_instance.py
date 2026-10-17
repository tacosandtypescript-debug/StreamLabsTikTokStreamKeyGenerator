import os
import unittest
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from StreamLabsTikTokStreamKeyGenerator import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.key = "fpv-stream-test-" + uuid.uuid4().hex
        self.instances = []

    def tearDown(self):
        for instance in reversed(self.instances):
            instance.close()
        self.app.processEvents()

    def make(self):
        instance = SingleInstance(self.key)
        self.instances.append(instance)
        return instance

    def test_second_instance_activates_the_first_window(self):
        first = self.make()
        self.assertTrue(first.acquire())
        calls = []
        first.on_activation(lambda: calls.append(1))
        second = self.make()
        self.assertFalse(second.acquire())
        self.assertTrue(second.notify_existing())
        QTest.qWait(200)
        self.app.processEvents()
        self.assertEqual(calls, [1])

    def test_notification_without_a_server_reports_failure(self):
        second = self.make()
        self.assertFalse(second.notify_existing())


if __name__ == "__main__":
    unittest.main()
