import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.services import price_survey_store as store
from src.services.price_survey_service import PriceSurveyService
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DATABASE_FILE",str(tmp_path/"survey.sqlite3"))
    store.initialize()


def item(n,price=10):
    return {"商品ID":str(n),"商品标题":f"aph tag {n}","当前售价":str(price),"商品链接":f"https://www.goofish.com/item?id={n}"}


def completed(items,keyword="tag"):
    run=store.create_run(0,keyword,100)
    store.finish(run["id"],items,"private1",1,"sample_limit")
    return run


def test_missing_is_not_sold_and_last_asking_price_is_retained():
    completed([item(1,57),item(2,89)])
    run=completed([item(2,80)])
    records={i["item_id"]:i for i in store.query_items()["items"]}
    assert records["1"]["status"]=="missing"
    assert records["1"]["price"]==57 and records["1"]["sold_price"] is None
    assert records["2"]["price"]==80
    assert store.get_run(run["id"])["summary"]["missing_count"]==1
    assert store.mark_sold("tag","1",True,50)
    record=store.query_items(status="sold")["items"][0]
    assert record["sold_price"]==50 and record["price"]==57
    completed([item(1,60)])
    assert store.query_items(status="sold")["items"][0]["sold_price"]==50
    assert store.mark_sold("tag","1",False)
    assert store.query_items(q="1")["items"][0]["status"]=="observed"


def test_capture_caps_at_100_deduplicates_and_exports_immutable_sample():
    run=store.create_run(0,"tag",100)
    capture=store.SurveyCapture(run["id"],100)
    for page in range(1,5):
        done=capture.add_page([item(n,n+1) for n in range((page-1)*30,page*30)],page,"private1")
        assert done is (page==4)
    capture.complete("private1")
    export=store.export_run(run["id"])
    assert len(export["items"])==100
    assert export["survey"]["summary"]["median"]==50.5
    assert export["survey"]["pages"]==4
    completed([item(1,999)])
    assert store.export_run(run["id"])["items"][1]["当前售价"]=="2"


def test_failed_cancelled_or_restarted_run_never_changes_item_states():
    completed([item(1),item(2)])
    before=store.query_items()["items"]
    run=store.create_run(0,"tag",100)
    capture=store.SurveyCapture(run["id"],100)
    capture.add_page([item(1,20)],1,"private1")
    store.fail(run["id"],"verification")
    with pytest.raises(ValueError):
        capture.complete("private1")
    assert store.query_items()["items"]==before
    pending=store.create_run(0,"tag",100)
    store.interrupt_stale_runs()
    assert store.get_run(pending["id"])["state"]=="failed"
    assert store.query_items()["items"]==before


def test_keyword_scoping_literal_search_and_sold_without_price():
    completed([item(1,57)],"tag")
    completed([item(2,89)],"other")
    completed([],"other")
    assert store.query_items(keyword="tag")["items"][0]["status"]=="observed"
    assert store.query_items(q="tag 1")["total"]==1
    assert store.query_items(q="%")["total"]==0
    assert store.query_items(q="' OR 1=1")["total"]==0
    store.mark_sold("tag","1",True)
    assert store.query_items(status="sold")["items"][0]["sold_price"] is None


def test_import_existing_history_without_overwriting_survey_states():
    from src.services.price_history_service import record_market_snapshots
    record_market_snapshots(keyword="tag",task_name="demo",items=[item(1,12)],run_id="old")
    store.import_history()
    assert store.query_items()["items"][0]["price"]==12
    completed([])
    store.import_history()
    assert store.query_items()["items"][0]["status"]=="missing"


