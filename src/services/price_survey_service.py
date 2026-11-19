"""Explicitly manual verification, yielding browser access between items."""
import asyncio
from contextlib import asynccontextmanager
from src.services import price_survey_store as store


class PriceSurveyService:
    def __init__(self):self.runner=None;self.run_id=None

    def start(self,payload,process_service):
        if self.runner is not None and not self.runner.done():
            raise ValueError('已有核验正在执行或等待，请勿重复启动')
        store.import_history()
        run=store.create_detail_run(**payload)
        store.save_settings(payload)
        self.run_id=run['id']
        self.runner=asyncio.create_task(self._run(run,process_service))
        return run

    async def _run(self,run,process_service):
        try:await self._execute(run,process_service)
        except asyncio.CancelledError:
            store.cancel_details(run['id'])
            raise
        except Exception as exc:
            store.fail(run['id'],'核验已停止（'+type(exc).__name__+'）；已完成证据保留，未核验商品不变')

    async def _execute(self,run,process_service):
        from src.services.price_survey_runner import execute
        @asynccontextmanager
        async def access():
            store.detail_phase(run['id'],'等待浏览器空闲 / 当前监测结束')
            async with process_service.browser_operation_lock:
                active=[p for p in process_service.processes.values() if p.returncode is None]
                if active:await asyncio.gather(*(p.wait() for p in active))
                store.detail_phase(run['id'],'正在核验历史商品详情')
                yield
        await execute(run['id'],access)

    async def cancel(self):
        if self.run_id:store.cancel_details(self.run_id)
        if self.runner is not None and not self.runner.done():
            self.runner.cancel()
            try:await self.runner
            except asyncio.CancelledError:pass


survey_service=PriceSurveyService()
