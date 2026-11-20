from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class BlindStatus(str, Enum):
    sealed = 'sealed'        # 盲态封存，明细仅负责人可见
    unblinding = 'unblinding'  # 揭盲进行中，中断后恢复为 sealed
    revealed = 'revealed'    # 已揭盲，归群明细公开
