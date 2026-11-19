import asyncio
import hashlib
import json
import sqlite3

import httpx
from fastapi import FastAPI
import pytest

from src.services.account_nodes import account_nodes


def fixture(root):
    (root / 'state').mkdir()
    (root / 'data').mkdir()
    mapping = {'private1': 'chrome', 'private_2': 'edge', 'private_3': 'firefox'}
    (root / 'data/account-browsers.json').write_text(json.dumps(mapping))
    for name in mapping:
        (root / 'state' / (name + '.json')).write_text(json.dumps({'cookies': [{'name': 'cookie2', 'value': 'SECRET-DO-NOT-RETURN'}]}))
    with sqlite3.connect(root / 'data/account-failover.sqlite3') as db:
        db.execute('CREATE TABLE active (task TEXT PRIMARY KEY, account TEXT)')
        db.execute('CREATE TABLE blocked (account TEXT PRIMARY KEY, cooldown_until REAL)')
        db.execute('INSERT INTO active VALUES (?,?)', ('task', str(root / 'state/private1.json')))
        db.execute('INSERT INTO blocked VALUES (?,?)', (str(root / 'state/private_2.json'), 2000))
    with sqlite3.connect(root / 'data/app.sqlite3') as db:
        db.execute('CREATE TABLE tasks (task_name TEXT,enabled INTEGER,is_running INTEGER,account_state_file TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?,?,?)', ('task', 1, 1, 'state/private_3.json'))


def test_actual_selection_wins_and_no_secret_or_write(tmp_path):
    fixture(tmp_path)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    result = account_nodes(root=tmp_path, now=1000)
    nodes = {n['name']: n for n in result['nodes']}
    assert nodes['private1']['status'] == 'active'
    assert nodes['private1']['running_by'] == ['task']
    assert nodes['private_2']['status'] == 'cooling'
    assert nodes['private_2']['remaining_seconds'] == 1000
    assert nodes['private_3']['status'] == 'available'
    assert 'SECRET' not in json.dumps(result)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}


def test_cooldown_expiry_changes_candidate_without_switching(tmp_path):
    fixture(tmp_path)
    nodes = {n['name']: n for n in account_nodes(root=tmp_path, now=2000)['nodes']}
    assert nodes['private_2']['status'] == 'available'
    assert nodes['private1']['status'] == 'active'


def test_invalid_missing_and_pending_accounts(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'state/private1.json').write_text('broken-json')
    (tmp_path / 'state/private_2.json').unlink()
    state = (tmp_path / 'state/private_3.json').read_bytes()
    (tmp_path / 'data/account-browser-pending.json').write_text(json.dumps({'private_3': hashlib.sha256(state).hexdigest()}))
    nodes = {n['name']: n for n in account_nodes(root=tmp_path, now=2000)['nodes']}
    assert nodes['private1']['status'] == 'invalid'
    assert nodes['private_2']['status'] == 'missing'
    assert nodes['private_3']['status'] == 'pending'


def test_disabled_tasks_do_not_show_active_node(tmp_path):
    fixture(tmp_path)
    with sqlite3.connect(tmp_path / 'data/app.sqlite3') as db:
        db.execute('UPDATE tasks SET enabled=0')
    assert all(n['status'] != 'active' for n in account_nodes(root=tmp_path, now=1000)['nodes'])


def test_unreadable_pool_does_not_claim_accounts_are_available(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'data/account-failover.sqlite3').write_bytes(b'corrupt')
    with pytest.raises(sqlite3.DatabaseError):
        account_nodes(root=tmp_path)


def test_nodes_route_precedes_account_name_and_fails_closed(monkeypatch):
    from src.api.routes import accounts
    async def run():
        app = FastAPI()
        app.include_router(accounts.router)
        expected = {'updated_at': 1, 'nodes': []}
        monkeypatch.setattr(accounts, 'account_nodes', lambda **kwargs: expected)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local') as client:
            assert (await client.get('/api/accounts/nodes')).json() == expected
            def broken(**kwargs):
                raise sqlite3.DatabaseError('internal-file-path-must-not-leak')
            monkeypatch.setattr(accounts, 'account_nodes', broken)
            response = await client.get('/api/accounts/nodes')
            assert response.status_code == 503
            assert 'internal-file-path' not in response.text
    asyncio.run(run())
