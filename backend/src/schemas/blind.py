from pydantic import BaseModel, Field


class BlindTrialInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)
    baseline_job_id: int


class BlindPreviewInput(BaseModel):
    # 页面改参试算：不落库、不排队，用任意 K 对已公开批次临时拟合后预览。
    dataset_id: int
    clusters: float = Field(default=3)
