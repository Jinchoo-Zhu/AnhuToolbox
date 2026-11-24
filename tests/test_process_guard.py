# -*- coding: utf-8 -*-
"""Windows child-process cleanup tests."""

import os
import subprocess
import sys
import time
import unittest

from anhutoolbox.process_guard import WindowsJob


class ProcessGuardTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Job Object only")
    def test_closing_job_terminates_assigned_child(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=flags,
        )
        job = WindowsJob()
        try:
            self.assertTrue(job.assign(child.pid))
            self.assertIsNone(child.poll())
            job.close()
            deadline = time.monotonic() + 3
            while child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertIsNotNone(child.poll())
        finally:
            job.close()
            if child.poll() is None:
                child.kill()
                child.wait(2)


if __name__ == "__main__":
    unittest.main()
