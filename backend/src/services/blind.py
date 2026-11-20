"""盲测试验：负责人单独录入、封存、沿用定稿口径归群、揭盲发布。"""
import math
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import BlindTrial, Dataset, Job
from src.services.business import (
    FEATURES, LABELS, analyze, assign_with_calibration,
    calibration_from_job, metadata, parse_matrix,
)
from src.utils.serialization import checksum


def _validate_records(records):
    """与普通数据批次一致的字段口径校验，确保盲测明细本身可用。"""
    columns = metadata()['columns']
    for index, row in enumerate(records):
        for c in columns:
            value = row.get(c['key'])
            if value is None or value == '':
                raise HTTPException(422, f'第 {index + 1} 行缺少字段 {c["label"]}')
            if c['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError()
                    row[c['key']] = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index + 1} 行 {c["label"]} 必须为有限数值')
    # 复用算法侧的物理口径校验（正压、正时间、收率0~100等）。
    try:
        parse_matrix(records)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _load_baseline(db, baseline_job_id):
    job = db.get(Job, baseline_job_id)
    if not job:
        raise HTTPException(404, '定稿分群试验不存在')
    if job.status != 'completed' or not job.approved:
        raise HTTPException(409, '仅已完成且获批准的定稿分群可作为盲测口径')
    dataset = db.get(Dataset, job.dataset_id)
    if not dataset:
        raise HTTPException(409, '定稿分群绑定的数据批次已不存在')
    return job, dataset


def create(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '盲测试验名称去除空格后至少需要两个字符')
    if db.scalar(select(BlindTrial).where(BlindTrial.name == name)):
        raise HTTPException(409, '该盲测试验名已存在，请修改名称')
    _validate_records(data.records)
    job, dataset = _load_baseline(db, data.baseline_job_id)
    # 重放定稿同口径拟合，固化标准化尺度与中心；盲测自身不参与拟合。
    try:
        calibration = calibration_from_job(dataset.records, job.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    trial = BlindTrial(
        name=name, source=data.source, records=data.records,
        checksum=checksum(data.records), baseline_job_id=job.id,
        calibration=calibration, status='sealed', result={},
        created_by=user.id, created_at=time.time(),
    )
    db.add(trial)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, '该盲测试验名已存在，请修改名称') from exc
    return trial


def masked_dict(trial, user, include_result=False):
    """揭盲前的脱敏视图：不暴露任何批次明细与归群结果。"""
    is_owner = user.role == 'admin'
    revealed = trial.status == 'revealed'
    base = {
        'id': trial.id, 'name': trial.name, 'source': trial.source,
        'rows': len(trial.records), 'checksum': trial.checksum,
        'baseline_job_id': trial.baseline_job_id, 'status': trial.status,
        'created_at': trial.created_at, 'revealed_at': trial.revealed_at,
        'calibration': {
            'k': trial.calibration.get('k'),
            'baseline_silhouette': trial.calibration.get('baseline_silhouette'),
            'features': trial.calibration.get('features', FEATURES),
        },
    }
    if revealed and include_result:
        # 已揭盲且为详情请求：明细对所有角色公开。列表保持轻量不带结果。
        base['result'] = trial.result
        return base
    if is_owner and not revealed:
        # 负责人在盲态也可核对录入明细（录入方需要自查），但拿不到归群结论。
        base['records'] = trial.records
    return base


def detail_dict(trial, user):
    data = masked_dict(trial, user, include_result=True)
    if trial.status == 'revealed':
        data['records'] = trial.records
    return data


