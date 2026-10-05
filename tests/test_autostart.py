import contextlib
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autostart import AutoStart, save_configuration, VALUE_NAME


class FakeRegistry:
    HKEY_CURRENT_USER = 'user'
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1
    def __init__(self):
        self.values = {'OtherApplication':'keep'}
    def OpenKey(self, *args):
        return contextlib.nullcontext(self)
    CreateKeyEx = OpenKey
    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        return self.values[name], self.REG_SZ
    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value
    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        del self.values[name]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.reg = FakeRegistry()
        self.manager = AutoStart(Path.cwd(), platform='win32', registry=self.reg)
        command = patch.object(self.manager, 'command', return_value='"pythonw.exe" "start_background.py" --no-browser')
        self.command = command.start()
        self.addCleanup(command.stop)

    def test_register_verify_reuse_and_remove_only_our_entry(self):
        self.assertFalse(self.manager.status()['enabled'])
        self.manager.set_enabled(True)
        self.assertTrue(self.manager.status()['enabled'])
        self.manager.set_enabled(True)
        self.manager.set_enabled(False)
        self.manager.set_enabled(False)
        self.assertEqual(self.reg.values, {'OtherApplication':'keep'})

    def test_other_installation_is_preserved(self):
        self.reg.values[VALUE_NAME] = 'different project'
        for enabled in (True,False):
            with self.assertRaises(OSError):
                self.manager.set_enabled(enabled)
        self.assertEqual(self.reg.values[VALUE_NAME], 'different project')

    def test_denied_registration_rolls_back_configuration(self):
        store = Mock()
        old = dict(device_name='PC', auto_start=False)
        new = dict(device_name='Changed', auto_start=True)
        store.read.return_value = old
        with patch.object(self.manager, 'write', side_effect=PermissionError('Access denied')):
            with self.assertRaises(OSError):
                save_configuration(store,new,self.manager)
        self.assertEqual(store.save.call_args_list[0].args[0],new)
        self.assertEqual(store.save.call_args_list[1].args[0],old)
        self.assertNotIn(VALUE_NAME,self.reg.values)

    def test_invalid_config_does_not_touch_system(self):
        store = Mock()
        store.save.side_effect = ValueError('invalid')
        manager = Mock()
        with self.assertRaises(ValueError):
            save_configuration(store,{},manager)
        manager.set_enabled.assert_not_called()

    def test_command_uses_windowless_interpreter_without_browser(self):
        manager=AutoStart('C:/CPreta Project',executable='C:/Python Test/python.exe',platform='win32')
        with patch.object(Path,'is_file',return_value=True):
            command=manager.command()
        self.assertIn('pythonw.exe"',command)
        self.assertIn('start_background.py"',command)
        self.assertTrue(command.endswith('--no-browser'))
        self.assertLessEqual(len(command),260)

    def test_non_windows_keeps_manual_mode(self):
        manager=AutoStart(Path.cwd(),platform='linux')
        self.assertFalse(manager.status()['supported'])
        manager.set_enabled(False)
        with self.assertRaises(OSError):
            manager.set_enabled(True)
