import json
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from attention import Proposal


class WorkflowTests(unittest.TestCase):
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

    def tearDown(self):
        assert self.root.parent == Path(__file__).resolve().parent
        shutil.rmtree(self.root)

    def post(self, action, **values):
        return self.client.post('/atividade/registrar', data=dict(csrf=self.csrf, action=action, **values), headers={'Origin':'http://localhost'})

    def test_complete_web_journey(self):
        response = self.post('start', category='trabalho', title='Demanda de integração', client='Cliente A', project='ERP', note='Validar os dados')
        self.assertEqual(response.status_code, 200)
        ident = response.json['current']['activity_id']
        self.assertEqual(self.post('continue', activity_id=ident, note='Revisei as credenciais', attempts=3, successes=2, failures=1, reason='Chave expirada', result='Integração validada').status_code, 200)
        self.assertIn('Chave expirada', self.client.get('/relatorios/painel').get_data(as_text=True))
        self.assertIn('Integração validada', self.client.get('/relatorios/resumo.md').get_data(as_text=True))
        self.assertEqual(self.post('complete', activity_id=ident, note='Entregue').status_code, 200)
        self.assertIsNone(self.app.extensions['activities'].current())
        self.assertEqual(self.post('complete', activity_id=ident).status_code, 400)

    def test_invalid_attempts_preserve_current_activity(self):
        ident = self.post('start', category='estudo', title='Python').json['current']['activity_id']
        response = self.post('complete', activity_id=ident, attempts=1, failures=3)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.app.extensions['activities'].current()['activity_id'], ident)

    def test_native_unavailable_still_allows_web(self):
        response = self.client.post('/atividade/popup', data={'csrf':self.csrf})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.post('start', category='pessoal', title='Planejar viagem').status_code, 200)
        self.assertEqual(self.post('idle').json['current']['kind'], 'idle')

    def test_stable_session_across_restart(self):
        cookie = self.client.get_cookie('cpreta_session').value
        other = create_app(self.root).test_client()
        other.set_cookie('cpreta_session', cookie)
        response = other.post('/atividade/registrar', data={'csrf':self.csrf,'action':'idle'})
        self.assertEqual(response.status_code, 200)

    def test_security_and_shutdown(self):
        runtime = self.app.extensions['desktop_runtime']
        self.assertEqual(self.client.post('/sistema/encerrar').status_code, 403)
        self.assertFalse(runtime.shutdown_requested.is_set())
        response = self.client.post('/sistema/encerrar', data={'csrf':self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(runtime.shutdown_requested.is_set())
        self.assertEqual(self.client.get('/health').json['application'], 'CPreta')

    def test_escape_and_suggestions(self):
        self.post('start', category='trabalho', title='<script>alert(1)</script>', client='Cliente A')
        html = self.client.get('/relatorios').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>alert(1)', html)
        self.assertIn('Cliente A', self.client.get('/atividade/opcoes').json['suggestions']['client'])


class NativeFlowTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    tearDown = WorkflowTests.tearDown
    def test_native_steps_without_showing_window(self):
        import tkinter as tk
        from desktop import ActivityDialog
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        root.font_family = 'Segoe UI'
        store = self.app.extensions['activities']
        dialog = None
        try:
            dialog = ActivityDialog(root, store, Proposal('manual'), lambda *_:None, present=False)
            dialog.begin_new()
            dialog.set_category('trabalho')
            dialog.widgets['title'].insert(0, 'Validar integração')
            dialog.widgets['client'].insert(0, 'Cliente de teste')
            dialog.save_start()
            dialog.close()
            ident = store.current()['activity_id']
            dialog = ActivityDialog(root, store, Proposal('manual'), lambda *_:None, present=False)
            dialog.begin_update(ident)
            dialog.widgets['note'].insert('1.0','Conferi a configuração')
            dialog.remember()
            dialog.results()
            dialog.widgets['attempts'].set('2')
            dialog.widgets['successes'].set('1')
            dialog.widgets['failures'].set('1')
            dialog.widgets['reason'].insert('1.0','Parâmetro incorreto')
            dialog.complete_var.set(True)
            dialog.save_progress()
            self.assertIsNone(store.current())
            data = store.dashboard()
            self.assertEqual(data['attempts'],2)
            self.assertEqual(data['failures'],1)
            self.assertEqual(data['activities'][0]['updates'][0]['note'],'Conferi a configuração')
        finally:
            if dialog and not dialog.closed: dialog.close()
            root.destroy()
