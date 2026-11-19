import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from local_server import LocalSessionGuard


@pytest.fixture
def guarded():
    fake = FastAPI()

    @fake.post('/auth/status')
    async def login():
        return {'authenticated': True}

    @fake.get('/api/accounts')
    async def accounts():
        return []

    @fake.websocket('/ws')
    async def ws(socket):
        await socket.accept()
        await socket.close()

    guard = LocalSessionGuard(fake)
    return guard, TestClient(guard, base_url='http://127.0.0.1:8765')


def test_api_requires_session_and_logout_revokes_it(guarded):
    guard, client = guarded
    assert client.get('/api/accounts').status_code == 401
    response = client.post('/auth/status')
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=Strict' in response.headers['set-cookie']
    assert client.get('/api/accounts').status_code == 200
    old_cookie = client.cookies.get('xianyu_local_session')
    assert client.post('/auth/logout').status_code == 200
    client.cookies.set('xianyu_local_session', old_cookie)
    assert client.get('/api/accounts').status_code == 401


def test_expired_and_forged_sessions_rejected(guarded):
    guard, client = guarded
    client.cookies.set('xianyu_local_session', 'forged')
    assert client.get('/api/accounts').status_code == 401
    guard.sessions['forged'] = time.time() - 1
    assert client.get('/api/accounts').status_code == 401


def test_cross_origin_and_rebinding_rejected(guarded):
    _, client = guarded
    assert client.post('/auth/status', headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.post('/auth/status', headers={'Host': 'example.com:8765'}).status_code == 403


def test_websocket_requires_auth(guarded):
    _, client = guarded
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws'):
            pass


def test_local_browser_channel(monkeypatch):
    from src.scraper import _resolve_browser_channel
    monkeypatch.setenv('LOCAL_BROWSER_CHANNEL', 'chromium')
    assert _resolve_browser_channel() == 'chromium'
