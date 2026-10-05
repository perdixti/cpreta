import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch, Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import start_background as bg


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ('run-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.base = patch.object(bg, 'BASE', self.root)
        self.base.start()

    def tearDown(self):
        self.base.stop()
        assert self.root.parent == Path(__file__).resolve().parent
        shutil.rmtree(self.root)

    def test_existing_instance_is_reused(self):
        with patch.object(bg, 'healthy', return_value=True), patch.object(bg.subprocess, 'Popen') as spawn, patch.object(bg.webbrowser, 'open') as browser:
            self.assertEqual(bg.start(), 0)
            spawn.assert_not_called()
            browser.assert_called_once_with(bg.URL + '/relatorios')

    def test_detached_child_and_no_browser(self):
        with patch.object(bg, 'healthy', side_effect=[False, True]), patch.object(bg.subprocess, 'Popen') as spawn, patch.object(bg.webbrowser, 'open') as browser:
            self.assertEqual(bg.start(open_browser=False), 0)
            options = spawn.call_args.kwargs
            self.assertEqual(options['stdin'], bg.subprocess.DEVNULL)
            self.assertIs(options['stdout'], options['stderr'])
            self.assertTrue(options['close_fds'])
            if os.name == 'nt':
                self.assertTrue(options['creationflags'] & bg.subprocess.CREATE_NO_WINDOW)
            else:
                self.assertTrue(options['start_new_session'])
            browser.assert_not_called()

    def test_failed_child_does_not_open_browser(self):
        with patch.object(bg, 'healthy', return_value=False), patch.object(bg.subprocess, 'Popen') as spawn, patch.object(bg.webbrowser, 'open') as browser:
            spawn.return_value.poll.return_value = 1
            self.assertEqual(bg.start(), 1)
            browser.assert_not_called()

    def test_timeout_cleans_up_only_created_child(self):
        child = Mock()
        child.poll.return_value = None
        with patch.object(bg, 'healthy', return_value=False), patch.object(bg.subprocess, 'Popen', return_value=child), patch.object(bg.time, 'monotonic', side_effect=[0, 16]):
            self.assertEqual(bg.start(open_browser=False), 1)
            child.terminate.assert_called_once()
            child.wait.assert_called_once_with(timeout=5)
