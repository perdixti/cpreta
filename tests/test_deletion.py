import re
import unittest
from unittest.mock import patch
import test_reports


class DeletionTests(unittest.TestCase):
    setUp = test_reports.SavedReportTests.setUp
    tearDown = test_reports.SavedReportTests.tearDown

    def start(self, title='Atividade'):
        return self.app.extensions['activities'].start(dict(category='trabalho', title=title, note='Passo inicial', attempts=2, successes=1, failures=1))

    def confirm(self, url, fingerprint=None):
        if fingerprint is None:
            response = self.client.get(url)
            self.assertEqual(response.status_code,200)
            fingerprint = re.search(r'name="fingerprint" value="([^"]+)"',response.get_data(as_text=True)).group(1)
        return self.client.post(url,data=dict(csrf=self.csrf, confirm='delete',fingerprint=fingerprint))

    def test_delete_current_activity_preserves_other_activity_and_html(self):
        ledger=self.app.extensions['activities']
        first=self.start('Manter')
        second=self.start('Excluir')
        file=self.folder/'snapshot.html'
        file.write_text('<h1>Preservar</h1>',encoding='utf-8')
        url=f'/registros/excluir/activity/{second}'
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(ledger.current()['activity_id'],second)
        self.assertEqual(self.confirm(url).status_code,302)
        self.assertIsNone(ledger.current())
        self.assertEqual(ledger.get_activity(first)['title'],'Manter')
        with ledger.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM segments WHERE activity_id=?',(second,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM updates WHERE activity_id=?',(second,)).fetchone()[0],0)
        self.assertTrue(file.exists())
        self.assertEqual(ledger.dashboard()['attempts'],2)

    def test_update_only_removes_its_attempts_and_preserves_timer(self):
        ledger=self.app.extensions['activities']
        ident=self.start()
        before=ledger.current()
        update=ledger.dashboard()['activities'][0]['updates'][0]['id']
        self.confirm(f'/registros/excluir/update/{update}')
        self.assertEqual(ledger.current(),before)
        self.assertEqual(ledger.dashboard()['attempts'],0)
        self.assertEqual(ledger.get_activity(ident)['title'],'Atividade')

    def test_idle_deletion_preserves_activity(self):
        ledger=self.app.extensions['activities']
        ident=self.start()
        ledger.idle()
        pause=ledger.current()['id']
        self.confirm(f'/registros/excluir/idle/{pause}')
        self.assertIsNone(ledger.current())
        self.assertEqual(ledger.dashboard()['idle'],0)
        self.assertEqual(ledger.get_activity(ident)['title'],'Atividade')

    def test_stale_activity_confirmation_does_not_delete_new_update(self):
        ledger=self.app.extensions['activities']
        ident=self.start()
        fingerprint=ledger.deletion_preview('activity',ident)['fingerprint']
        ledger.continue_activity(ident,dict(note='New update'))
        response=self.confirm(f'/registros/excluir/activity/{ident}',fingerprint)
        self.assertIn('mudou desde',self.client.get(response.location).get_data(as_text=True))
        self.assertEqual(len(ledger.dashboard()['activities'][0]['updates']),2)

    def test_html_deletion_preserves_ledger_and_other_files(self):
        ident=self.start()
        file=self.folder/'report.html'
        file.write_text('<h1>Report</h1>',encoding='utf-8')
        other=self.folder/'other.html'
        other.write_text('Keep',encoding='utf-8')
        url='/relatorios/excluir/report.html'
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertTrue(file.exists())
        self.confirm(url)
        self.assertFalse(file.exists())
        self.assertTrue(other.exists())
        self.assertEqual(self.app.extensions['activities'].get_activity(ident)['id'],ident)

    def test_changed_html_requires_confirmation_again(self):
        file=self.folder/'report.html'
        file.write_text('Before',encoding='utf-8')
        url='/relatorios/excluir/report.html'
        html=self.client.get(url).get_data(as_text=True)
        fingerprint=re.search(r'name="fingerprint" value="([^"]+)"',html).group(1)
        file.write_text('After edit - different size',encoding='utf-8')
        response=self.confirm(url,fingerprint)
        self.assertIn('mudou desde',self.client.get(response.location).get_data(as_text=True))
        self.assertTrue(file.exists())

    def test_csrf_confirmation_type_and_path_are_required(self):
        ident=self.start()
        url=f'/registros/excluir/activity/{ident}'
        self.assertEqual(self.client.post(url).status_code,403)
        self.assertEqual(self.client.post(url,data={'csrf':self.csrf}).status_code,400)
        self.assertEqual(self.client.get('/relatorios/excluir/../config.json').status_code,404)
        file=self.folder/'note.txt'
        file.write_text('Keep',encoding='utf-8')
        self.assertEqual(self.client.get('/relatorios/excluir/note.txt').status_code,415)
        self.assertTrue(file.exists())
        self.assertEqual(self.app.extensions['activities'].get_activity(ident)['id'],ident)

    def test_file_permission_error_is_reported(self):
        file=self.folder/'report.html'
        file.write_text('Keep',encoding='utf-8')
        url='/relatorios/excluir/report.html'
        with patch('pathlib.Path.unlink',side_effect=PermissionError('denied')):
            response=self.confirm(url)
        self.assertTrue(file.exists())
        self.assertIn('Não foi possível excluir',self.client.get(response.location).get_data(as_text=True))
