from sqlalchemy import String, JSON, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class BlindTrial(Base):
    """盲测工况试验。

    由业务负责人单独录入；揭盲前记录明细仅负责人可读，分析人员只能看到
    脱敏元数据。归群沿用定稿试验的标准化尺度与簇中心，不重新拟合。
    """
    __tablename__ = 'blind_trials'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    # 定稿（已完成且已批准）的分群试验，盲测沿用其尺度与中心。
    baseline_job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    # 定稿口径快照：scaler(mean/scale)、标准化簇中心、K、特征列。
    calibration: Mapped[dict] = mapped_column(JSON, default=dict)
    # sealed=盲态封存；unblinding=揭盲进行中（中断后恢复为 sealed）；revealed=已揭盲公开。
    status: Mapped[str] = mapped_column(String(20), default='sealed')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    revealed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
