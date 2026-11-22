import logging

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from redis.exceptions import RedisError

from src.config.database import connect, queue
from src.constants.domain import BatchChoice, EntryStatus, Role, RunState
from src.services.audit import record
from src.services.crossover import METHOD
from src.services.field import ledger_rows, route_or_error
from src.utils.serial import fingerprint

WAKE_KEY = 'ramp:recalculate'
LOGGER = logging.getLogger(__name__)

REJECT_REASONS = {
    EntryStatus.DUPLICATE: '重复上传，未重复计数',
    EntryStatus.SEQUENCE_CONFLICT: '上传顺序与台账分配冲突，未纳入',
    EntryStatus.CONFLICT: '被后续批次覆盖，原值无法恢复',
}


def inclusion(row):
    missing = [f'第 {number} 轮' for number, key in ((1, 'period1'), (2, 'period2')) if row[key] is None]
    label = row['batch_label'] or '未标注批次'
    if row['entry_status'] == EntryStatus.PASSED and not missing:
        return True, f'批次「{label}」校验通过'
    if missing:
        return False, f'缺测{"、".join(missing)}，未纳入'
    return False, '对账标记未通过，未纳入'


def snapshot_pair(row):
    included, reason = inclusion(row)
    return {
        'code': row['code'],
        'sequence': row['sequence'],
        'period1': format(row['period1'], '.2f') if row['period1'] is not None else None,
        'period2': format(row['period2'], '.2f') if row['period2'] is not None else None,
        'batch_id': row['batch_id'],
        'batch_label': row['batch_label'],
        'included': included,
        'reason': reason,
    }


def rejected_rows(db, route_code):
    rows = db.execute('''
        SELECT e.code, e.sequence, e.kind, e.status, b.label AS batch_label
        FROM collection_entry AS e JOIN collection_batch AS b ON b.id=e.batch_id
        WHERE e.route_code=%s AND e.status IN ('duplicate', 'sequence_conflict', 'conflict')
        ORDER BY e.id
    ''', (route_code,)).fetchall()
    return [dict(row, reason=REJECT_REASONS[row['status']]) for row in rows]


def latest_batch(db, route_code):
    return db.execute('SELECT * FROM collection_batch WHERE route_code=%s ORDER BY id DESC LIMIT 1',
                      (route_code,)).fetchone()


def latest_complete_batch(db, route_code):
    return db.execute('''
        SELECT b.* FROM collection_batch AS b
        WHERE b.route_code=%s
          AND EXISTS (SELECT 1 FROM collection_entry AS e WHERE e.batch_id=b.id)
          AND NOT EXISTS (SELECT 1 FROM collection_entry AS e WHERE e.batch_id=b.id
                          AND e.status NOT IN ('passed', 'duplicate'))
        ORDER BY b.id DESC LIMIT 1
    ''', (route_code,)).fetchone()


def create_run(plan_id, actor):
    with connect() as db:
        plan = db.execute('SELECT * FROM analysis_plan WHERE id=%s', (plan_id,)).fetchone()
        if plan is None:
            raise HTTPException(404, '未找到参数版本')
        route = route_or_error(db, plan['route_code'])
        batch = latest_batch(db, route['code'])
        if batch is None:
            raise HTTPException(409, '请先建立采集批次并登记台账')
        snapshot = {
            'method': METHOD,
            'route': route,
            'plan': {'id': plan_id, 'edition': plan['edition'], 'min_pairs': plan['min_pairs'], 'gap_limit': format(plan['gap_limit'], '.2f')},
            'batch': {'id': batch['id'], 'label': batch['label'], 'source': batch['source']},
            'pairs': [snapshot_pair(row) for row in ledger_rows(db, route['code'])],
            'rejected': rejected_rows(db, route['code']),
        }
        digest = fingerprint(snapshot)
        existing = db.execute('''
            SELECT id, state, fingerprint FROM report
            WHERE fingerprint=%s AND state IN ('queued', 'ready', 'published') ORDER BY id LIMIT 1
        ''', (digest,)).fetchone()
        if existing is not None:
            record(db, actor, 'run_deduplicated', str(existing['id']), {'fingerprint': digest})
            return existing
        report = db.execute('INSERT INTO report (plan_id, created_by, snapshot, fingerprint, batch_id) VALUES (%s,%s,%s,%s,%s) '
                            'RETURNING id, state, fingerprint', (plan_id, actor, Jsonb(snapshot), digest, batch['id'])).fetchone()
        record(db, actor, 'run_queued', str(report['id']), {'fingerprint': digest, 'batch_id': batch['id']})
    try:
        queue.lpush(WAKE_KEY, 'pending')
    except RedisError:
        LOGGER.warning('Redis wake-up failed, worker will poll PostgreSQL')
    return report


