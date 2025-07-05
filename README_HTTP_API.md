# ComfyUI Worker HTTP API Mode

This document explains how to use the ComfyUI Worker in HTTP API mode for production deployment on dedicated machines using SQLite for local job management.

## Overview

The HTTP API mode allows you to run the ComfyUI Worker as a standalone HTTP service with local SQLite-based job management. This completely replaces the external RunPod API dependency with a self-contained, production-ready solution.

**The handler now supports both HTTP API mode and original RunPod serverless mode**, making it a hybrid solution that can be deployed in various environments.

## Key Features

- **REST API Interface**: Submit jobs via HTTP POST to `/run` endpoint
- **SQLite Job Storage**: Local database for job persistence and management
- **Asynchronous Processing**: Jobs are processed asynchronously in the background
- **Status Checking**: Check job status and retrieve results via `/status/{job_id}` endpoint
- **Full ComfyUI Integration**: Maintains all ComfyUI functionality including image uploads, websocket communication, and result processing
- **Production Ready**: Built on FastAPI with proper error handling, logging, and job cleanup
- **Self-Contained**: No external dependencies - everything runs locally
- **Admin Endpoints**: Job management, statistics, and cleanup capabilities

## Code Organization

The code is now organized in the `api/` subfolder for better management:
- `api/job_manager.py` - SQLite job management with Job dataclass and thread-safe operations
- `api/server.py` - FastAPI HTTP server with all endpoints
- `api/handler.py` - Hybrid handler supporting both HTTP API and serverless modes
- `api/client.py` - Example client demonstrating API usage

## Mode Selection

The worker supports two modes:

### HTTP API Mode (New)
Set `HTTP_API_MODE=true` to enable SQLite-based job management with HTTP API server.

### RunPod Serverless Mode (Original)
Default mode when `HTTP_API_MODE` is not set or set to `false`. Uses original RunPod serverless functionality.

## Architecture

### HTTP API Mode
```
HTTP Request → FastAPI Server → SQLite Database → RunPod Worker → ComfyUI → Results
```

### Serverless Mode
```
RunPod Queue → RunPod Worker → ComfyUI → Results
```

1. **FastAPI Server**: Handles HTTP requests and responses (HTTP API mode only)
2. **SQLite Database**: Persistent job storage with status tracking (HTTP API mode only)
3. **RunPod Worker**: Processes jobs using the existing ComfyUI handler
4. **ComfyUI**: Executes the actual image generation workflow

## Configuration

### Environment Variables

- `HTTP_API_MODE`: Set to `true` to enable HTTP API mode (default: `false`)
- `API_HOST`: Host to bind the HTTP API server (default: `0.0.0.0`)
- `API_PORT`: Port for the HTTP API server (default: `8000`)
- `SQLITE_DB_PATH`: Path to SQLite database file (default: `/tmp/comfyui_jobs.db`)
- `COMFY_LOG_LEVEL`: ComfyUI logging level (default: `DEBUG`)

### Other ComfyUI Environment Variables

All existing ComfyUI environment variables are supported:
- `BUCKET_ENDPOINT_URL`: S3 bucket configuration for image uploads
- `WEBSOCKET_RECONNECT_ATTEMPTS`: WebSocket reconnection attempts
- `WEBSOCKET_RECONNECT_DELAY_S`: Delay between reconnection attempts
- `WEBSOCKET_TRACE`: Enable WebSocket tracing
- `REFRESH_WORKER`: Refresh worker after each job

## Usage

### Starting the Server

#### Using Docker

```bash
# Start with HTTP API mode enabled
docker run -it \
  -e HTTP_API_MODE=true \
  -e API_HOST=0.0.0.0 \
  -e API_PORT=8000 \
  -e SQLITE_DB_PATH=/data/comfyui_jobs.db \
  -p 8000:8000 \
  -p 8188:8188 \
  -v comfyui_data:/data \
  your-comfyui-image /start.sh
```

#### Using Docker Compose

