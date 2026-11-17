from fastapi import APIRouter

from rescueai.api.v1 import health, jobs

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(jobs.router)