def list_reports(user):
    with connect() as db:
        return db.execute('''
            SELECT r.id, r.state, r.created_by AS actor, r.created_at, r.decision, r.batch_choice,
                   r.adopted_report_id, p.edition, p.route_code, b.label AS batch_label
            FROM report AS r JOIN analysis_plan AS p ON p.id=r.plan_id
            LEFT JOIN collection_batch AS b ON b.id=r.batch_id
            WHERE (%s OR r.state='published') ORDER BY r.id DESC
        ''', (user['role'] != Role.VIEWER,)).fetchall()


def report_or_error(db, report_id, user, lock=False):
    suffix = ' FOR UPDATE' if lock else ''
    report = db.execute('SELECT * FROM report WHERE id=%s' + suffix, (report_id,)).fetchone()
    if report is None or (user['role'] == Role.VIEWER and report['state'] != RunState.PUBLISHED):
        raise HTTPException(404, '未找到可阅报告')
    return report


def batch_summary(db, batch_id):
    if batch_id is None:
        return None
    return db.execute('SELECT id, label, source, created_by, created_at FROM collection_batch WHERE id=%s',
                      (batch_id,)).fetchone()


def get_report(report_id, user):
    with connect() as db:
        report = report_or_error(db, report_id, user)
        report['batch'] = batch_summary(db, report['batch_id'])
        report['adopted'] = None
        if report['adopted_report_id']:
            adopted = db.execute('SELECT id, state, batch_id, result, fingerprint, finished_at FROM report WHERE id=%s',
                                 (report['adopted_report_id'],)).fetchone()
            if adopted is not None:
                adopted['batch'] = batch_summary(db, adopted['batch_id'])
                if user['role'] == Role.VIEWER and adopted['state'] != RunState.PUBLISHED:
                    adopted.pop('result')
                report['adopted'] = adopted
        return report


def publish(report_id, review, user):
    with connect() as db:
        report = report_or_error(db, report_id, user, lock=True)
        if report['state'] != RunState.READY:
            raise HTTPException(409, '仅可发布已完成且待复核的报告')
        plan = db.execute('SELECT * FROM analysis_plan WHERE id=%s', (report['plan_id'],)).fetchone()
        adopted = None
        if review.batch_choice == BatchChoice.LATEST_COMPLETE:
            batch = latest_complete_batch(db, plan['route_code'])
            if batch is None:
                raise HTTPException(409, '当前没有校验完整的采集批次可采用')
            if batch['id'] != report['batch_id']:
                adopted = db.execute('''
                    SELECT * FROM report WHERE plan_id=%s AND batch_id=%s AND id!=%s
                    AND state IN ('ready', 'published') ORDER BY id DESC LIMIT 1
                ''', (report['plan_id'], batch['id'], report_id)).fetchone()
                if adopted is None:
                    raise HTTPException(409, '最新完整批次尚无同一参数版本的完成运行，请先由分析员提交')
        basis = adopted['result'] if adopted else report['result']
        if review.decision not in basis['decisions']:
            raise HTTPException(422, '当前数据和告警状态不支持此决定')
        report = db.execute('''
            UPDATE report SET state='published', decision=%s, review_note=%s, reviewed_by=%s, reviewed_at=now(),
                   batch_choice=%s, adopted_report_id=%s
            WHERE id=%s RETURNING *
        ''', (review.decision, review.note, user['username'], review.batch_choice,
              adopted['id'] if adopted else None, report_id)).fetchone()
        record(db, user['username'], 'report_published', str(report_id), {
            'decision': review.decision, 'note': review.note, 'batch_choice': review.batch_choice,
            'adopted_report_id': adopted['id'] if adopted else None,
        })
        return report