```yaml
version: '3.8'
services:
  comfyui-worker:
    image: your-comfyui-image
    environment:
      - HTTP_API_MODE=true
      - API_HOST=0.0.0.0
      - API_PORT=8000
      - SQLITE_DB_PATH=/data/comfyui_jobs.db
      - COMFY_LOG_LEVEL=INFO
    ports:
      - "8000:8000"  # HTTP API
      - "8188:8188"  # ComfyUI (optional, for direct access)
    volumes:
      - sqlite_data:/data
    command: ["/start.sh"]

volumes:
  sqlite_data:
```

### API Endpoints

#### Job Management

**Submit Job - POST `/run`**

Submit a new job for processing.

**Request Body:**
```json
{
  "workflow": {
    "1": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {
        "ckpt_name": "flux1-dev.safetensors"
      }
    },
    "2": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "A beautiful landscape",
        "clip": ["1", 1]
      }
    }
    // ... rest of ComfyUI workflow
  },
  "images": [
    {
      "name": "input_image.png",
      "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

**Check Status - GET `/status/{job_id}`**

Check the status of a submitted job.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "images": [
      {
        "filename": "ComfyUI_00001_.png",
        "type": "base64",
        "data": "iVBORw0KGgoAAAANSUhEUgAA..."
      }
    ]
  },
  "error": null,
  "created_at": 1704067200.0,
  "started_at": 1704067205.0,
  "completed_at": 1704067225.0
}
```

#### Monitoring and Statistics

**Health Check - GET `/health`**

Check the health status of the API server with job statistics.

**Response:**
```json
{
  "status": "healthy",
  "database_path": "/data/comfyui_jobs.db",
  "job_stats": {
    "pending": 2,
    "running": 1,
    "completed": 15,
    "failed": 1,
    "total": 19
  }
}
```

**Statistics - GET `/stats`**

Get detailed job statistics.

**Query Parameters:**
- `include_recent`: Include recent jobs (default: false)

**Response:**
```json
{
  "total_jobs": 19,
  "pending_jobs": 2,
  "running_jobs": 1,
  "completed_jobs": 15,
  "failed_jobs": 1,
  "recent_jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "completed",
      "created_at": 1704067200.0,
      "started_at": 1704067205.0,
      "completed_at": 1704067225.0,
      "error": null
    }
  ]
}
```

#### Administration

**Manual Cleanup - POST `/admin/cleanup`**

Manually trigger cleanup of old completed/failed jobs.

**Query Parameters:**
- `max_age_hours`: Maximum age in hours (default: 24)

**Reset Stuck Jobs - POST `/admin/reset-stuck`**

Reset jobs that have been running too long.

**Query Parameters:**
- `max_running_time_hours`: Maximum running time in hours (default: 2)

**Delete Job - DELETE `/admin/job/{job_id}`**

Delete a specific completed or failed job.

### Job Status Values

- `pending`: Job is queued but not yet started
- `running`: Job is currently being processed
- `completed`: Job completed successfully
- `failed`: Job failed with an error

## Database Features

### Automatic Cleanup

The system automatically:
- Cleans up completed/failed jobs older than 24 hours
- Resets stuck jobs that have been running for more than 2 hours
- Runs cleanup tasks every hour in the background

### Persistence

- All job data is stored in SQLite database
- Jobs persist across container restarts
- Database can be backed up and restored
- Thread-safe operations with file locking

### Statistics and Monitoring

- Real-time job statistics
- Recent job history
- Database health monitoring
- Failed job tracking and analysis

## Example Usage

### Python Client

```python
import requests
import time

API_BASE = "http://localhost:8000"

# Submit a job
workflow = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "flux1-dev.safetensors"}
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "A beautiful landscape with mountains and a lake",
            "clip": ["1", 1]
        }
    }
    # ... add your complete workflow here
}

# Submit job
response = requests.post(f"{API_BASE}/run", json={
    "workflow": workflow,
    "images": []
})

job_data = response.json()
job_id = job_data["job_id"]
print(f"Job submitted: {job_id}")

# Poll for completion
while True:
    response = requests.get(f"{API_BASE}/status/{job_id}")
    status_data = response.json()
    
    print(f"Status: {status_data['status']}")
    
    if status_data["status"] == "completed":
        print("Job completed successfully!")
        for image in status_data["result"]["images"]:
            print(f"Generated image: {image['filename']}")
        break
    elif status_data["status"] == "failed":
        print(f"Job failed: {status_data['error']}")
        break
    
    time.sleep(5)

# Get system statistics
stats = requests.get(f"{API_BASE}/stats?include_recent=true").json()
print(f"System stats: {stats}")
```

