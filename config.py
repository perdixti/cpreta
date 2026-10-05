import json
import os
from pathlib import Path
import socket
import tempfile

DEFAULTS = dict(monitor_enabled=True, observation_mode='app', idle_minutes=3,
                change_seconds=30, cooldown_minutes=5, checkin_minutes=20,
                snooze_minutes=5, max_prompts_hour=6)


class ConfigStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / 'config.json'
        if not self.file.exists():
            self.save(dict(device_name=socket.gethostname(), reports_directory='relatorios', auto_start=False))

    def read(self):
        try:
            value = json.loads(self.file.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('Formato de configuração inválido.')
            return DEFAULTS | value
        except (ValueError, OSError) as error:
            raise RuntimeError(f'Não foi possível ler {self.file}. Corrija ou restaure o JSON antes de iniciar.') from error

    def reports_path(self, config):
        path = Path(config['reports_directory']).expanduser()
        return path if path.is_absolute() else self.data_dir / path

    def save(self, config):
        config = DEFAULTS | config
        if not config['device_name'] or len(config['device_name']) > 100:
            raise ValueError('Informe um nome de dispositivo entre 1 e 100 caracteres.')
        if not config['reports_directory'] or len(config['reports_directory']) > 4096:
            raise ValueError('Informe um diretório local válido.')
        if config['observation_mode'] not in ('idle', 'app'):
            raise ValueError('Escolha um modo de sugestão válido.')
        for key, low, high in [('idle_minutes', 1, 120), ('change_seconds', 15, 600), ('cooldown_minutes', 2, 120), ('checkin_minutes', 0, 180), ('snooze_minutes', 1, 120), ('max_prompts_hour', 1, 12)]:
            try:
                config[key] = int(config[key])
            except (TypeError, ValueError):
                raise ValueError('Os intervalos devem ser números inteiros.')
            if not low <= config[key] <= high:
                raise ValueError(f'Intervalo inválido: use entre {low} e {high}.')
        path = self.reports_path(config)
        if str(path).startswith(('\\\\', '//')):
            raise ValueError('Use uma pasta local, sem caminho de rede.')
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.data_dir, delete=False) as handle:
                temp = Path(handle.name)
                json.dump(config, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            os.replace(temp, self.file)
        except OSError as error:
            if 'temp' in locals():
                temp.unlink(missing_ok=True)
            raise OSError('Não foi possível salvar. Confira o caminho e as permissões das pastas.') from error
