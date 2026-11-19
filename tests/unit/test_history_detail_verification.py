import asyncio
import json
from types import SimpleNamespace
import pytest
from playwright.async_api import async_playwright
from src.services import price_survey_store as store
from src.services.history_detail import classify_payload,inspect_detail,canonical_url,SOLD_MARKER
from src.services.price_survey_service import PriceSurveyService


@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'db.sqlite3'))
    store.initialize();folder=tmp_path/'jsonl';folder.mkdir()
    def seed(count=3):
        items=[{'商品信息':{'商品ID':str(n),'商品标题':'谷子'+str(n),'当前售价':'57',
                '商品链接':'https://www.goofish.com/item?id='+str(n)}} for n in range(1,count+1)]
        (folder/'tag_full_data.jsonl').write_text('\n'.join(json.dumps(i,ensure_ascii=False) for i in items),encoding='utf-8')
        store.import_history()
    return seed


def payload(state='卖掉了',item_id='1'):
    return {'ret':['SUCCESS::ok'],'data':{'trackParams':{'itemId':item_id},
        'itemDO':{'itemStatusStr':state,'soldPrice':'57'}}}


@pytest.mark.parametrize('value,expected',[
    (payload(),'sold'),(payload('已下架'),'unavailable'),(payload('在线'),'available'),
    (payload('卖掉了','2'),None),(payload('1'),None),
    ({'ret':['FAIL_BIZ_ITEM_DEL_NOT_FOUND::gone']},'unavailable'),
    ({'ret':['FAIL_SYS_USER_VALIDATE::challenge']},'failed'),
    ({'ret':['FAIL_SYS_SESSION_EXPIRED::login']},'failed'),
    ({'ret':['SUCCESS'],'data':[]},None),({'ret':None},None),
])
def test_explicit_current_item_status_only(value,expected):
    result=classify_payload(value,'1')
    assert (result['status'] if result else None)==expected


def test_json_and_jsonl_import_and_stable_target_queue(local,tmp_path):
    local(3)
    (tmp_path/'jsonl/other.json').write_text(json.dumps([{'item_id':'9','title':'其他谷子','price':90}]),encoding='utf-8')
    store.import_history()
    assert store.query_items(keyword='other')['items'][0]['title']=='其他谷子'
    run=store.create_detail_run(0,'tag',2)
    assert [r['item_id'] for r in store.detail_targets(run['id'])]==['1','2']
    local(4)
    assert len(store.detail_targets(run['id']))==2
    assert run['target_count']==2 and run['item_limit']==2
    with pytest.raises(ValueError):store.create_detail_run(0,'nothing',10)


def test_sale_evidence_manual_confirmation_and_prices_preserved(local):
    local()
    store.mark_sold('tag','1',True,42)
    run=store.create_detail_run(0,'tag',3);store.progress(run['id'])
    assert store.record_detail(run['id'],'1',{'status':'available','source':'detail_api','evidence':'itemDO.itemStatusStr=在线','asking_price':60})
    assert store.record_detail(run['id'],'2',{'status':'sold','source':'detail_api','evidence':'itemDO.itemStatusStr=卖掉了','asking_price':57})
    assert store.record_detail(run['id'],'3',{'status':'unavailable','reason':'404'})
    store.complete_details(run['id'])
    records={i['item_id']:i for i in store.query_items()['items']}
    assert records['1']['sold_source']=='manual' and records['1']['sold_price']==42
    assert records['1']['price']==57 and records['1']['checked_price']==60
    assert records['2']['status']=='sold' and records['2']['sold_source']=='detail_auto'
    assert records['2']['sold_price'] is None and records['2']['last_checked']
    assert records['3']['status']=='unavailable' and not records['3']['sold']
    export=store.export_run(run['id']);assert len(export['items'])==3
    assert export['items'][1]['history_price']==57 and export['items'][1]['checked_price']==57
    store.mark_sold('tag','2',False)
    assert store.query_items(keyword='tag',q='2',status='unknown')['total']==1


def test_cancel_keeps_verified_sales_and_rejects_late_results(local):
    local();run=store.create_detail_run(0,'tag',3);store.progress(run['id'])
    with pytest.raises(ValueError):store.record_detail(run['id'],'1',{'status':'sold'})
    store.record_detail(run['id'],'1',{'status':'sold','source':'detail_page','evidence':'详情状态控件：卖掉了'})
    store.cancel_details(run['id'])
    assert not store.record_detail(run['id'],'2',{'status':'sold','source':'detail_api','evidence':'late'})
    assert store.get_run(run['id'])['state']=='cancelled'
    records={i['item_id']:i for i in store.query_items()['items']}
    assert records['1']['sold'] and records['2']['last_checked'] is None
    assert len(store.export_run(run['id'])['items'])==3