### cURL Examples

Submit a job:
```bash
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": {
      "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
          "ckpt_name": "flux1-dev.safetensors"
        }
      }
    }
  }'
```

Check status:
```bash
curl "http://localhost:8000/status/550e8400-e29b-41d4-a716-446655440000"
```

Get statistics:
```bash
curl "http://localhost:8000/stats?include_recent=true"
```

Manual cleanup:
```bash
curl -X POST "http://localhost:8000/admin/cleanup?max_age_hours=12"
```

## Performance Considerations

- **Database Performance**: SQLite with indexes for fast job queries
- **Concurrency**: Worker processes jobs sequentially. Run multiple instances for higher throughput
- **Memory Management**: Jobs are persisted to disk, minimal memory usage
- **Storage**: Generated images returned as base64 or S3 URLs. Database cleanup prevents disk bloat
- **Background Tasks**: Automatic cleanup and monitoring tasks

## Monitoring and Maintenance

### Health Monitoring

- Use the `/health` endpoint for monitoring
- Monitor job statistics via `/stats` endpoint
- Check logs for detailed processing information
- Monitor ComfyUI directly on port 8188 if exposed

### Database Maintenance

- Automatic cleanup of old jobs (configurable)
- Manual cleanup via `/admin/cleanup` endpoint
- Database backup recommendations
- Stuck job detection and recovery

### Production Considerations

1. **Database Backup**: Regular backups of SQLite database
2. **Monitoring**: Set up alerts for failed jobs and system health
3. **Log Management**: Proper log rotation and archival
4. **Resource Monitoring**: Monitor CPU, memory, and disk usage
5. **Security**: Implement authentication and rate limiting

## Troubleshooting

### Common Issues

1. **ComfyUI not starting**: Check logs for ComfyUI startup errors
2. **Jobs stuck in pending**: Verify ComfyUI is running and accessible
3. **Database locked**: Check file permissions and disk space
4. **WebSocket errors**: Check ComfyUI WebSocket connectivity
5. **Model loading errors**: Verify model files are present and accessible

### Debugging

Enable debug mode:
```bash
export COMFY_LOG_LEVEL=DEBUG
export WEBSOCKET_TRACE=true
```

Check database directly:
```bash
sqlite3 /data/comfyui_jobs.db "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 10;"
```

### Recovery

Reset stuck jobs:
```bash
curl -X POST "http://localhost:8000/admin/reset-stuck"
```

Manual database cleanup:
```bash
curl -X POST "http://localhost:8000/admin/cleanup?max_age_hours=1"
```

## Migration from RunPod Serverless

To migrate from RunPod Serverless to HTTP API mode:

1. Update your deployment to use the new Docker image
2. Set `HTTP_API_MODE=true` environment variable
3. Configure `SQLITE_DB_PATH` for database location
4. Update your client code to use the new HTTP endpoints
5. Remove RunPod-specific environment variables
6. Set up volume mounts for database persistence

## Production Deployment

For production deployment:

1. **Reverse Proxy**: Use nginx or traefik for SSL termination
2. **Database**: Mount SQLite database on persistent volume
3. **Monitoring**: Implement health checks and monitoring
4. **Backup**: Set up automated database backups
5. **Scaling**: Deploy multiple instances behind load balancer
6. **Security**: Implement authentication, rate limiting, and HTTPS

## Security Considerations

- The API has no built-in authentication. Implement authentication at the reverse proxy level.
- Validate input workflows to prevent malicious code execution.
- Use HTTPS in production.
- Implement rate limiting to prevent abuse.
- Secure SQLite database file permissions.
- Regular security updates and monitoring.

## Support

This HTTP API mode with SQLite job management provides a complete, self-contained solution for production ComfyUI deployments. All existing ComfyUI functionality is preserved while adding robust job management, persistence, and monitoring capabilities. 