"""Local activity ledger. Only confirmed answers become activity records."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import csv
import io
import sqlite3
import time
import hashlib
import json

CATEGORIES = {'trabalho': 'Trabalho', 'estudo': 'Estudo', 'pessoal': 'Pessoal', 'outro': 'Outra atividade'}


class ActivityStore:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
                    client TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY, activity_id INTEGER REFERENCES activities(id),
                    kind TEXT NOT NULL, start REAL NOT NULL, end REAL,
                    CHECK(kind IN ('active', 'idle')), CHECK(end IS NULL OR end >= start));
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_segment ON segments((1)) WHERE end IS NULL;
                CREATE TABLE IF NOT EXISTS updates (
                    id INTEGER PRIMARY KEY, activity_id INTEGER REFERENCES activities(id),
                    note TEXT NOT NULL, attempts INTEGER NOT NULL, successes INTEGER NOT NULL,
                    failures INTEGER NOT NULL, reason TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                # Serialize transitions even when web and desktop save together.
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    @staticmethod
    def current_row(db):
        row = db.execute('SELECT s.*, a.title, a.category, a.client, a.project FROM segments s LEFT JOIN activities a ON a.id=s.activity_id WHERE s.end IS NULL').fetchone()
        return dict(row) if row else None

    def current(self):
        with self.connection() as db:
            return self.current_row(db)

    @staticmethod
    def close_current(db, now):
        db.execute('UPDATE segments SET end=MAX(start, ?) WHERE end IS NULL', (now,))

    @staticmethod
    def details(payload):
        cleaned = {}
        for field in ('note', 'reason', 'result'):
            cleaned[field] = str(payload.get(field, '')).strip()
            if len(cleaned[field]) > 4000:
                raise ValueError('Use até 4.000 caracteres por campo.')
        for field in ('attempts', 'successes', 'failures'):
            try:
                cleaned[field] = int(payload.get(field, 0) or 0)
            except (ValueError, TypeError):
                raise ValueError('As tentativas precisam ser números inteiros.')
            if not 0 <= cleaned[field] <= 10000:
                raise ValueError('Informe uma quantidade entre 0 e 10.000.')
        if cleaned['successes'] + cleaned['failures'] > cleaned['attempts']:
            raise ValueError('Acertos e erros não podem superar o total de tentativas.')
        return cleaned

    def add_update(self, db, activity_id, payload, now):
        value = self.details(payload)
        if any(value.values()):
            db.execute('INSERT INTO updates(activity_id,note,attempts,successes,failures,reason,result,created) VALUES(?,?,?,?,?,?,?,?)',
                       (activity_id, value['note'], value['attempts'], value['successes'], value['failures'], value['reason'], value['result'], now))

    def start(self, payload):
        category = payload.get('category', '')
        title = str(payload.get('title', '')).strip()
        client = str(payload.get('client', '')).strip() if category == 'trabalho' else ''
        project = str(payload.get('project', '')).strip() if category == 'trabalho' else ''
        if category not in CATEGORIES or not title or len(title) > 180:
            raise ValueError('Escolha uma categoria e informe uma atividade de até 180 caracteres.')
        if len(client) > 180 or len(project) > 180:
            raise ValueError('Cliente e projeto devem ter até 180 caracteres.')
        self.details(payload)
        now = self.clock()
        with self.connection() as db:
            self.close_current(db, now)
            ident = db.execute('INSERT INTO activities(category,title,client,project,created) VALUES(?,?,?,?,?)', (category, title, client, project, now)).lastrowid
            db.execute("INSERT INTO segments(activity_id,kind,start) VALUES(?,'active',?)", (ident, now))
            self.add_update(db, ident, payload, now)
        return ident

    def continue_activity(self, activity_id, payload):
        now = self.clock()
        with self.connection() as db:
            if not db.execute('SELECT id FROM activities WHERE id=?', (activity_id,)).fetchone():
                raise ValueError('Escolha uma atividade existente ou comece uma nova.')
            current = self.current_row(db)
            if not current or current['kind'] != 'active' or current['activity_id'] != activity_id:
                self.close_current(db, now)
                db.execute("INSERT INTO segments(activity_id,kind,start) VALUES(?,'active',?)", (activity_id, now))
            self.add_update(db, activity_id, payload, now)

    def idle(self):
        now = self.clock()
        with self.connection() as db:
            current = self.current_row(db)
            if current and current['kind'] == 'idle':
                return
            self.close_current(db, now)
            db.execute("INSERT INTO segments(kind,start) VALUES('idle',?)", (now,))

    def confirm_gap(self, start, end, resume):
        now = self.clock()
        if not 0 <= start <= end <= now + 1:
            raise ValueError('Intervalo de pausa inválido.')
        with self.connection() as db:
            current = self.current_row(db)
            if not current or current['kind'] != 'active' or start < current['start']:
                raise ValueError('A atividade mudou desde a sugestão. Registre seu estado atual.')
            self.close_current(db, start)
            db.execute("INSERT INTO segments(kind,start,end) VALUES('idle',?,?)", (start, end))
            if resume:
                db.execute("INSERT INTO segments(activity_id,kind,start) VALUES(?,'active',?)", (current['activity_id'], end))

    def finish(self):
        with self.connection() as db:
            self.close_current(db, self.clock())

    def complete(self, activity_id, payload):
        now = self.clock()
        with self.connection() as db:
            current = self.current_row(db)
            if not current or current['kind'] != 'active' or current['activity_id'] != activity_id:
                raise ValueError('Esta atividade não está mais em andamento. Atualize a página.')
            self.add_update(db, activity_id, payload, now)
            self.close_current(db, now)

    def get_activity(self, activity_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM activities WHERE id=?', (activity_id,)).fetchone()
            if not row:
                raise ValueError('Atividade não encontrada.')
            return dict(row)

    @staticmethod
    def deletion_snapshot(db, kind, ident):
        tables = {'activity': 'activities', 'update': 'updates', 'idle': 'segments'}
        if kind not in tables:
            raise ValueError('Tipo de registro inválido.')
        row = db.execute(f'SELECT * FROM {tables[kind]} WHERE id=?', (ident,)).fetchone()
        if not row or (kind == 'idle' and row['kind'] != 'idle'):
            raise ValueError('Registro não encontrado. Atualize a página.')
        snapshot = {'record': dict(row)}
        if kind == 'activity':
            for table in ('segments', 'updates'):
                snapshot[table] = [dict(item) for item in db.execute(
                    f'SELECT * FROM {table} WHERE activity_id=? ORDER BY id', (ident,))]
        snapshot['fingerprint'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return snapshot

    def deletion_preview(self, kind, ident):
        with self.connection() as db:
            return self.deletion_snapshot(db, kind, ident)

    def delete_record(self, kind, ident, fingerprint):
        with self.connection() as db:
            snapshot = self.deletion_snapshot(db, kind, ident)
            if fingerprint != snapshot['fingerprint']:
                raise ValueError('O registro mudou desde a confirmação. Abra a exclusão novamente.')
            if kind == 'activity':
                db.execute('DELETE FROM updates WHERE activity_id=?', (ident,))
                db.execute('DELETE FROM segments WHERE activity_id=?', (ident,))
                db.execute('DELETE FROM activities WHERE id=?', (ident,))
            elif kind == 'update':
                db.execute('DELETE FROM updates WHERE id=?', (ident,))
            else:
                db.execute("DELETE FROM segments WHERE id=? AND kind='idle'", (ident,))

    def suggestions(self):
        with self.connection() as db:
            return {key: [row[0] for row in db.execute(f"SELECT DISTINCT {key} FROM activities WHERE {key} != '' ORDER BY {key} LIMIT 100")] for key in ('client', 'project')}

    def recover(self, last_seen):
        # Do not bill the hours while the application was closed or crashed.
        with self.connection() as db:
            current = self.current_row(db)
            if current:
                self.close_current(db, max(current['start'], min(self.clock(), last_seen or current['start'])))

    def recent(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT a.* FROM activities a LEFT JOIN segments s ON s.activity_id=a.id GROUP BY a.id ORDER BY MAX(s.start) DESC, a.id DESC LIMIT 30')]

    def dashboard(self, period='today'):
        now = self.clock()
        today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=6 if period == 'week' else 0)
        start_ts = start.timestamp()
        with self.connection() as db:
            rows = [dict(row) for row in db.execute('SELECT s.*,a.category,a.title,a.client,a.project FROM segments s LEFT JOIN activities a ON a.id=s.activity_id WHERE COALESCE(s.end,?)>=? AND s.start<=? ORDER BY s.start DESC', (now, start_ts, now))]
            updates = [dict(row) for row in db.execute('SELECT u.*, a.title FROM updates u JOIN activities a ON a.id=u.activity_id WHERE u.created>=? AND u.created<=? ORDER BY u.created DESC', (start_ts, now))]
            current = self.current_row(db)
        totals = {key: 0 for key in CATEGORIES}
        totals['idle'] = 0
        days = { (start + timedelta(days=i)).strftime('%d/%m'): {'active': 0, 'idle': 0} for i in range(7 if period == 'week' else 1) }
        for row in rows:
            left, right = max(row['start'], start_ts), min(row['end'] if row['end'] is not None else now, now)
            row['duration'] = max(0, right - left)
            key = 'idle' if row['kind'] == 'idle' else row['category']
            totals[key] += row['duration']
            cursor = left
            while cursor < right:
                date = datetime.fromtimestamp(cursor)
                next_day = (date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
                edge = min(right, next_day)
                day = date.strftime('%d/%m')
                if day in days:
                    days[day][row['kind']] += edge - cursor
                cursor = edge
        active = sum(value for key, value in totals.items() if key != 'idle')
        total = active + totals['idle']
        categories = [dict(key=key, label=CATEGORIES.get(key, 'Ocioso'), seconds=value, percent=round(value / total * 100, 1) if total else 0) for key, value in totals.items()]
        max_day = max((sum(day.values()) for day in days.values()), default=0)
        daily = [dict(label=label, active=day['active'], idle=day['idle'], active_pct=day['active']/max_day*100 if max_day else 0, idle_pct=day['idle']/max_day*100 if max_day else 0) for label, day in days.items()]
        grouped = {}
        for row in rows:
            if row['activity_id']:
                item = grouped.setdefault(row['activity_id'], dict(id=row['activity_id'], title=row['title'], category=row['category'], client=row['client'], project=row['project'], duration=0, updates=[]))
                item['duration'] += row['duration']
        for update in updates:
            if update['activity_id'] in grouped:
                grouped[update['activity_id']]['updates'].append(update)
        if current:
            current['elapsed'] = max(0, now - current['start'])
        return dict(current=current, active=active, idle=totals['idle'], total=total, categories=categories, daily=daily, segments=rows, updates=updates, period=period,
                    activities=list(grouped.values()), attempts=sum(x['attempts'] for x in updates), successes=sum(x['successes'] for x in updates), failures=sum(x['failures'] for x in updates))

    def export_csv(self, period):
        data = self.dashboard(period)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Tipo', 'Categoria', 'Atividade', 'Cliente', 'Projeto', 'Início', 'Fim', 'Segundos'])
        def safe(value):
            text = str(value or '')
            return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text
        for row in data['segments']:
            writer.writerow([row['kind'], row['category'] or 'ocioso', safe(row['title']), safe(row['client']), safe(row['project']), datetime.fromtimestamp(row['start']).isoformat(timespec='seconds'), datetime.fromtimestamp(row['end']).isoformat(timespec='seconds') if row['end'] is not None else 'Em andamento', round(row['duration'])])
        return '\ufeff' + output.getvalue()
