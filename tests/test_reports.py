import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from reports import seal, verified, LIMIT


class SavedReportTests(unittest.TestCase):
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
        self.client.get('/relatorios')
        with self.client.session_transaction() as session:
            self.csrf = session['csrf']
        self.folder = self.root / 'relatorios'

    def tearDown(self):
        assert self.root.parent == Path(__file__).resolve().parent
        shutil.rmtree(self.root)

    def activity(self):
        ledger = self.app.extensions['activities']
        ident = ledger.start(dict(category='trabalho', title='<script>alert(1)</script>', client='Cliente A', project='Demanda X'))
        ledger.continue_activity(ident, dict(note='Executei os testes', attempts=2, successes=1, failures=1, reason='Credencial expirada', result='Acesso corrigido'))

    def save(self, period='today'):
        return self.client.post('/relatorios/registrar', data={'csrf':self.csrf, 'period':period, 'title':'Meu relatório'})

    def test_saved_snapshot_opens_and_downloads(self):
        self.activity()
        response = self.save('week')
        self.assertEqual(response.status_code,302)
        self.assertIn('files=1',response.location)
        paths = list(self.folder.glob('*.html'))
        self.assertEqual(len(paths),1)
        path = paths[0]
        body = verified(path,self.app.secret_key).decode()
        self.assertIn('Cliente A',body)
        self.assertIn('Demanda X',body)
        self.assertIn('Credencial expirada',body)
        self.assertIn('Acesso corrigido',body)
        self.assertIn('&lt;script&gt;',body)
        self.assertNotIn('<script>',body)
        self.assertIn('<svg',body)
        self.assertIn('<style>',body)
        view = self.client.get('/relatorios/visualizar/'+path.name)
        self.assertIn('sandbox',view.get_data(as_text=True))
        rendered = self.client.get('/relatorios/conteudo/'+path.name)
        self.assertEqual(rendered.status_code,200)
        self.assertIn("default-src 'none'",rendered.headers['Content-Security-Policy'])
        self.assertIn('sandbox;',rendered.headers['Content-Security-Policy'])
        download = self.client.get('/relatorios/baixar/'+path.name)
        self.assertEqual(download.data,rendered.data)
        self.assertIn('attachment',download.headers['Content-Disposition'])
        first = path.read_bytes()
        self.save()
        self.assertEqual(len(list(self.folder.glob('*.html'))),2)
        self.assertEqual(path.read_bytes(),first)
        restarted = create_app(self.root).test_client()
        self.assertEqual(restarted.get('/relatorios/conteudo/'+path.name).status_code,200)

    def test_empty_invalid_and_unprotected_requests_do_not_write(self):
        self.assertEqual(self.client.post('/relatorios/registrar').status_code,403)
        self.assertEqual(self.save('wrong').status_code,400)
        response=self.save()
        self.assertIn('Registre uma atividade',self.client.get(response.location).get_data(as_text=True))
        self.assertEqual(list(self.folder.glob('*.html')),[])

    def test_modified_and_external_html_are_not_rendered(self):
        self.activity()
        self.save()
        path=next(self.folder.glob('*.html'))
        path.write_bytes(path.read_bytes()+b'<script>evil()</script>')
        self.assertEqual(self.client.get('/relatorios/conteudo/'+path.name).status_code,404)
        self.assertEqual(self.client.get('/relatorios/baixar/'+path.name).status_code,404)
        view=self.client.get('/relatorios/visualizar/'+path.name).get_data(as_text=True)
        self.assertIn('&lt;script&gt;evil()',view)
        self.assertNotIn('saved-report-frame',view)
        self.assertEqual(self.client.get('/relatorios/conteudo/../config.json').status_code,404)

    def test_configured_folder_and_write_error(self):
        store=self.app.extensions['config_store']
        store.save(store.read() | {'reports_directory':'personalizados'})
        self.activity()
        self.save()
        self.assertEqual(len(list((self.root/'personalizados').glob('*.html'))),1)
        with patch('app.seal',side_effect=OSError('unavailable')):
            response=self.save()
        self.assertIn('Não foi possível salvar',self.client.get(response.location).get_data(as_text=True))
        self.assertEqual(len(list((self.root/'personalizados').glob('*.html'))),1)

    def test_large_report_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            seal('x'*LIMIT,self.app.secret_key)
