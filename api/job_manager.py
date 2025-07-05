"""
Local SQLite-based job manager for ComfyUI Worker
Replaces external RunPod API dependency with local database
"""

import sqlite3
import json
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from contextlib import contextmanager
import threading
import os

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Job:
    """Job data structure"""
    id: str
    input: Dict[str, Any]
    status: JobStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

class JobManager:
    """Local SQLite-based job manager"""
    
    def __init__(self, db_path: str = "/tmp/comfyui_jobs.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database with jobs table"""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL
                )
            ''')
            
            # Create indexes for better performance
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_status 
                ON jobs(status)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at 
                ON jobs(created_at)
            ''')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper error handling"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_job(self, input_data: Dict[str, Any]) -> str:
        """Create a new job and return its ID"""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            input=input_data,
            status=JobStatus.PENDING
        )
        
        with self.lock:
            with self._get_connection() as conn:
                conn.execute('''
                    INSERT INTO jobs (id, input, status, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (
                    job.id,
                    json.dumps(job.input),
                    job.status.value,
                    job.created_at
                ))
                conn.commit()
        
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID"""
        with self._get_connection() as conn:
            row = conn.execute('''
                SELECT * FROM jobs WHERE id = ?
            ''', (job_id,)).fetchone()
            
            if row:
                return Job(
                    id=row['id'],
                    input=json.loads(row['input']),
                    status=JobStatus(row['status']),
                    result=json.loads(row['result']) if row['result'] else None,
                    error=row['error'],
                    created_at=row['created_at'],
                    started_at=row['started_at'],
                    completed_at=row['completed_at']
                )
        return None
    
    def get_pending_jobs(self, limit: int = 1) -> List[Job]:
        """Get pending jobs for processing"""
        jobs = []
        with self._get_connection() as conn:
            rows = conn.execute('''
                SELECT * FROM jobs 
                WHERE status = ? 
                ORDER BY created_at ASC 
                LIMIT ?
            ''', (JobStatus.PENDING.value, limit)).fetchall()
            
            for row in rows:
                job = Job(
                    id=row['id'],
                    input=json.loads(row['input']),
                    status=JobStatus(row['status']),
                    result=json.loads(row['result']) if row['result'] else None,
                    error=row['error'],
                    created_at=row['created_at'],
                    started_at=row['started_at'],
                    completed_at=row['completed_at']
                )
                jobs.append(job)
        
        return jobs
    
    def update_job_status(self, job_id: str, status: JobStatus, 
                         result: Optional[Dict[str, Any]] = None, 
                         error: Optional[str] = None) -> bool:
        """Update job status and optionally set result or error"""
        with self.lock:
            with self._get_connection() as conn:
                current_time = time.time()
                
                # Prepare update fields
                update_fields = ['status = ?']
                update_values = [status.value]
                
                if status == JobStatus.RUNNING:
                    update_fields.append('started_at = ?')
                    update_values.append(current_time)
                elif status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    update_fields.append('completed_at = ?')
                    update_values.append(current_time)
                
                if result is not None:
                    update_fields.append('result = ?')
                    update_values.append(json.dumps(result))
                
                if error is not None:
                    update_fields.append('error = ?')
                    update_values.append(error)
                
                update_values.append(job_id)
                
                cursor = conn.execute(f'''
                    UPDATE jobs 
                    SET {', '.join(update_fields)}
                    WHERE id = ?
                ''', update_values)
                
                conn.commit()
                return cursor.rowcount > 0
    
    def get_job_stats(self) -> Dict[str, int]:
        """Get job statistics"""
        with self._get_connection() as conn:
            stats = {}
            for status in JobStatus:
                count = conn.execute('''
                    SELECT COUNT(*) FROM jobs WHERE status = ?
                ''', (status.value,)).fetchone()[0]
                stats[status.value] = count
            
            # Get total jobs
            total = conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            stats['total'] = total
            
            return stats
    
    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Clean up old completed/failed jobs"""
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    DELETE FROM jobs 
                    WHERE status IN (?, ?) 
                    AND (completed_at IS NOT NULL AND completed_at < ?)
                ''', (JobStatus.COMPLETED.value, JobStatus.FAILED.value, cutoff_time))
                
                conn.commit()
                return cursor.rowcount
    
    def get_recent_jobs(self, limit: int = 100) -> List[Job]:
        """Get recent jobs for monitoring"""
        jobs = []
        with self._get_connection() as conn:
            rows = conn.execute('''
                SELECT * FROM jobs 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,)).fetchall()
            
            for row in rows:
                job = Job(
                    id=row['id'],
                    input=json.loads(row['input']),
                    status=JobStatus(row['status']),
                    result=json.loads(row['result']) if row['result'] else None,
                    error=row['error'],
                    created_at=row['created_at'],
                    started_at=row['started_at'],
                    completed_at=row['completed_at']
                )
                jobs.append(job)
        
        return jobs
    
    def reset_stuck_jobs(self, max_running_time_hours: int = 2) -> int:
        """Reset jobs that have been running too long"""
        cutoff_time = time.time() - (max_running_time_hours * 3600)
        
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE jobs 
                    SET status = ?, error = ?, completed_at = ?
                    WHERE status = ? 
                    AND started_at IS NOT NULL 
                    AND started_at < ?
                ''', (
                    JobStatus.FAILED.value,
                    "Job timed out (stuck in running state)",
                    time.time(),
                    JobStatus.RUNNING.value,
                    cutoff_time
                ))
                
                conn.commit()
                return cursor.rowcount

# Global job manager instance
job_manager = JobManager()

# Custom jobs fetcher for RunPod worker
async def sqlite_jobs_fetcher(session, jobs_needed: int):
    """
    Custom jobs fetcher that pulls from SQLite database.
    This replaces the default RunPod job fetcher.
    """
    jobs = []
    
    # Get pending jobs from database
    pending_jobs = job_manager.get_pending_jobs(limit=jobs_needed)
    
    if not pending_jobs:
        return None
    
    # Convert to RunPod job format and mark as running
    for job in pending_jobs:
        # Mark job as running
        job_manager.update_job_status(job.id, JobStatus.RUNNING)
        
        # Convert to RunPod format
        runpod_job = {
            "id": job.id,
            "input": job.input
        }
        jobs.append(runpod_job)
    
    return jobs

# Custom jobs handler for RunPod worker
async def sqlite_jobs_handler(session, config, job):
    """
    Custom jobs handler that stores results in SQLite database.
    This wraps the original ComfyUI handler.
    """
    job_id = job["id"]
    
    try:
        # Call the original handler
        result = config["original_handler"](job)
        
        # Store the result in database
        job_manager.update_job_status(job_id, JobStatus.COMPLETED, result=result)
        
    except Exception as e:
        # Store the error in database
        job_manager.update_job_status(job_id, JobStatus.FAILED, error=str(e))
        raise 