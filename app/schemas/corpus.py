from pydantic import BaseModel


class HarvestAreaRequest(BaseModel):
    area_code: str
    year_from: int = 2015
    year_to: int = 2025
    max_results: int | None = None


class DownloadOaPdfsRequest(BaseModel):
    area_code: str | None = None
    limit: int = 100


class ImportScimagoRequest(BaseModel):
    csv_path: str
    year: int
    set_as_current: bool = False


class TaskQueuedResponse(BaseModel):
    task_id: str
    status: str = "queued"
