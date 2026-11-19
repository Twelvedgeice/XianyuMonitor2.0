import asyncio
import sys
from types import SimpleNamespace
import httpx
import pytest
from src.services import firefox_worker as worker


@pytest.mark.parametrize('account,flag,available', [('private_3','1',True), ('private_3','0',False), ('private1','1',False)])
def test_probe_is_opt_in_one_shot_and_exclusive(tmp_path, monkeypatch, account, flag, available):
    monkeypatch.setenv('FIREFOX_SORT_PROBE_ONCE',flag)
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    (tmp_path/'state').mkdir()
    (tmp_path/'state'/f'{account}.json').write_text('{"cookies":[]}',encoding='utf-8')
    async def run():
        started,finish=asyncio.Event(),asyncio.Event()
        async def probe(runtime,snapshot):
            started.set()
            await finish.wait()
            return {'ok':True}
        monkeypatch.setitem(sys.modules,'src.services.firefox_sort_probe',SimpleNamespace(probe_sort_once=probe))
        app=worker.create_app(account,'test-only',SimpleNamespace())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://local') as client:
            assert (await client.post('/diagnostics/sort-once')).status_code==401
            client.headers['Authorization']='Bearer test-only'
            if not available:
                assert (await client.post('/diagnostics/sort-once')).status_code==404
                return
            pending=asyncio.create_task(client.post('/diagnostics/sort-once'))
            await asyncio.wait_for(started.wait(),2)
            assert (await client.post('/run',json={'task':{}})).status_code==409
            assert (await client.post('/shutdown')).status_code==409
            finish.set()
            assert (await pending).json()=={'ok':True}
            assert (await client.post('/diagnostics/sort-once')).status_code==409
    asyncio.run(run())
