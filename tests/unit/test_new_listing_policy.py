from src.services.new_listing_policy import is_new_listing
from src.keyword_rule_engine import evaluate_keyword_rules
import pytest
from src.services.new_listing_policy import validate_search_payload


def test_api_failure_is_not_empty_success():
    with pytest.raises(RuntimeError, match='FAIL_SYS_USER_VALIDATE'):
        validate_search_payload({'ret': ['FAIL_SYS_USER_VALIDATE::private-data'], 'data': {}})
    with pytest.raises(RuntimeError, match='有效商品列表'):
        validate_search_payload({'ret': ['SUCCESS::ok'], 'data': {}})
    validate_search_payload({'ret': ['SUCCESS::ok'], 'data': {'resultList': []}})


def test_old_unknown_and_new_publications():
    cutoff = 1794031200  # epoch seconds; comparisons use raw millisecond timestamps
    assert not is_new_listing({'发布时间戳': (cutoff - 1) * 1000}, cutoff)
    assert is_new_listing({'发布时间戳': cutoff * 1000}, cutoff)
    assert is_new_listing({'发布时间戳': (cutoff + 1) * 1000}, cutoff)
    assert not is_new_listing({'发布时间': '未知时间'}, cutoff)
    assert is_new_listing({}, None)


def test_publication_fallback_uses_shanghai_timezone():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    cutoff = datetime(2026, 11, 7, 15, 0, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    assert is_new_listing({'发布时间': '2026-11-07 15:00'}, cutoff)
    assert not is_new_listing({'发布时间': '2026-11-07 14:59'}, cutoff)


def test_reported_missed_listing_matches_aph():
    title = '推推均价57的二十周年aph拼团 标价无意义，想拼团请小窗捆序英米耀仏普'
    assert not evaluate_keyword_rules(['aph仏英', '仏英', '弗朗西斯'], title)['is_recommended']
    assert evaluate_keyword_rules(['aph仏英', '仏英', '弗朗西斯', 'aph'], title)['is_recommended']


def test_verification_is_typed_and_does_not_expose_response_secrets():
    from src.services.new_listing_policy import SearchVerificationError
    with pytest.raises(SearchVerificationError) as result:
        validate_search_payload({'ret': ['FAIL_SYS_USER_VALIDATE::secret-url', 'RGV587_ERROR::private'], 'data': {}})
    assert 'secret-url' not in str(result.value)
    assert 'private' not in str(result.value)


def test_stage_validation_reports_first_failed_filter():
    import asyncio
    from src.services.new_listing_policy import validate_search_response, SearchVerificationError
    class Response:
        ok = True
        async def json(self):
            return {'ret': ['FAIL_SYS_USER_VALIDATE::private'], 'data': {}}
    async def run():
        stages = []
        for stage in ['最新发布排序', '价格筛选']:
            stages.append(stage)
            await validate_search_response(Response(), stage)
        return stages
    with pytest.raises(SearchVerificationError, match='最新发布排序'):
        asyncio.run(run())


def test_successful_filter_response_and_http_failure():
    import asyncio
    from src.services.new_listing_policy import validate_search_response, SearchResponseError
    class Response:
        ok = True
        status = 200
        async def json(self):
            return {'ret': ['SUCCESS::ok'], 'data': {'resultList': []}}
    assert asyncio.run(validate_search_response(Response(), '价格筛选'))['data']['resultList'] == []
    response = Response()
    response.ok = False
    response.status = 403
    with pytest.raises(SearchResponseError, match='价格筛选.*403'):
        asyncio.run(validate_search_response(response, '价格筛选'))
