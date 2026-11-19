import asyncio
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from src.api.dependencies import get_process_service, get_task_service
from src.services import price_survey_store as store
from src.services.price_survey_service import survey_service

router=APIRouter(prefix="/api/price-surveys",tags=["price-surveys"])


class SurveyRequest(BaseModel):
    task_id: int = Field(ge=0)
    keyword: str = Field(min_length=1,max_length=100)
    item_limit: int = Field(default=100,ge=1,le=500,strict=True)

    @field_validator("keyword")
    @classmethod
    def clean_keyword(cls,value):
        value=value.strip()
        if not value:
            raise ValueError("请选择本地历史商品分类")
        return value


class SoldRequest(BaseModel):
    keyword: str = Field(min_length=1,max_length=100)
    item_id: str = Field(min_length=1,max_length=100)
    sold: bool
    sold_price: float | None = Field(default=None,ge=0,allow_inf_nan=False)


@router.get("/state")
async def state():
    return {"settings":store.settings(),"latest":store.get_run()}


@router.put("/settings")
async def update_settings(payload: SurveyRequest):
    store.save_settings(payload.model_dump())
    return store.settings()


@router.post("/runs")
async def start(payload: SurveyRequest, processes=Depends(get_process_service), tasks=Depends(get_task_service)):
    if await tasks.get_task(payload.task_id) is None:
        raise HTTPException(404,"参考任务不存在")
    try:
        return survey_service.start(payload.model_dump(),processes)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc


@router.post("/cancel")
async def cancel():
    await survey_service.cancel()
    return {"ok":True}


@router.get("/items")
async def items(keyword: str="",q: str=Query("",max_length=200),
                status: Literal["","observed","missing","history","sold","available","unavailable","unknown","check_failed"]="",
                page: int=Query(1,ge=1),limit: int=Query(30,ge=1,le=100)):
    await asyncio.to_thread(store.import_history)
    return await asyncio.to_thread(store.query_items,keyword,q,status,page,limit)


@router.patch("/items/sold")
async def sold(payload: SoldRequest):
    if not store.mark_sold(**payload.model_dump()):
        raise HTTPException(404,"本地商品不存在")
    return {"ok":True}


@router.get("/history/export")
async def export_history(keyword: str="",q: str=Query("",max_length=200),
                         status: Literal["","observed","missing","history","sold","available","unavailable","unknown","check_failed"]=""):
    data = await asyncio.to_thread(store.query_items,keyword,q,status,1,1_000_000)
    data["note"] = "sold_source区分手动确认与详情明确证据；sold_price仅为手动填写的成交价，price/checked_price均为挂牌价；无法访问不等于已卖出"
    return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type="application/json",
                    headers={"Content-Disposition":'attachment; filename="local-price-history.json"'})


@router.get("/runs/{run_id}/export")
async def export(run_id: str):
    try:
        data=store.export_run(run_id)
    except ValueError as exc:
        raise HTTPException(404,str(exc)) from exc
    return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type="application/json",
                    headers={"Content-Disposition":'attachment; filename="price-survey.json"'})
