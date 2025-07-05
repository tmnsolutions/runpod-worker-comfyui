"""
HTTP API Server for ComfyUI Worker
Uses SQLite for local job management instead of external RunPod API
"""

import asyncio
import json
import time
from typing import Dict, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import threading
import os
from contextlib import asynccontextmanager

# Import our job manager
from .job_manager import job_manager, sqlite_jobs_fetcher, sqlite_jobs_handler, JobStatus

class JobRequest(BaseModel):
    """HTTP request model for job submission"""
    workflow: dict
    images: Optional[list] = None

class JobResponse(BaseModel):
    """HTTP response model for job submission"""
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    """HTTP response model for job status"""
    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    database_path: str
    job_stats: Dict[str, int]

class StatsResponse(BaseModel):
    """Statistics response model"""
    total_jobs: int
    pending_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    recent_jobs: Optional[list] = None

# Background task for cleanup
def cleanup_old_jobs():
    """Background task to clean up old jobs"""
    while True:
        try:
            # Clean up jobs older than 24 hours
            deleted_count = job_manager.cleanup_old_jobs(max_age_hours=24)
            if deleted_count > 0:
                print(f"Cleaned up {deleted_count} old jobs")
            
            # Reset stuck jobs (running for more than 2 hours)
            reset_count = job_manager.reset_stuck_jobs(max_running_time_hours=2)
            if reset_count > 0:
                print(f"Reset {reset_count} stuck jobs")
            
            # Sleep for 1 hour before next cleanup
            time.sleep(3600)
            
        except Exception as e:
            print(f"Error in cleanup task: {e}")
            time.sleep(600)  # Wait 10 minutes before retrying

# Startup/shutdown event handlers
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    # Startup: Start background cleanup task
    cleanup_thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
    cleanup_thread.start()
    print("Started background cleanup task")
    
    # Reset any stuck jobs on startup
    reset_count = job_manager.reset_stuck_jobs(max_running_time_hours=2)
    if reset_count > 0:
        print(f"Reset {reset_count} stuck jobs on startup")
    
    yield
    
    # Shutdown: Nothing special needed as threads will be terminated

# FastAPI app with lifespan events
app = FastAPI(
    title="ComfyUI Worker API",
    description="HTTP API for ComfyUI Worker with SQLite job management",
    version="1.0.0",
    lifespan=lifespan
)

@app.post("/run", response_model=JobResponse)
async def run_job(job_request: JobRequest):
    """
    Submit a new job for processing.
    Returns immediately with job_id for status checking.
    """
    try:
        # Create job in database
        job_id = job_manager.create_job({
            "workflow": job_request.workflow,
            "images": job_request.images
        })
        
        return JobResponse(job_id=job_id, status="pending")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get the status and result of a job.
    """
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with job statistics"""
    try:
        stats = job_manager.get_job_stats()
        return HealthResponse(
            status="healthy",
            database_path=job_manager.db_path,
            job_stats=stats
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@app.get("/stats", response_model=StatsResponse)
async def get_stats(include_recent: bool = False):
    """Get detailed job statistics"""
    try:
        stats = job_manager.get_job_stats()
        
        response = StatsResponse(
            total_jobs=stats.get('total', 0),
            pending_jobs=stats.get('pending', 0),
            running_jobs=stats.get('running', 0),
            completed_jobs=stats.get('completed', 0),
            failed_jobs=stats.get('failed', 0)
        )
        
        if include_recent:
            recent_jobs = job_manager.get_recent_jobs(limit=50)
            response.recent_jobs = [
                {
                    "id": job.id,
                    "status": job.status.value,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "error": job.error[:100] if job.error else None  # Truncate long errors
                }
                for job in recent_jobs
            ]
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@app.post("/admin/cleanup")
async def manual_cleanup(max_age_hours: int = 24):
    """Manually trigger cleanup of old jobs"""
    try:
        deleted_count = job_manager.cleanup_old_jobs(max_age_hours=max_age_hours)
        return {"message": f"Cleaned up {deleted_count} old jobs"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@app.post("/admin/reset-stuck")
async def reset_stuck_jobs(max_running_time_hours: int = 2):
    """Manually reset stuck jobs"""
    try:
        reset_count = job_manager.reset_stuck_jobs(max_running_time_hours=max_running_time_hours)
        return {"message": f"Reset {reset_count} stuck jobs"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

@app.delete("/admin/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a specific job (admin endpoint)"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Only allow deletion of completed or failed jobs
    if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]:
        raise HTTPException(status_code=400, detail="Can only delete completed or failed jobs")
    
    try:
        # Delete job from database
        with job_manager._get_connection() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            
        if cursor.rowcount > 0:
            return {"message": f"Job {job_id} deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Job not found")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")

def start_api_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the HTTP API server"""
    uvicorn.run(app, host=host, port=port)

def start_worker_with_sqlite_jobs(original_handler):
    """
    Start the RunPod worker with SQLite job management.
    This should be called from your handler.py after importing this module.
    """
    import runpod
    
    # Ensure we're in local mode by unsetting the RunPod webhook
    if "RUNPOD_WEBHOOK_GET_JOB" in os.environ:
        del os.environ["RUNPOD_WEBHOOK_GET_JOB"]
    
    config = {
        "handler": original_handler,
        "original_handler": original_handler,  # Store original for custom handler
        "jobs_fetcher": sqlite_jobs_fetcher,
        "jobs_handler": sqlite_jobs_handler,
        "jobs_fetcher_timeout": 30,  # Shorter timeout for responsiveness
    }
    
    # Start the worker
    runpod.serverless.start(config)

if __name__ == "__main__":
    # For testing the API server standalone
    start_api_server() 