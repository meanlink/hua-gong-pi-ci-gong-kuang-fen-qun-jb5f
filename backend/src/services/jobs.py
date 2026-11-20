import time
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
def create(db, data, user):
    # 与揭盲共用数据批次行锁锚点：并发请求串行，只接受一方。
    dataset=db.execute(select(Dataset).where(Dataset.id==data.dataset_id).with_for_update()).scalar_one_or_none()
    if not dataset: raise HTTPException(404,'数据批次不存在')
    # 盲测揭盲锁与改参试算互斥：定稿分群被揭盲占用时，拒绝在同批数据上新建试算。
    locked=db.scalar(select(Job).where(Job.dataset_id==dataset.id,Job.blind_lock_id.isnot(None)))
    if locked: raise HTTPException(409,'该数据批次的定稿分群正在揭盲锁定中，改参试算与揭盲只接受一方')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=time.time(), status='queued')
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