def test_manual_survey_waits_for_browser_and_rejects_duplicate(monkeypatch):
    Path('jsonl').mkdir(exist_ok=True)
    Path('jsonl/tag_full_data.jsonl').write_text(json.dumps({'商品信息':item(1)}),encoding='utf-8')
    async def scenario():
        service=PriceSurveyService()
        processes=SimpleNamespace(browser_operation_lock=asyncio.Lock(),processes={})
        entered=asyncio.Event()
        release=asyncio.Event()
        async def execute(run,ps):
            async with ps.browser_operation_lock:
                entered.set()
                await release.wait()
                store.progress(run['id'])
                store.record_detail(run['id'],'1',{'status':'available','source':'detail_api','evidence':'在线'})
                store.complete_details(run['id'])
        monkeypatch.setattr(service,"_execute",execute)
        await processes.browser_operation_lock.acquire()
        run=service.start(dict(task_id=0,keyword="tag",item_limit=100),processes)
        await asyncio.sleep(0)
        assert not entered.is_set()
        with pytest.raises(ValueError):
            service.start(dict(task_id=0,keyword="tag",item_limit=100),processes)
        processes.browser_operation_lock.release()
        await entered.wait()
        assert processes.browser_operation_lock.locked()
        release.set()
        await service.runner
        assert not processes.browser_operation_lock.locked()
        assert store.get_run(run["id"])["state"]=="completed"
    asyncio.run(scenario())


def test_cancel_queued_survey_releases_reservation(monkeypatch):
    Path('jsonl').mkdir(exist_ok=True)
    Path('jsonl/tag_full_data.jsonl').write_text(json.dumps({'商品信息':item(1)}),encoding='utf-8')
    async def scenario():
        service=PriceSurveyService()
        processes=SimpleNamespace(browser_operation_lock=asyncio.Lock(),processes={})
        async def waiting(run,ps):
            async with ps.browser_operation_lock:await asyncio.Event().wait()
        monkeypatch.setattr(service,'_execute',waiting)
        await processes.browser_operation_lock.acquire()
        run=service.start(dict(task_id=0,keyword="tag",item_limit=100),processes)
        await asyncio.sleep(0)
        await service.cancel()
        assert store.get_run(run["id"])["state"]=="cancelled"
        processes.browser_operation_lock.release()
    asyncio.run(scenario())


def test_list_analysis_saves_and_notifies_without_opening_seller_or_images():
    from src.services.item_analysis_dispatcher import ItemAnalysisDispatcher,ItemAnalysisJob
    async def scenario():
        seller,images,ai=AsyncMock(),AsyncMock(),AsyncMock()
        notify,save=AsyncMock(),AsyncMock(return_value=True)
        dispatcher=ItemAnalysisDispatcher(concurrency=1,skip_ai_analysis=False,seller_loader=seller,
            image_downloader=images,ai_analyzer=ai,notifier=notify,saver=save)
        dispatcher.submit(ItemAnalysisJob.from_search_list(keyword="tag",task_name="test",
            decision_mode="keyword",prompt_text="",keyword_rules=("aph",),
            final_record={"商品信息":item(1),"卖家信息":{}}))
        await dispatcher.join()
        seller.assert_not_called();images.assert_not_called();ai.assert_not_called()
        save.assert_awaited_once();notify.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("payload",[
    {"task_id":0,"keyword":"tag","item_limit":0},
    {"task_id":0,"keyword":"tag","item_limit":501},
    {"task_id":0,"keyword":"tag","item_limit":2.5},
    {"task_id":0,"keyword":"   ","item_limit":100},
])
def test_invalid_survey_request_never_saves(payload):
    from src.api.routes.price_surveys import router
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    assert client.put("/api/price-surveys/settings",json=payload).status_code==422
    assert store.settings()["item_limit"]==100


def test_local_api_search_manual_sold_and_export():
    from src.api.routes.price_surveys import router
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    completed([item(7,57)])
    assert client.get("/api/price-surveys/items",params={"q":"7"}).json()["total"]==1
    assert client.patch("/api/price-surveys/items/sold",json={"keyword":"tag","item_id":"7","sold":True,"sold_price":50}).status_code==200
    exported=client.get("/api/price-surveys/history/export",params={"status":"sold"}).json()
    assert exported["items"][0]["sold_price"]==50
    assert exported["items"][0]["price"]==57
    assert client.put("/api/price-surveys/settings",json={"task_id":0,"keyword":"tag","item_limit":120}).status_code==200
    assert client.get("/api/price-surveys/state").json()["settings"]["item_limit"]==120