@pytest.mark.parametrize('stop_on_second',[False,True])
def test_real_runner_yields_to_monitor_and_stops_on_failure(local,monkeypatch,stop_on_second):
    import src.services.price_survey_runner as runner
    from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
    local();order=[];ps=SimpleNamespace(browser_operation_lock=asyncio.Lock(),processes={})
    async def task(self,task_id):return SimpleNamespace(task_name='reference',account_state_file='state/private_3.json')
    monkeypatch.setattr(SqliteTaskRepository,'find_by_id',task)
    monkeypatch.setattr(runner,'select_account',lambda t:('private_3','firefox'))
    class Browser:
        def __init__(self,*args):pass
        async def open(self):assert ps.browser_operation_lock.locked()
        async def check(self,run_id,item_id):
            assert ps.browser_operation_lock.locked();order.append('item'+item_id)
            if item_id=='1':
                async def monitor():
                    async with ps.browser_operation_lock:order.append('scheduled_monitor')
                asyncio.create_task(monitor())
            if item_id=='2' and stop_on_second:return {'status':'failed','reason':'timeout','stop':True}
            return {'status':'available','source':'detail_api','evidence':'在线'}
        async def close(self,run_id):order.append('closed')
    monkeypatch.setattr(runner,'HistoryBrowser',Browser)
    async def scenario():
        service=PriceSurveyService();run=service.start({'task_id':0,'keyword':'tag','item_limit':3},ps)
        await service.runner
        record=store.get_run(run['id'])
        assert record['state']==('failed' if stop_on_second else 'completed')
        assert order.index('scheduled_monitor')<order.index('item2')
        assert not ps.browser_operation_lock.locked()
        if stop_on_second:assert store.detail_targets(run['id'])[2]['state']=='pending'
    asyncio.run(scenario())


def test_live_dom_fixture_never_uses_descriptions_recommendations_or_404_as_sale():
    async def scenario():
        async with async_playwright() as pw:
            browser=await pw.firefox.launch(headless=True)
            try:
                cases=[
                    ('api_sold','sold',200,payload()),('api_offline','unavailable',200,payload('已下架')),
                    ('wrong_item','unknown',200,payload('卖掉了','999')),
                    ('description','unknown',200,None),('hidden','unknown',200,None),
                    ('watermark','sold',200,None),('404','unavailable',404,None),
                    ('challenge','failed',200,payload()),('network','failed',200,None),
                ]
                for name,expected,http,data in cases:
                    context=await browser.new_context();page=await context.new_page()
                    html='<div>商品描述：卖掉了</div><section>推荐商品 已售出</section>'
                    if name=='hidden':html+='<div class="item-status--fixture" style="display:none">卖掉了</div>'
                    if name in ('watermark','404'):
                        html+='<div class="item-status--fixture" style="width:50px;height:50px"><img width="50" height="50" src="https://img.alicdn.com/'+SOLD_MARKER+'.png"></div>'
                    if name=='challenge':html+='<div class="baxia-dialog-mask" style="width:100px;height:100px">verify</div>'
                    if data is not None or name=='network':
                        html+='<script>fetch("/h5/mtop.taobao.idle.pc.detail/1.0/?data="+encodeURIComponent(JSON.stringify({itemId:"1"}))).catch(()=>{});</script>'
                    async def route(r):
                        if '/h5/mtop.taobao.idle.pc.detail/' in r.request.url:
                            if name=='network':await r.abort()
                            else:await r.fulfill(status=200,content_type='application/json',body=json.dumps(data))
                        elif r.request.resource_type=='document':await r.fulfill(status=http,content_type='text/html',body=html)
                        else:await r.abort()
                    await context.route('**/*',route)
                    value=await inspect_detail(page,'1',settle_seconds=.35)
                    assert value['status']==expected,(name,value)
                    assert not value.get('sold_price')
                    await context.close()
            finally:await browser.close()
    asyncio.run(scenario())


def test_invalid_ids_cannot_navigate_to_external_urls():
    for value in ('../private1','https://evil.test','1&redirect=evil','', '１２３'):
        with pytest.raises(ValueError):canonical_url(value)


