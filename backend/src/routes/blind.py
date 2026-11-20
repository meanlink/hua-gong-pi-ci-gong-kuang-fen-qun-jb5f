from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import BlindTrial
from src.schemas.blind import BlindTrialInput, BlindPreviewInput
from src.middlewares.auth import current_user, admin_only, can_write
from src.services import blind
from src.services.audit import record

router = APIRouter(prefix='/blind-trials')


@router.get('')
def listing(db=Depends(get_db), user=Depends(current_user)):
    # 所有角色可看列表，但非负责人在盲态只拿到脱敏元数据。
    return [blind.masked_dict(t, user) for t in
            db.scalars(select(BlindTrial).order_by(BlindTrial.id.desc()))]


@router.post('', status_code=201)
def create(data: BlindTrialInput, db=Depends(get_db), user=Depends(admin_only)):
    # 仅业务负责人可单独录入盲测工况。
    t = blind.create(db, data, user)
    record(db, user.email, 'blind.create', {'id': t.id, 'rows': len(t.records), 'baseline_job_id': t.baseline_job_id})
    db.commit()
    return blind.detail_dict(t, user)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), user=Depends(current_user)):
    t = db.get(BlindTrial, id)
    if not t:
        raise HTTPException(404, '盲测试验不存在')
    return blind.detail_dict(t, user)


@router.post('/{id}/unblind')
def unblind(id: int, db=Depends(get_db), user=Depends(admin_only)):
    t, started = blind.start_unblind(db, id, user)
    if not started:
        # 幂等：重试揭盲不重复发布，直接返回已公开结果。
        record(db, user.email, 'blind.unblind.retry', {'id': id})
        db.commit()
        return blind.detail_dict(t, user)
    record(db, user.email, 'blind.unblind.start', {'id': id})
    db.commit()
    try:
        # 归群失败时服务层已把状态提交回 sealed 并释放锁。
        t = blind.finish_unblind(db, t)
    except HTTPException:
        raise
    record(db, user.email, 'blind.unblind.revealed', {'id': id, 'rows': len(t.records)})
    db.commit()
    return blind.detail_dict(t, user)


@router.post('/preview')
def preview(data: BlindPreviewInput, db=Depends(get_db), user=Depends(can_write)):
    # 页面改参试算：不落库、不排队；与揭盲锁互斥。
    return blind.preview(db, data, user)
