"""Manual history detail verification; no keyword search or account rotation."""
import asyncio
from src.services import price_survey_store as store
from src.services.history_browser import HistoryBrowser,select_account


async def execute(run_id,access):
    from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
    run=store.get_run(run_id)
    if not run or run['kind']!='history_detail':raise ValueError('仅支持手动历史详情核验')
    task=await SqliteTaskRepository().find_by_id(run['task_id'])
    if task is None:raise ValueError('参考任务已删除')
    browser=None
    try:
        async with access():
            if store.get_run(run_id)['state'] not in ('queued','running'):return
            account,kind=select_account(task)
            browser=HistoryBrowser(account,kind)
            await browser.open()
            store.progress(run_id,state='running',account=account)
        for target in store.detail_targets(run_id):
            if store.get_run(run_id)['state'] not in ('queued','running'):return
            if target['state']!='pending':continue
            async with access():
                if store.get_run(run_id)['state'] not in ('queued','running'):return
                try:value=await browser.check(run_id,target['item_id'])
                except Exception:
                    value={'status':'failed','source':'detail_page','reason':'浏览器连接或账号不可用，已停止','stop':True}
                if not store.record_detail(run_id,target['item_id'],value):return
            if value.get('stop'):
                store.fail(run_id,value.get('reason') or '核验遇到限制，已停止；未核验商品不变')
                return
            # Queued scheduled checks get the lock before the next manual item.
            await asyncio.sleep(.05)
        store.complete_details(run_id)
    finally:
        if browser is not None:await asyncio.shield(browser.close(run_id))


if __name__=='__main__':
    raise SystemExit('请从网页手动启动历史售出核验，以使用浏览器操作锁。')