def lock_dataset(db, dataset_id):
    """锁定数据批次行：揭盲与改参试算/新建任务在同一锚点上串行，只接受一方。"""
    dataset = db.execute(
        select(Dataset).where(Dataset.id == dataset_id).with_for_update()
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(404, '数据批次不存在')
    return dataset


def start_unblind(db, trial_id, user):
    """揭盲：锁定定稿分群 → 归群 → 发布。全程行锁，与改参试算互斥。

    幂等：已揭盲直接返回；进行中（他人/中断残留）返回 409。
    """
    trial = db.get(BlindTrial, trial_id)
    if not trial:
        raise HTTPException(404, '盲测试验不存在')
    if trial.status == 'revealed':
        return trial, False
    if trial.status == 'unblinding':
        raise HTTPException(409, '该盲测试验正在揭盲中，请勿重复提交')
    # 先锁定盲测所依赖的数据批次行：与改参试算/新建任务共用同一锚点，
    # 并发请求在 InnoDB 行锁上串行，只接受一方。
    job = db.get(Job, trial.baseline_job_id)
    if job is None:
        raise HTTPException(409, '定稿分群已不存在，无法揭盲')
    lock_dataset(db, job.dataset_id)
    # 再锁定定稿 Job 行。
    job = db.execute(
        select(Job).where(Job.id == trial.baseline_job_id).with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(409, '定稿分群已不存在，无法揭盲')
    if job.blind_lock_id is not None and job.blind_lock_id != trial.id:
        raise HTTPException(409, '定稿分群正在被其他揭盲或改参操作占用，请稍后再试')
    # 同一定稿分群上若有其他已在揭盲的试验，也不允许并发。
    other = db.scalar(
        select(BlindTrial).where(
            BlindTrial.baseline_job_id == job.id,
            BlindTrial.status == 'unblinding',
            BlindTrial.id != trial.id,
        )
    )
    if other:
        raise HTTPException(409, '该定稿分群已有另一个盲测试验在揭盲中')
    job.blind_lock_id = trial.id
    trial.status = 'unblinding'
    db.flush()
    return trial, True


def finish_unblind(db, trial):
    """执行归群并发布；任何异常都回滚到 sealed 并释放锁（中断恢复原定稿）。"""
    job = db.execute(
        select(Job).where(Job.id == trial.baseline_job_id).with_for_update()
    ).scalar_one_or_none()
    try:
        labels, summary_rows, detail_rows = assign_with_calibration(
            trial.records, trial.calibration
        )
    except ValueError as exc:
        # 立即落盘回滚状态，避免依赖重启巡检；调用方提交后再抛业务错误。
        _revert(db, trial, job)
        db.commit()
        raise HTTPException(422, f'盲测归群失败，已恢复盲态：{exc}') from exc
    k = trial.calibration['k']
    counts = {f'工况族群{i}': 0 for i in range(1, k + 1)}
    for label in labels:
        counts[f'工况族群{label}'] += 1
    result = {
        'summary': (
            f"{len(trial.records)}批盲测工况沿用定稿尺度与中心归群，"
            f"未重新拟合；覆盖{k}个定稿族群，明细已随揭盲公开。"
        ),
        'metrics': [
            {'label': '盲测批次数', 'value': len(trial.records)},
            {'label': '沿用定稿K', 'value': k},
            {'label': '定稿轮廓系数', 'value': trial.calibration.get('baseline_silhouette')},
            {'label': '覆盖族群数', 'value': sum(1 for v in counts.values() if v)},
        ],
        'table': {
            'columns': [
                {'key': 'cluster', 'label': '工况族群'},
                {'key': 'count', 'label': '盲测批次数'},
                {'key': 'share_pct', 'label': '占比(%)'},
            ] + [{'key': f, 'label': l} for f, l in zip(FEATURES, LABELS)],
            'rows': summary_rows,
        },
        'details': {
            'columns': [
                {'key': 'batch_id', 'label': '批次'},
                {'key': 'cluster', 'label': '归群'},
                {'key': 'distance', 'label': '到中心标准化距离'},
            ] + [{'key': f, 'label': l} for f, l in zip(FEATURES, LABELS)],
            'rows': detail_rows,
        },
        'method': '盲测沿用定稿试验的Z分数标准化尺度与KMeans簇中心，按欧氏距离最近中心归群，不重新拟合。',
        'warnings': ['盲测归群标签与定稿显示标签一致，标签无优劣含义。'],
    }
    trial.result = result
    trial.status = 'revealed'
    trial.revealed_at = time.time()
    if job is not None:
        job.blind_lock_id = None
    db.flush()
    return trial


def _revert(db, trial, job):
    """揭盲中断后恢复原定稿：试验回到 sealed，释放定稿锁。"""
    trial.status = 'sealed'
    if job is not None and job.blind_lock_id == trial.id:
        job.blind_lock_id = None
    db.flush()


def recover_interrupted(db):
    """启动/巡检时把残留在 unblinding 的试验恢复为 sealed（恢复原定稿）。"""
    trials = list(db.scalars(select(BlindTrial).where(BlindTrial.status == 'unblinding')))
    for trial in trials:
        job = db.get(Job, trial.baseline_job_id)
        _revert(db, trial, job)
    return trials


def preview(db, data, user):
    """页面改参试算：对已公开数据批次临时拟合，不落库、不进队列。

    与揭盲互斥：若所选批次上的定稿分群正被揭盲锁定，拒绝试算。
    """
    # 与揭盲共用数据批次行锁锚点，并发时一方等待，检查到锁即拒绝。
    dataset = lock_dataset(db, data.dataset_id)
    locked = db.scalar(
        select(Job).where(
            Job.dataset_id == dataset.id, Job.blind_lock_id.isnot(None)
        )
    )
    if locked:
        raise HTTPException(409, '该数据批次的定稿分群正在揭盲锁定中，改参试算与揭盲只接受一方')
    try:
        raw_k = float(data.clusters)
        k = int(raw_k)
        if raw_k != k or not 2 <= k <= 6:
            raise ValueError
        result = analyze(dataset.records, {'clusters': k})
    except ValueError as exc:
        raise HTTPException(422, 'K须为2~6的整数。') from exc
    return {
        'dataset_id': dataset.id, 'dataset_name': dataset.name,
        'params': {'clusters': k},
        'ephemeral': True, 'result': result,
    }
