import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
from src.services import firefox_worker as worker,history_detail


def test_worker_detail_auth_validation_busy_and_targeted_cancel(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    (tmp_path/'state').mkdir()
    (tmp_path/'state/private_3.json').write_text(json.dumps({'cookies':[{'name':'unb','value':'fixture'}]}))
    async def scenario():
        started=asyncio.Event();release=asyncio.Event();run_id='a'*32
        class Pages:
            def __init__(self,runtime):pass
            async def check(self,run,item):
                started.set();await release.wait();return {'status':'unknown'}
            async def close(self,run):
                if run==run_id:release.set()
        monkeypatch.setattr(history_detail,'FirefoxHistoryPages',Pages)
        runtime=SimpleNamespace(context=SimpleNamespace(cookies=AsyncMock(return_value=[{'name':'unb','value':'fixture'}])))
        app=worker.create_app('private_3','fixture-token',runtime)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://local') as client:
            payload={'run_id':run_id,'item_id':'123'}
            assert (await client.post('/history/detail',json=payload)).status_code==401
            client.headers['Authorization']='Bearer fixture-token'
            assert (await client.post('/history/detail',json={'run_id':run_id,'item_id':'https://other.test'})).status_code==422
            assert (await client.post('/history/detail',json=[])).status_code==422
            pending=asyncio.create_task(client.post('/history/detail',json=payload))
            await asyncio.wait_for(started.wait(),2)
            assert (await client.post('/run',json={'task':{}})).status_code==409
            assert (await client.post('/history/detail',json=payload)).status_code==409
            assert (await client.post('/shutdown')).status_code==409
            await client.post('/history/cancel',json={'run_id':'b'*32})
            assert not pending.done()
            assert (await client.post('/history/cancel',json={'run_id':run_id})).status_code==200
            assert (await asyncio.wait_for(pending,2)).json()['status']=='unknown'
    asyncio.run(scenario())


def test_worker_cannot_start_browser_or_read_unverified_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    (tmp_path/'state').mkdir()
    (tmp_path/'state/private_3.json').write_text('{"cookies":[{"name":"unb","value":"expected"}]}')
    async def scenario():
        for context in (None,SimpleNamespace(cookies=AsyncMock(return_value=[{'name':'unb','value':'wrong'}]))):
            runtime=SimpleNamespace(context=context)
            app=worker.create_app('private_3','fixture-token',runtime)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://local',headers={'Authorization':'Bearer fixture-token'}) as client:
                assert (await client.post('/history/detail',json={'run_id':'a'*32,'item_id':'123'})).status_code==409
                assert (await client.get('/health')).json()['history_detail_version']==1
    asyncio.run(scenario())
