import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class Store:
    """Local prototype index. Gridded data lives in Zarr, not database blobs."""
    def __init__(self, root: Path, recover_jobs=False):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for name in ('datasets', 'forecasts', 'models', 'incoming'):
            (root / name).mkdir(exist_ok=True)
        self.db = root / 'meteo.sqlite3'
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)')
            conn.execute('CREATE INDEX IF NOT EXISTS kind_created ON records(kind, created)')
        for item in self.list('job') if recover_jobs else []:
            if item['status'] in ('queued', 'running'):
                self.update(item['id'], status='interrupted', message='服务重启导致任务中断，请重新启动训练')
        if not self.list('thresholds'):
            self.add('thresholds', {'precip': 20., 'wind': 17., 'temperature': 35.}, key='thresholds')

    def connect(self):
        return sqlite3.connect(self.db, timeout=30)

    def add(self, kind, payload, key=None):
        item = {**payload, 'id': key or uuid4().hex, 'created_at': now()}
        with self.connect() as conn:
            conn.execute('INSERT INTO records VALUES (?, ?, ?, ?)',
                         (item['id'], kind, item['created_at'], json.dumps(item, ensure_ascii=False, allow_nan=False)))
        return item

    def get(self, key, kind=None):
        with self.connect() as conn:
            row = conn.execute('SELECT kind, payload FROM records WHERE id=?', (key,)).fetchone()
        if not row or (kind and row[0] != kind):
            raise KeyError(key)
        return json.loads(row[1])

    def list(self, kind):
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM records WHERE kind=? ORDER BY created DESC', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, key, **changes):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM records WHERE id=?', (key,)).fetchone()
            if not row:
                raise KeyError(key)
            data = {**json.loads(row[0]), **changes}
            conn.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(data, ensure_ascii=False, allow_nan=False), key))
        return data
