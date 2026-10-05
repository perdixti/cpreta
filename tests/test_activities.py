from datetime import datetime
from pathlib import Path
import shutil
import unittest
import uuid
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activities import ActivityStore
from attention import AttentionPolicy
from signals import Sample


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ('run-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).timestamp()
        self.store = ActivityStore(self.root / 'activities.sqlite3', clock=lambda: self.now)

    def tearDown(self):
        assert self.root.parent == Path(__file__).resolve().parent
        shutil.rmtree(self.root)

    def start(self, title='Atender demanda X'):
        return self.store.start(dict(category='trabalho', title=title, client='Cliente A', project='Integração'))

    def test_active_idle_resume_no_overlap(self):
        ident = self.start()
        self.now += 600
        self.store.idle()
        self.now += 300
        self.store.continue_activity(ident, dict(note='Revisei a configuração', attempts=3, successes=2, failures=1, reason='Parâmetro incorreto', result='Integração concluída'))
        self.now += 120
        data = self.store.dashboard()
        self.assertEqual(data['active'], 720)
        self.assertEqual(data['idle'], 300)
        self.assertEqual(data['attempts'], 3)
        self.assertEqual(data['activities'][0]['duration'], 720)
        self.assertEqual(data['activities'][0]['updates'][0]['reason'], 'Parâmetro incorreto')
        self.assertEqual(data['current']['activity_id'], ident)

    def test_same_activity_update_does_not_restart_timer(self):
        ident = self.start()
        beginning = self.store.current()['start']
        self.now += 100
        self.store.continue_activity(ident, dict(note='Mesmo foco'))
        self.assertEqual(self.store.current()['start'], beginning)

    def test_gap_requires_confirmation(self):
        ident = self.start()
        beginning = self.now
        self.now += 1200
        self.assertEqual(self.store.dashboard()['idle'], 0)
        self.store.confirm_gap(beginning + 300, beginning + 900, True)
        data = self.store.dashboard()
        self.assertEqual(data['active'], 600)
        self.assertEqual(data['idle'], 600)
        self.assertEqual(data['current']['activity_id'], ident)

    def test_invalid_update_rolls_back_transition(self):
        ident = self.start()
        self.now += 100
        self.store.idle()
        with self.assertRaises(ValueError):
            self.store.continue_activity(ident, dict(attempts=1, successes=2))
        self.assertEqual(self.store.current()['kind'], 'idle')

    def test_crash_recovery_does_not_count_closed_hours(self):
        self.start()
        beginning = self.now
        self.now += 7200
        self.store.recover(beginning + 120)
        self.assertIsNone(self.store.current())
        self.assertEqual(self.store.dashboard()['active'], 120)

    def test_across_midnight_clips_daily_totals(self):
        self.now = datetime.now().replace(hour=23, minute=50, second=0, microsecond=0).timestamp()
        self.start()
        self.now += 1200
        self.assertEqual(self.store.dashboard()['active'], 600)
        self.assertEqual(self.store.dashboard('week')['active'], 1200)
        self.assertEqual(sum(day['active'] for day in self.store.dashboard('week')['daily']), 1200)

    def test_export_escapes_spreadsheet_formulas(self):
        self.start('=UNSAFE()')
        self.now += 60
        self.assertIn("'=UNSAFE()", self.store.export_csv('today'))


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.policy = AttentionPolicy()
        self.config = dict(monitor_enabled=True, observation_mode='app', idle_minutes=5, change_seconds=60, cooldown_minutes=15)
        self.current = dict(kind='active', start=0)

    def observe(self, at, app='editor', idle=0, **kwargs):
        return self.policy.observe(Sample(at, idle, app, **kwargs), self.config, self.current)

    def test_brief_switch_is_ignored_sustained_change_proposes(self):
        self.assertIsNone(self.observe(1000))
        self.assertIsNone(self.observe(1002, 'browser'))
        self.assertIsNone(self.observe(1010))
        self.assertIsNone(self.observe(1012, 'browser'))
        self.assertIsNone(self.observe(1050, 'browser'))
        self.assertIsNone(self.observe(1073, 'browser'))
        self.assertEqual(self.observe(1075, 'browser', idle=2).reason, 'context_change')

    def test_no_periodic_prompt_without_change(self):
        for at in range(1000, 5000, 2):
            self.assertIsNone(self.observe(at))

    def test_idle_return_waits_until_person_returns(self):
        self.observe(1000)
        for at in range(1002, 1400, 2):
            self.assertIsNone(self.observe(at, idle=at - 1000))
        proposal = self.observe(1400, idle=0)
        self.assertEqual(proposal.reason, 'idle_return')
        self.assertEqual(proposal.start, 1000)
        self.assertEqual(proposal.end, 1400)

    def test_fullscreen_and_snooze_suppress(self):
        self.observe(1000)
        self.observe(1002, 'browser')
        self.assertIsNone(self.observe(1070, 'browser', fullscreen=True))
        self.policy.acknowledge(1070, 900)
        self.assertIsNone(self.observe(1072, 'editor'))
        self.assertIsNone(self.observe(1150, 'editor'))

    def test_cooldown_prevents_app_hopping_prompts(self):
        self.observe(1000)
        self.observe(1002, 'browser')
        self.observe(1070, 'browser')
        self.policy.acknowledge(1070)
        self.observe(1072, 'editor')
        self.assertIsNone(self.observe(1140, 'editor'))

    def test_idle_only_does_not_propose_app_changes(self):
        self.config['observation_mode'] = 'idle'
        self.observe(1000)
        self.observe(1002, 'browser')
        self.assertIsNone(self.observe(1070, 'browser'))

    def test_disabled_never_proposes(self):
        self.config['monitor_enabled'] = False
        self.assertIsNone(self.observe(1000, idle=700))
        self.assertIsNone(self.observe(1700, 'browser'))

    def test_untracked_waits_for_interaction_pause(self):
        self.current = None
        self.assertIsNone(self.observe(1000))
        self.assertIsNone(self.observe(1032))
        self.assertEqual(self.observe(1034, idle=2).reason, 'untracked')

    def test_long_activity_prompt_is_contextual(self):
        self.config['checkin_minutes'] = 1
        self.observe(1000)
        self.assertIsNone(self.observe(1062, idle=0))
        self.assertEqual(self.observe(1064, idle=2).reason, 'long_activity')
        self.policy.acknowledge(1064, 1800)
        self.assertIsNone(self.observe(1080, idle=3))

    def test_hourly_cap_and_unknown_idle(self):
        self.config['max_prompts_hour'] = 1
        self.policy.shown(1000)
        self.current = None
        self.assertIsNone(self.observe(1002))
        for at in range(1004, 2200, 2):
            self.assertIsNone(self.observe(at, idle=2))
        self.policy.prompt_times.clear()
        self.assertIsNone(self.observe(2200, idle=None))
