"""Per-user Windows logon registration. No service or administrator required."""
import argparse
from pathlib import Path
import subprocess
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'CPreta'


class AutoStart:
    def __init__(self, project, executable=None, platform=None, registry=None):
        self.project = Path(project).resolve()
        self.executable = Path(executable or sys.executable)
        self.platform = platform or sys.platform
        self.registry = registry

    def reg(self):
        if self.registry is None:
            import winreg
            self.registry = winreg
        return self.registry

    def command(self):
        pythonw = self.executable.with_name('pythonw.exe')
        script = self.project / 'start_background.py'
        if not pythonw.is_file() or not script.is_file():
            raise OSError('Python ou iniciador não encontrado. Confira a instalação do CPreta.')
        # list2cmdline quotes paths for Windows CreateProcess, without a shell.
        command = subprocess.list2cmdline([str(pythonw), str(script), '--no-browser'])
        if len(command) > 260:
            raise OSError('O caminho da instalação é longo demais para iniciar com o Windows. Use uma pasta mais curta.')
        return command

    def read(self):
        reg = self.reg()
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
                value, kind = reg.QueryValueEx(key, VALUE_NAME)
                return value
        except FileNotFoundError:
            return None

    def write(self, value):
        reg = self.reg()
        if value is None:
            try:
                with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                    reg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        else:
            with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, value)

    def status(self):
        if self.platform != 'win32':
            return dict(enabled=False, supported=False, message='A integração automática está disponível no Windows. Nesta versão, o Linux continua com início manual.')
        try:
            value = self.read()
            command = self.command()
            enabled = value == command
            message = 'Registrado para iniciar em segundo plano quando você entrar no Windows.' if enabled else 'Ainda não registrado. Marque a opção e salve para ativar.'
            if value and not enabled:
                message = 'Existe uma entrada de outra instalação do CPreta. Desative-a na instalação anterior antes de ativar esta.'
            return dict(enabled=enabled, supported=True, message=message)
        except OSError:
            return dict(enabled=False, supported=True, message='Não foi possível verificar a inicialização no Windows. Tente salvar novamente pela aplicação.')

    def set_enabled(self, enabled):
        if self.platform != 'win32':
            if enabled:
                raise OSError('A inicialização automática está disponível no Windows nesta versão.')
            return
        before = self.read()
        command = self.command()
        if before and before != command:
            raise OSError('Outra instalação do CPreta já usa a inicialização automática. Desative-a na instalação anterior.')
        wanted = command if enabled else None
        if before == wanted:
            return
        try:
            self.write(wanted)
            if self.read() != wanted:
                raise OSError('O Windows não confirmou a alteração da inicialização.')
        except OSError:
            # Restore only our entry, never touch other startup applications.
            try:
                if self.read() != before:
                    self.write(before)
            except OSError:
                pass
            raise


def save_configuration(store, config, startup):
    previous = store.read()
    store.save(config)
    try:
        startup.set_enabled(bool(config.get('auto_start')))
    except OSError as error:
        store.save(previous)
        raise OSError('Não foi possível alterar o início automático. As configurações anteriores foram mantidas. ' + str(error)) from error


if __name__ == '__main__':
    from config import ConfigStore
    parser = argparse.ArgumentParser(description='Inicialização do CPreta com o Windows')
    parser.add_argument('action', choices=['enable', 'disable', 'status'])
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    manager = AutoStart(project)
    try:
        if args.action != 'status':
            store = ConfigStore(project / 'data')
            save_configuration(store, store.read() | {'auto_start':args.action == 'enable'}, manager)
        print(manager.status()['message'])
    except OSError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
