"""Read-only local account overview. Never connects to any account/browser."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[2]


def _json_file(path, default):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def _rows(path, query):
    if not path.exists():
        return []
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query)]


def account_nodes(*, root=None, state_dir='state', now=None):
    root = Path(root) if root is not None else ROOT
    now = time.time() if now is None else now
    directory = Path(state_dir)
    if not directory.is_absolute():
        directory = root / directory
    mapping = _json_file(root / 'data/account-browsers.json', {})
    pending = _json_file(root / 'data/account-browser-pending.json', {})
    pool_path = root / 'data/account-failover.sqlite3'
    active = {r['task']: r['account'] for r in _rows(pool_path, 'SELECT task,account FROM active')}
    blocked = {str(Path(r['account']).resolve()): r['cooldown_until'] for r in
               _rows(pool_path, 'SELECT account,cooldown_until FROM blocked')}
    tasks = _rows(root / 'data/app.sqlite3', 'SELECT task_name,enabled,is_running,account_state_file FROM tasks')
    selected = {}
    running = {}
    for task in tasks:
        if not task['enabled']:
            continue
        # The runtime override wins over the task's preferred account.
        path = active.get(task['task_name']) or task['account_state_file']
        if not path:
            continue
        path = Path(path)
        key = str((path if path.is_absolute() else root / path).resolve())
        selected.setdefault(key, []).append(task['task_name'])
        if task['is_running']:
            running.setdefault(key, []).append(task['task_name'])
    files = {p.stem: p for p in directory.glob('*.json') if p.is_file()}
    nodes = []
    for name in sorted(set(files) | set(mapping)):
        path = files.get(name)
        browser = mapping.get(name, 'chrome')
        until = blocked.get(str(path.resolve())) if path else None
        cooling = bool(until and until > now)
        status = 'available'
        if path is None:
            status = 'missing'
        elif browser not in ('chrome', 'edge', 'firefox'):
            status = 'pending'
        else:
            try:
                raw = path.read_bytes()
                state = json.loads(raw.decode('utf-8-sig'))
                if not any(c.get('name') == 'cookie2' and c.get('value') for c in state.get('cookies', [])):
                    status = 'invalid'
                elif pending.get(name) == hashlib.sha256(raw).hexdigest():
                    status = 'pending'
            except (ValueError, OSError, AttributeError, TypeError):
                status = 'invalid'
        if cooling:
            status = 'cooling'
        key = str(path.resolve()) if path else ''
        used_by = selected.get(key, [])
        can_select = status == 'available'
        if can_select and used_by:
            status = 'active'
        nodes.append({'name': name, 'browser': browser, 'status': status,
                      'selected_by': used_by, 'running_by': running.get(key, []) if can_select else [],
                      'cooldown_until': until if cooling else None,
                      'remaining_seconds': max(0, int(until - now)) if cooling else 0})
    return {'updated_at': now, 'nodes': nodes}
