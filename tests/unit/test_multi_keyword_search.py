import json
from types import SimpleNamespace
from urllib.parse import urlencode
from src.services.multi_keyword_search import search_keywords, item_identity, link_identity, matches_keyword


def test_all_queries_preserve_phrase_order_and_remove_duplicates():
    task={'keyword':'aph仏英','keyword_rules':['aph仏英','仏英','弗朗西斯 亚瑟','亚瑟 弗朗西斯','弗朗西斯',' 仏英 ', '']}
    assert search_keywords(task)==['aph仏英','仏英','弗朗西斯 亚瑟','亚瑟 弗朗西斯','弗朗西斯']
    task['_price_survey']={'id':'legacy'}
    assert search_keywords(task)==['aph仏英']


def test_identity_survives_query_parameter_order_and_tracking_changes():
    old=link_identity('https://www.goofish.com/item?spm=old&id=123&foo=x')
    assert old==item_identity({'商品ID':123,'商品链接':'https://www.goofish.com/item?id=123'})
    assert old==item_identity({'商品链接':'https://www.goofish.com/item?foo=y&id=123'})
    assert item_identity({'商品ID':'456'})!=old


def test_late_response_from_previous_query_does_not_match():
    def response(keyword):
        return SimpleNamespace(url='https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/',request=SimpleNamespace(method='POST',post_data=urlencode({'data':json.dumps({'keyword':keyword})})))
    assert matches_keyword(response('弗朗西斯 亚瑟'),'弗朗西斯 亚瑟')
    assert not matches_keyword(response('aph仏英'),'弗朗西斯 亚瑟')
    bad=response('a');bad.request.post_data='invalid'
    assert not matches_keyword(bad,'a')


def test_single_keyword_tasks_still_work():
    assert search_keywords({'keyword':'one'})==['one']


def test_real_list_submission_loop_deduplicates_across_query_pages():
    import ast, asyncio
    from pathlib import Path
    from datetime import datetime
    source=ast.parse(Path('src/scraper.py').read_text(encoding='utf-8'))
    loop=next(n for n in ast.walk(source) if isinstance(n,ast.For) and ast.unparse(n.target)=='(i, item_data)')
    boundary=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.If) and ast.unparse(n.test)=='list_only')
    loop.body=loop.body[:boundary+1]
    outer=ast.For(target=ast.Name(id='basic_items',ctx=ast.Store()),iter=ast.Name(id='pages',ctx=ast.Load()),body=[loop],orelse=[])
    fn=ast.AsyncFunctionDef(name='run',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[ast.Assign(targets=[ast.Name(id='processed_item_count',ctx=ast.Store())],value=ast.Constant(0)),outer],decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    submitted=[]
    def item(id,link):return {'商品ID':id,'商品链接':link,'商品标题':'fixture'}
    env=dict(pages=[[item('1','https://www.goofish.com/item?id=1'),item('2','https://www.goofish.com/item?id=2')],[item('2','https://www.goofish.com/item?tracking=x&id=2'),item('3','https://www.goofish.com/item?id=3')]],
        processed_ids={'1'},processed_links=set(),listing_cutoff=None,is_new_listing=lambda *a:True,
        log_time=lambda *a:None,debug_limit=0,get_link_unique_key=lambda link:link,
        item_identity=item_identity,list_only=True,datetime=datetime,keyword='archive',search_keyword='query',task_config={},
        build_market_reference=lambda **k:{},historical_snapshots=[],analysis_dispatcher=SimpleNamespace(submit=submitted.append),
        ItemAnalysisJob=SimpleNamespace(from_search_list=lambda **k:k),decision_mode='keyword',ai_prompt_text='',keyword_rules=[],total_items_on_page=2)
    exec(compile(module,'real_scraper_loop','exec'),env)
    asyncio.run(env['run']())
    assert [j['final_record']['商品信息']['商品ID'] for j in submitted]==['2','3']
    assert all(j['keyword']=='archive' for j in submitted)
