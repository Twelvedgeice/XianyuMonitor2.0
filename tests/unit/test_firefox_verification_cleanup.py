import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.services import firefox_worker as worker


class Page:
    """Only supported public listener API; no remove_all_listeners shortcut."""
    def __init__(self):
        self.closed = False
        self.unrelated = lambda response: None
        self.listeners = [self.unrelated]
        self.bring_to_front = AsyncMock()
        self.goto = AsyncMock()

    def on(self, event, callback):
        assert event == 'response'
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        assert event == 'response'
        self.listeners.remove(callback)

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True

    def locator(self, selector):
        return SimpleNamespace(is_visible=AsyncMock(return_value=False))


@pytest.mark.parametrize('scenario', ['cancel_open', 'cancel_closed', 'restart', 'save'])
def test_verification_cleanup(tmp_path, monkeypatch, scenario):
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    (tmp_path / 'state').mkdir()
    (tmp_path / 'state/private_3.json').write_text('{"cookies":[],"origins":[]}', encoding='utf-8')
    first, second = Page(), Page()
    state = {'cookies': [{'name': 'cookie2', 'value': 'fake-test-only'}], 'origins': []}
    context = SimpleNamespace(new_page=AsyncMock(side_effect=[first, second]), storage_state=AsyncMock(return_value=state))
    runtime = SimpleNamespace(context=context, get_context=AsyncMock(return_value=context),
                              save_live_state=AsyncMock(), mark_seeded=lambda state: None)
    async def run():
        app = worker.create_app('private_3', 'test-only', runtime)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local',
                                     headers={'Authorization': 'Bearer test-only'}) as client:
            assert (await client.post('/verify/start')).status_code == 200
            observer = first.listeners[-1]
            response = SimpleNamespace(url='https://example.test/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/',
                request=SimpleNamespace(method='POST'), ok=True,
                json=AsyncMock(return_value={'ret':['SUCCESS::ok'], 'data':{'resultList':[{}]}}))
            if scenario == 'cancel_closed':
                await first.close()
            if scenario.startswith('cancel'):
                assert (await client.post('/verify/cancel')).json() == {'ok': True}
                assert first.listeners == [first.unrelated]
                assert first.closed == (scenario == 'cancel_closed')
                # Repeated cleanup and stale callbacks must not re-enable saving.
                await observer(response)
                assert (await client.post('/verify/save')).json()['ok'] is False
                assert (await client.post('/verify/cancel')).status_code == 200
                runtime.save_live_state.assert_not_awaited()
            elif scenario == 'restart':
                assert (await client.post('/verify/start')).status_code == 200
                assert first.closed
                assert first.listeners == [first.unrelated]
                await observer(response)
                assert (await client.post('/verify/save')).json()['ok'] is False
                assert (await client.post('/verify/cancel')).status_code == 200
                assert second.listeners == [second.unrelated]
            else:
                await observer(response)
                assert (await client.post('/verify/save')).json() == {'ok': True, 'items': 1}
                assert first.listeners == [first.unrelated]
                assert first.closed is False
                assert json.loads((tmp_path / 'state/private_3.json').read_text()) == state
                assert (await client.post('/verify/save')).json()['ok'] is False
    asyncio.run(run())
