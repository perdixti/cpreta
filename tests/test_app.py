import json
import shutil
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        startup_patch = patch('app.AutoStart')
        self.startup = startup_patch.start().return_value
        self.startup.status.return_value = dict(enabled=False, supported=True, message='Test startup')
        self.addCleanup(startup_patch.stop)
        self.root = Path(__file__).resolve().parent / ('run-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.app = create_app(self.root)
        self.app.testing = True
        self.client = self.app.test_client()
        self.client.get('/configuracao')

    def tearDown(self):
        assert self.root.parent == Path(__file__).resolve().parent
        shutil.rmtree(self.root)

    def token(self):
        with self.client.session_transaction() as session:
            return session['csrf']

    def test_persistence(self):
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='Estação Lucas', reports_directory='nova', auto_start='on'))
        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.root / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['device_name'], 'Estação Lucas')
        self.assertTrue(saved['auto_start'])
        self.startup.set_enabled.assert_called_once_with(True)
        self.assertTrue((self.root / 'nova').is_dir())
        self.assertIn('Estação Lucas', create_app(self.root).test_client().get('/configuracao').get_data(as_text=True))

    def test_startup_denied_preserves_previous_settings(self):
        before = (self.root / 'config.json').read_text(encoding='utf-8')
        self.startup.set_enabled.side_effect = PermissionError('Access denied')
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='Novo', reports_directory='relatorios', auto_start='on'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('configurações anteriores foram mantidas', response.get_data(as_text=True))
        self.assertEqual(json.loads((self.root / 'config.json').read_text(encoding='utf-8')), json.loads(before))

    def test_disable_startup_from_settings(self):
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='PC', reports_directory='relatorios'))
        self.assertEqual(response.status_code, 302)
        self.startup.set_enabled.assert_called_once_with(False)

    def test_empty_and_listing(self):
        self.assertIn('Tudo pronto', self.client.get('/relatorios').get_data(as_text=True))
        (self.root / 'relatorios' / 'teste.txt').write_text('Olá', encoding='utf-8')
        self.assertIn('teste.txt', self.client.get('/relatorios').get_data(as_text=True))
        self.assertIn('Olá', self.client.get('/relatorios/visualizar/teste.txt').get_data(as_text=True))

    def test_html_escaped(self):
        (self.root / 'relatorios' / 'x.html').write_text('<script>alert(1)</script>', encoding='utf-8')
        text = self.client.get('/relatorios/visualizar/x.html').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('<script>alert(1)', text)

    def test_security(self):
        self.assertEqual(self.client.get('/configuracao').headers['Referrer-Policy'], 'same-origin')
        self.assertEqual(self.client.post('/configuracao', data={}).status_code, 403)
        self.assertEqual(self.client.post('/configuracao', data={'csrf': 'inválido'}).status_code, 403)
        self.assertEqual(self.client.get('/configuracao', headers={'Host': 'evil.example'}).status_code, 400)
        (self.root / 'secret.txt').write_text('segredo')
        self.assertEqual(self.client.get('/relatorios/visualizar/../secret.txt').status_code, 404)
        self.assertEqual(self.client.get('/relatorios/visualizar/..%5Csecret.txt').status_code, 404)
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='a', reports_directory='nova'), headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_browser_form_origin(self):
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='Meu PC', reports_directory='relatorios', auto_start='on'), headers={'Origin': 'http://localhost'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(json.loads((self.root / 'config.json').read_text(encoding='utf-8'))['auto_start'])
        response = self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='Outro', reports_directory='relatorios'), headers={'Origin': 'null'})
        self.assertEqual(response.status_code, 403)

    def test_validation_and_limits(self):
        self.assertEqual(self.client.post('/configuracao', data=dict(csrf=self.token(), device_name='', reports_directory='a')).status_code, 400)
        (self.root / 'relatorios' / 'big.txt').write_bytes(b'a' * (2 * 1024 * 1024 + 1))
        self.assertEqual(self.client.get('/relatorios/visualizar/big.txt').status_code, 302)
        (self.root / 'relatorios' / 'file.exe').write_bytes(b'test')
        self.assertEqual(self.client.get('/relatorios/visualizar/file.exe').status_code, 415)


if __name__ == '__main__':
    unittest.main()
