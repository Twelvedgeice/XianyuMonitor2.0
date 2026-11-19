import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode
from src.services.firefox_sort_evidence import request_summary,payload_summary,ref
from src.parsers import _parse_search_results_json


def test_request_summary_is_allowlisted():
    data={'keyword':'aph仏英','sortField':'create','sortValue':'desc','pageNumber':1,'rowsPerPage':30,
          'fromFilter':True,'token':'SECRET','userPositionJson':'PRIVATE'}
    result=request_summary(SimpleNamespace(post_data=urlencode({'data':json.dumps(data)})))
    assert result=={'keyword_matches':True,'sortField':'create','sortValue':'desc','pageNumber':1,'rowsPerPage':30,'fromFilter':True}
    assert request_summary(SimpleNamespace(post_data='not-json'))=={'parse_failed':True}


def test_evidence_and_real_parser_keep_response_order_and_timestamp():
    def item(identifier,time,label):
        return {'data':{'item':{'main':{'exContent':{'itemId':identifier,'title':'PRIVATE TITLE','picUrl':'https://example.test/SECRET',
            'fishTags':{'r2':{'tagList':[{'data':{'textContent':label}}]}}},
            'clickParam':{'args':{'publishTime':str(time),'token':'SECRET'}}}}}}
    payload={'ret':['SUCCESS::ok'],'data':{'resultList':[item('a',1700000000000,'1天内上新'),item('b',1700000001000,'2小时前发布')]}}
    evidence=payload_summary(payload)
    parsed=asyncio.run(_parse_search_results_json(payload,'test'))
    assert [row['item_ref'] for row in evidence['rows']]==[ref(row['商品ID']) for row in parsed]
    assert [row['parser_publishTime'] for row in evidence['rows']]==[row['发布时间戳'] for row in parsed]
    assert evidence['rows'][0]['display_time_labels']==['1天内上新']
    assert evidence['inversions']==[{'positions':[1,2],'later_by_seconds':1}]
    assert 'SECRET' not in json.dumps(evidence)
    assert 'PRIVATE' not in json.dumps(evidence)