def test_cancel_inflight_releases_browser_and_preserves_only_finished_evidence(local,monkeypatch):
    import src.services.price_survey_runner as runner
    from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
    local();ps=SimpleNamespace(browser_operation_lock=asyncio.Lock(),processes={})
    async def task(self,task_id):return SimpleNamespace(task_name='reference',account_state_file=None)
    monkeypatch.setattr(SqliteTaskRepository,'find_by_id',task)
    monkeypatch.setattr(runner,'select_account',lambda t:('private_3','firefox'))
    async def scenario():
        second=asyncio.Event();closed=asyncio.Event()
        class Browser:
            def __init__(self,*args):pass
            async def open(self):pass
            async def check(self,run_id,item_id):
                if item_id=='1':return {'status':'sold','source':'detail_api','evidence':'itemDO.itemStatusStr=卖掉了'}
                second.set();await asyncio.Event().wait()
            async def close(self,run_id):closed.set()
        monkeypatch.setattr(runner,'HistoryBrowser',Browser)
        service=PriceSurveyService();run=service.start({'task_id':0,'keyword':'tag','item_limit':3},ps)
        await asyncio.wait_for(second.wait(),2);await service.cancel()
        assert closed.is_set() and not ps.browser_operation_lock.locked()
        assert store.get_run(run['id'])['state']=='cancelled'
        checks=store.detail_targets(run['id'])
        assert [c['state'] for c in checks]==['sold','pending','pending']
    asyncio.run(scenario())


def test_legacy_schema_migration_preserves_manual_history(local):
    from src.infrastructure.persistence.sqlite_connection import sqlite_connection
    local(1)
    store.mark_sold('tag','1',True,42)
    legacy=store.create_run(0,'old',2)
    with sqlite_connection() as db:
        before=tuple(db.execute('SELECT keyword,item_id,title,price,sold,sold_price,sold_at,observation,raw_json FROM price_survey_items').fetchone())
        for col in ('history_source','sold_source','last_checked','check_status','check_source','check_evidence','checked_price'):
            db.execute('ALTER TABLE price_survey_items DROP COLUMN '+col)
        for col in ('kind','target_count'):db.execute('ALTER TABLE price_survey_runs DROP COLUMN '+col)
        db.commit()
    store.initialize();store.initialize()
    with sqlite_connection() as db:
        after=tuple(db.execute('SELECT keyword,item_id,title,price,sold,sold_price,sold_at,observation,raw_json FROM price_survey_items').fetchone())
    assert before==after
    assert store.query_items()['items'][0]['sold_source']=='manual'
    assert store.get_run(legacy['id'])['kind']=='list_sample'


def test_web_api_does_not_start_without_click_and_cancel_keeps_history(local,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routes import price_surveys as api
    from src.api.dependencies import get_process_service,get_task_service
    local(3);service=PriceSurveyService();entered=[]
    async def execute(run,ps):entered.append(run['id']);await asyncio.Event().wait()
    monkeypatch.setattr(service,'_execute',execute);monkeypatch.setattr(api,'survey_service',service)
    class Tasks:
        async def get_task(self,task_id):return object()
    app=FastAPI();app.include_router(api.router)
    app.dependency_overrides[get_task_service]=lambda:Tasks()
    app.dependency_overrides[get_process_service]=lambda:SimpleNamespace()
    with TestClient(app) as client:
        assert client.get('/api/price-surveys/state').json()['latest'] is None
        assert client.get('/api/price-surveys/items').json()['total']==3
        assert not entered and service.runner is None
        body={'task_id':0,'keyword':'tag','item_limit':2}
        response=client.post('/api/price-surveys/runs',json=body);assert response.status_code==200
        run=response.json();assert run['kind']=='history_detail' and run['target_count']==2
        assert client.post('/api/price-surveys/runs',json=body).status_code==409
        assert client.post('/api/price-surveys/cancel').status_code==200
        assert client.get('/api/price-surveys/state').json()['latest']['state']=='cancelled'
        assert len(client.get('/api/price-surveys/runs/'+run['id']+'/export').json()['items'])==2
        assert client.get('/api/price-surveys/items',params={'status':'sold'}).json()['total']==0


def test_price_samples_remain_searchable_but_do_not_enter_json_verification_queue(local):
    from src.services.price_history_service import record_market_snapshots
    local(1)
    record_market_snapshots(keyword='sample_only',task_name='old',items=[{'商品ID':'99','商品标题':'旧采样',
        '当前售价':'10','商品链接':'https://www.goofish.com/item?id=99'}],run_id='old')
    store.import_history()
    assert store.query_items(keyword='sample_only')['total']==1
    assert store.query_items()['history_counts']=={'tag':1}
    with pytest.raises(ValueError):store.create_detail_run(0,'sample_only',100)
