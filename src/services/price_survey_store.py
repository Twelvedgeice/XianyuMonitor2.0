"""Local market samples. Absence from a bounded sample is never proof of sale."""
import json
import math
import statistics
import uuid
import re
from pathlib import Path
from datetime import datetime

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.price_history_service import parse_price_value


def now():
    return datetime.now().isoformat(timespec="seconds")


def initialize():
    bootstrap_sqlite_storage()
    with sqlite_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS price_survey_runs (
            id TEXT PRIMARY KEY, keyword TEXT NOT NULL, task_id INTEGER NOT NULL,
            item_limit INTEGER NOT NULL, state TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, actual_count INTEGER NOT NULL DEFAULT 0,
            pages INTEGER NOT NULL DEFAULT 0, account TEXT, error TEXT, summary_json TEXT
        );
        CREATE TABLE IF NOT EXISTS price_survey_items (
            keyword TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
            link TEXT, price REAL, price_display TEXT, first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL, last_run TEXT, observation TEXT NOT NULL DEFAULT 'history',
            sold INTEGER NOT NULL DEFAULT 0, sold_price REAL, sold_at TEXT, raw_json TEXT NOT NULL,
            PRIMARY KEY(keyword,item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_survey_last_seen ON price_survey_items(last_seen DESC);
        """)
        additions = {
            'price_survey_runs': {'kind': "TEXT NOT NULL DEFAULT 'list_sample'", 'target_count': 'INTEGER NOT NULL DEFAULT 0'},
            'price_survey_items': {'history_source':'TEXT', 'sold_source':'TEXT', 'last_checked':'TEXT',
                'check_status':'TEXT', 'check_source':'TEXT', 'check_evidence':'TEXT', 'checked_price':'REAL'},
        }
        for table, columns in additions.items():
            existing = {row[1] for row in db.execute('PRAGMA table_info('+table+')')}
            for column, definition in columns.items():
                if column not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        db.execute("UPDATE price_survey_items SET sold_source='manual' WHERE sold=1 AND sold_source IS NULL")
        db.execute('''CREATE TABLE IF NOT EXISTS price_survey_checks (
            run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, keyword TEXT NOT NULL, item_id TEXT NOT NULL,
            title TEXT, link TEXT, history_price REAL, history_source TEXT,
            state TEXT NOT NULL DEFAULT 'pending', checked_at TEXT, source TEXT, evidence TEXT,
            reason TEXT, checked_price REAL, PRIMARY KEY(run_id,item_id))''')
        db.commit()


def settings():
    with sqlite_connection() as db:
        row = db.execute("SELECT value FROM app_metadata WHERE key='price_survey_settings'").fetchone()
        return json.loads(row[0]) if row else {"task_id": None, "keyword": "", "item_limit": 100}


def save_settings(value):
    with sqlite_connection() as db:
        db.execute("INSERT OR REPLACE INTO app_metadata VALUES ('price_survey_settings',?)",
                   (json.dumps(value, ensure_ascii=False),))
        db.commit()


def import_history():
    """Import existing JSON-backed records/snapshots locally; never visit sellers."""
    with sqlite_connection() as db:
        rows = db.execute("""
            SELECT keyword,item_id,title,link,price,price_display,crawl_time AS seen,raw_json,'result_file' AS origin
            FROM result_items WHERE item_id IS NOT NULL AND item_id != ''
            UNION ALL
            SELECT keyword,item_id,title,link,price,price_display,snapshot_time AS seen,NULL,'price_snapshot' AS origin
            FROM price_snapshots ORDER BY seen DESC
        """).fetchall()
        for row in rows:
            if row["item_id"] == "未知ID":
                continue
            db.execute("""INSERT OR IGNORE INTO price_survey_items
                (keyword,item_id,title,link,price,price_display,first_seen,last_seen,raw_json)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (row["keyword"], row["item_id"], row["title"] or "", row["link"], row["price"],
                 row["price_display"], row["seen"], row["seen"], row["raw_json"] or "{}"))
            if row['origin']=='result_file':
                db.execute("UPDATE price_survey_items SET history_source=COALESCE(history_source,'local_json_result_database') WHERE keyword=? AND item_id=?",
                           (row['keyword'],row['item_id']))
        from src.services.price_survey_history import local_history_records
        for keyword, item, source, stamp in local_history_records(Path('jsonl')):
            item_id = item['商品ID']
            price = parse_price_value(item.get('当前售价'))
            if price is not None and not math.isfinite(price):price=None
            db.execute('''INSERT OR IGNORE INTO price_survey_items
                (keyword,item_id,title,link,price,price_display,first_seen,last_seen,raw_json,history_source)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (keyword,item_id,item.get('商品标题',''),item['商品链接'],
                price,str(item.get('当前售价','')),stamp,stamp,json.dumps(item,ensure_ascii=False),source))
            db.execute('UPDATE price_survey_items SET history_source=? WHERE keyword=? AND item_id=?',
                       (source,keyword,item_id))
        db.commit()


def create_run(task_id, keyword, item_limit):
    run_id = uuid.uuid4().hex
    with sqlite_connection() as db:
        db.execute("""INSERT INTO price_survey_runs(id,keyword,task_id,item_limit,state,started_at)
            VALUES (?,?,?,?,'queued',?)""", (run_id, keyword, task_id, item_limit, now()))
        db.commit()
    return get_run(run_id)


def get_run(run_id=None):
    with sqlite_connection() as db:
        row = db.execute("SELECT * FROM price_survey_runs WHERE id=?", (run_id,)).fetchone() if run_id else db.execute(
            "SELECT * FROM price_survey_runs ORDER BY started_at DESC,rowid DESC LIMIT 1").fetchone()
    if row is None:
        return None
    result = dict(row)
    result["summary"] = json.loads(result.pop("summary_json") or "{}")
    return result


def progress(run_id, *, state="running", count=0, pages=0, account=None):
    with sqlite_connection() as db:
        db.execute("""UPDATE price_survey_runs SET state=?,actual_count=?,pages=?,account=COALESCE(?,account)
            WHERE id=? AND state IN ('queued','running')""", (state,count,pages,account,run_id))
        db.commit()


def fail(run_id, message):
    with sqlite_connection() as db:
        db.execute("""UPDATE price_survey_runs SET state='failed',error=?,finished_at=?
            WHERE id=? AND state IN ('queued','running')""", (message,now(),run_id))
        db.commit()


def interrupt_stale_runs():
    with sqlite_connection() as db:
        db.execute("""UPDATE price_survey_runs SET state='failed',error='服务已重启；已完成核验保留，未核验商品不变',
            finished_at=? WHERE state IN ('queued','running')""", (now(),))
        db.commit()


def summarize(items):
    prices = [parse_price_value(item.get("当前售价")) for item in items]
    prices = [p for p in prices if p is not None and math.isfinite(p) and p > 0]
    return {"priced_count":len(prices), "min":min(prices) if prices else None,
            "max":max(prices) if prices else None,
            "median":round(statistics.median(prices),2) if prices else None,
            "mean":round(statistics.mean(prices),2) if prices else None}


def finish(run_id, items, account, pages, coverage):
    """Publish a completed sample atomically. Failed/partial jobs never infer absence."""
    run = get_run(run_id)
    if not run or run["state"] not in ("queued","running"):
        raise ValueError("调查记录不存在或已结束")
    unique = {}
    for item in items:
        item_id = str(item.get("商品ID") or "")
        if item_id and item_id != "未知ID":
            unique.setdefault(item_id, item)
    if len(unique) > run["item_limit"]:
        raise ValueError("调查样本超过设置数量")
    stamp = now()
    summary = dict(summarize(unique.values()), coverage=coverage)
    with sqlite_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT state FROM price_survey_runs WHERE id=?",(run_id,)).fetchone()[0] not in ("queued","running"):
            raise ValueError("调查已取消，不能发布结果")
        db.execute("UPDATE price_survey_items SET observation='missing' WHERE keyword=?", (run["keyword"],))
        for item_id, item in unique.items():
            price = parse_price_value(item.get("当前售价"))
            price = price if price is not None and math.isfinite(price) else None
            db.execute("""INSERT INTO price_survey_items
                (keyword,item_id,title,link,price,price_display,first_seen,last_seen,last_run,observation,raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,'observed',?)
                ON CONFLICT(keyword,item_id) DO UPDATE SET
                title=excluded.title,link=excluded.link,price=excluded.price,price_display=excluded.price_display,
                last_seen=excluded.last_seen,last_run=excluded.last_run,observation='observed',raw_json=excluded.raw_json""",
                (run["keyword"],item_id,item.get("商品标题",""),item.get("商品链接",""),price,
                 str(item.get("当前售价","")),stamp,stamp,run_id,json.dumps(item,ensure_ascii=False)))
        summary["missing_count"] = db.execute(
            "SELECT COUNT(*) FROM price_survey_items WHERE keyword=? AND observation='missing' AND sold=0",
            (run["keyword"],)).fetchone()[0]
        db.execute("""UPDATE price_survey_runs SET state='completed',finished_at=?,actual_count=?,pages=?,
            account=?,summary_json=? WHERE id=?""",
            (stamp,len(unique),pages,account,json.dumps(summary,ensure_ascii=False),run_id))
        # Store immutable sample JSON in the same transaction as item states.
        db.execute("INSERT OR REPLACE INTO app_metadata VALUES (?,?)",
                   ("price_survey_sample:"+run_id,json.dumps(list(unique.values()),ensure_ascii=False)))
        db.commit()


def export_run(run_id):
    run = get_run(run_id)
    if run and run.get('kind') == 'history_detail':
        if run['state'] in ('queued','running'):
            raise ValueError('核验尚在进行，请完成或停止后导出')
        with sqlite_connection() as db:
            rows=db.execute('SELECT * FROM price_survey_checks WHERE run_id=? ORDER BY ordinal',(run_id,)).fetchall()
        return {'survey':run,'items':[dict(row) for row in rows],
            'price_note':'history_price是历史挂牌价，checked_price是本次可见挂牌价，均不代表成交价；仅明确售出证据自动标记已卖出'}
    if not run or run["state"] != "completed":
        raise ValueError("只能导出已完成的调查")
    with sqlite_connection() as db:
        row = db.execute("SELECT value FROM app_metadata WHERE key=?",("price_survey_sample:"+run_id,)).fetchone()
    return {"survey":run,"items":json.loads(row[0]) if row else [],
            "price_note":"搜索列表标价，不代表实际成交价；样本未出现不代表已售出"}


def query_items(keyword="", q="", status="", page=1, limit=30):
    conditions, args = [], []
    if keyword:
        conditions.append("keyword=?"); args.append(keyword)
    # instr treats user %, _ and quotes literally, not as wildcard SQL.
    for term in q.strip().split():
        conditions.append("(instr(lower(title),lower(?))>0 OR instr(item_id,?)>0)")
        args.extend([term,term])
    if status == "sold":
        conditions.append("sold=1")
    elif status:
        if status in ('available','unavailable','unknown','check_failed'):
            if status=='unknown':conditions.append("check_status IN ('unknown','sold') AND sold=0")
            else:
                conditions.append("check_status=? AND sold=0"); args.append('failed' if status=='check_failed' else status)
        else:
            conditions.append("observation=? AND sold=0"); args.append(status)
    where = " AND ".join(conditions) or "1=1"
    with sqlite_connection() as db:
        total = db.execute("SELECT COUNT(*) FROM price_survey_items WHERE "+where,args).fetchone()[0]
        rows = db.execute("SELECT * FROM price_survey_items WHERE "+where+" ORDER BY last_seen DESC,item_id LIMIT ? OFFSET ?",
                          [*args,limit,(page-1)*limit]).fetchall()
        keywords = [row[0] for row in db.execute("SELECT DISTINCT keyword FROM price_survey_items ORDER BY keyword")]
        history_counts = dict(db.execute('SELECT keyword,COUNT(*) FROM price_survey_items WHERE history_source IS NOT NULL GROUP BY keyword ORDER BY keyword').fetchall())
    items = []
    for row in rows:
        item = dict(row)
        item.pop("raw_json")
        item["status"] = "sold" if item["sold"] else ('check_failed' if item['check_status']=='failed' else ('unknown' if item['check_status']=='sold' else item['check_status'] or item["observation"]))
        items.append(item)
    return {"items":items,"total":total,"page":page,"limit":limit,"keywords":keywords,"history_counts":history_counts}


def mark_sold(keyword, item_id, sold, sold_price=None):
    with sqlite_connection() as db:
        result = db.execute("""UPDATE price_survey_items SET sold=?,sold_price=?,sold_at=?,sold_source='manual'
            WHERE keyword=? AND item_id=?""",
            (int(sold),sold_price if sold else None,now() if sold else None,keyword,item_id))
        db.commit()
        return result.rowcount > 0


def create_detail_run(task_id, keyword, item_limit):
    run_id=uuid.uuid4().hex
    with sqlite_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('''SELECT * FROM price_survey_items WHERE keyword=? AND history_source IS NOT NULL
            ORDER BY COALESCE(last_checked,''),first_seen,item_id LIMIT ?''',(keyword,item_limit)).fetchall()
        if not rows: raise ValueError('此分类没有本地历史JSON/JSONL商品，请选择已有历史分类')
        db.execute('''INSERT INTO price_survey_runs
            (id,keyword,task_id,item_limit,state,started_at,kind,target_count)
            VALUES (?,?,?,?,'queued',?,'history_detail',?)''',
            (run_id,keyword,task_id,item_limit,now(),len(rows)))
        for ordinal,row in enumerate(rows,1):
            db.execute('''INSERT INTO price_survey_checks
                (run_id,ordinal,keyword,item_id,title,link,history_price,history_source)
                VALUES (?,?,?,?,?,?,?,?)''',(run_id,ordinal,keyword,row['item_id'],row['title'],
                    row['link'],row['price'],row['history_source']))
        db.commit()
    return get_run(run_id)


def detail_targets(run_id):
    with sqlite_connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM price_survey_checks WHERE run_id=? ORDER BY ordinal',(run_id,))]


def detail_phase(run_id,phase):
    with sqlite_connection() as db:
        row=db.execute("SELECT summary_json FROM price_survey_runs WHERE id=? AND state IN ('queued','running')",(run_id,)).fetchone()
        if row is None:return
        summary=json.loads(row[0] or '{}');summary['stage']=phase
        db.execute('UPDATE price_survey_runs SET summary_json=? WHERE id=?',(json.dumps(summary,ensure_ascii=False),run_id))
        db.commit()


def _check_summary(db, run_id):
    counts=dict(db.execute("SELECT state,COUNT(*) FROM price_survey_checks WHERE run_id=? GROUP BY state",(run_id,)).fetchall())
    return {key+'_count':counts.get(key,0) for key in ('sold','available','unavailable','unknown','failed','pending')}


def record_detail(run_id,item_id,result):
    """Commit only this item's evidence; cancellation cannot publish later results."""
    state=result['status']
    if state not in ('sold','available','unavailable','unknown','failed'):raise ValueError('无效核验状态')
    if state=='sold' and (not result.get('evidence') or result.get('source') not in ('detail_page','detail_api')):
        raise ValueError('自动售出标记必须有当前详情证据')
    stamp=now();asking=parse_price_value(result.get('asking_price'))
    if asking is not None and (not math.isfinite(asking) or asking<0):asking=None
    with sqlite_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT state FROM price_survey_runs WHERE id=?',(run_id,)).fetchone()
        if not run or run[0] not in ('queued','running'):return False
        target=db.execute('SELECT keyword,state FROM price_survey_checks WHERE run_id=? AND item_id=?',(run_id,item_id)).fetchone()
        if not target or target['state']!='pending':return False
        source=result.get('source','detail_page');evidence=result.get('evidence','');reason=result.get('reason','')
        db.execute('''UPDATE price_survey_checks SET state=?,checked_at=?,source=?,evidence=?,reason=?,checked_price=?
            WHERE run_id=? AND item_id=?''',(state,stamp,source,evidence,reason,asking,run_id,item_id))
        db.execute('''UPDATE price_survey_items SET last_checked=?,check_status=?,check_source=?,
            check_evidence=?,checked_price=? WHERE keyword=? AND item_id=?''',
            (stamp,state,source,evidence or reason,asking,target['keyword'],item_id))
        if state=='sold':
            # Existing manual/automatic sale history is never cleared or repriced.
            db.execute('''UPDATE price_survey_items SET sold=1,sold_at=?,sold_source='detail_auto'
                WHERE keyword=? AND item_id=? AND sold=0''',(stamp,target['keyword'],item_id))
        summary=_check_summary(db,run_id)
        checked=sum(v for k,v in summary.items() if k!='pending_count')
        db.execute('UPDATE price_survey_runs SET actual_count=?,summary_json=? WHERE id=?',
                   (checked,json.dumps(summary,ensure_ascii=False),run_id))
        db.commit()
    return True


def complete_details(run_id):
    with sqlite_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        summary=_check_summary(db,run_id)
        if summary['pending_count']:raise ValueError('仍有未核验商品，不能标记完成')
        db.execute("UPDATE price_survey_runs SET state='completed',finished_at=?,summary_json=? WHERE id=? AND state='running'",
                   (now(),json.dumps(summary,ensure_ascii=False),run_id))
        db.commit()


def cancel_details(run_id):
    with sqlite_connection() as db:
        db.execute("UPDATE price_survey_runs SET state='cancelled',finished_at=?,error='已停止；已完成核验保留，未核验商品不变' WHERE id=? AND state IN ('queued','running')",(now(),run_id))
        db.commit()


class SurveyCapture:
    def __init__(self, run_id, item_limit):
        self.run_id, self.item_limit = run_id, item_limit
        self.items = {}
        self.pages = 0
        self.coverage = "sample_limit"

    def add_page(self, items, page, account):
        for item in items:
            item_id = str(item.get("商品ID") or "")
            if item_id and item_id != "未知ID" and len(self.items) < self.item_limit:
                self.items.setdefault(item_id, item)
        self.pages = page
        progress(self.run_id,count=len(self.items),pages=page,account=account)
        return len(self.items) >= self.item_limit

    def complete(self, account):
        finish(self.run_id,list(self.items.values()),account,self.pages,self.coverage)
