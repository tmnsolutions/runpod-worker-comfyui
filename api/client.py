#!/usr/bin/env python3
"""
Example client for ComfyUI Worker HTTP API with SQLite job management
This script demonstrates how to submit jobs, check status, and use admin endpoints.
"""

import requests
import json
import time
import base64
import os
from pathlib import Path

# Configuration
API_BASE = "http://localhost:8000"
POLL_INTERVAL = 5  # seconds

def load_workflow(workflow_file):
    """Load a workflow from a JSON file."""
    with open(workflow_file, 'r') as f:
        return json.load(f)

def encode_image(image_path):
    """Encode an image file to base64."""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def save_base64_image(base64_data, output_path):
    """Save a base64 encoded image to a file."""
    with open(output_path, 'wb') as f:
        f.write(base64.b64decode(base64_data))

def check_api_health():
    """Check if the API is healthy and return statistics."""
    try:
        response = requests.get(f"{API_BASE}/health")
        if response.status_code == 200:
            health_data = response.json()
            print(f"✓ API is healthy")
            print(f"  Database: {health_data['database_path']}")
            print(f"  Job stats: {health_data['job_stats']}")
            return True
        else:
            print(f"✗ API health check failed: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to API server")
        return False

def get_detailed_stats():
    """Get detailed statistics with recent jobs."""
    try:
        response = requests.get(f"{API_BASE}/stats", params={"include_recent": True})
        if response.status_code == 200:
            stats_data = response.json()
            print(f"📊 System Statistics:")
            print(f"  Total jobs: {stats_data['total_jobs']}")
            print(f"  Pending: {stats_data['pending_jobs']}")
            print(f"  Running: {stats_data['running_jobs']}")
            print(f"  Completed: {stats_data['completed_jobs']}")
            print(f"  Failed: {stats_data['failed_jobs']}")
            
            if stats_data.get('recent_jobs'):
                print(f"  Recent jobs:")
                for job in stats_data['recent_jobs'][:5]:  # Show last 5
                    status_icon = "✓" if job['status'] == 'completed' else "✗" if job['status'] == 'failed' else "⏳"
                    print(f"    {status_icon} {job['id'][:8]}... ({job['status']})")
            
            return stats_data
        else:
            print(f"✗ Failed to get stats: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Error getting stats: {e}")
        return None

def submit_job(workflow, images=None):
    """Submit a job to the API."""
    payload = {
        "workflow": workflow,
        "images": images or []
    }
    
    print("📤 Submitting job...")
    try:
        response = requests.post(f"{API_BASE}/run", json=payload)
        
        if response.status_code == 200:
            job_data = response.json()
            print(f"✓ Job submitted successfully: {job_data['job_id']}")
            return job_data['job_id']
        else:
            print(f"✗ Error submitting job: {response.status_code}")
            if response.headers.get('content-type', '').startswith('application/json'):
                error_data = response.json()
                print(f"   Details: {error_data.get('detail', 'Unknown error')}")
            else:
                print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"✗ Exception submitting job: {e}")
        return None

def check_job_status(job_id):
    """Check the status of a job."""
    try:
        response = requests.get(f"{API_BASE}/status/{job_id}")
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"✗ Job {job_id} not found")
            return None
        else:
            print(f"✗ Error checking status: {response.status_code}")
            print(response.text)
            return None
    except Exception as e:
        print(f"✗ Exception checking status: {e}")
        return None

def wait_for_completion(job_id, timeout=600):
    """Wait for a job to complete and return the result."""
    start_time = time.time()
    last_status = None
    
    print(f"⏳ Waiting for job {job_id[:8]}... to complete (timeout: {timeout}s)")
    
    while True:
        if time.time() - start_time > timeout:
            print(f"⏰ Job {job_id[:8]}... timed out after {timeout} seconds")
            return None
        
        status_data = check_job_status(job_id)
        if not status_data:
            return None
        
        status = status_data['status']
        
        # Only print status changes to reduce noise
        if status != last_status:
            status_icon = "⏳" if status == 'pending' else "🏃" if status == 'running' else "✓" if status == 'completed' else "✗"
            print(f"  {status_icon} Status: {status}")
            last_status = status
        
        if status == "completed":
            elapsed = time.time() - start_time
            print(f"✓ Job completed successfully in {elapsed:.1f}s!")
            return status_data
        elif status == "failed":
            print(f"✗ Job failed: {status_data.get('error', 'Unknown error')}")
            return status_data
        
        time.sleep(POLL_INTERVAL)

def cleanup_old_jobs(max_age_hours=1):
    """Trigger manual cleanup of old jobs."""
    try:
        response = requests.post(f"{API_BASE}/admin/cleanup", params={"max_age_hours": max_age_hours})
        if response.status_code == 200:
            result = response.json()
            print(f"🧹 {result['message']}")
            return True
        else:
            print(f"✗ Cleanup failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Exception during cleanup: {e}")
        return False

def reset_stuck_jobs():
    """Reset jobs that are stuck in running state."""
    try:
        response = requests.post(f"{API_BASE}/admin/reset-stuck")
        if response.status_code == 200:
            result = response.json()
            print(f"🔄 {result['message']}")
            return True
        else:
            print(f"✗ Reset failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Exception during reset: {e}")
        return False

def main():
    """Main function demonstrating API usage."""
    print("🖼️  ComfyUI Worker HTTP API Example Client")
    print("=" * 50)
    
    # Check API health and get initial stats
    print("\n1️⃣  Health Check")
    if not check_api_health():
        print("❌ API server is not available. Please start the server first.")
        return
    
    print("\n2️⃣  System Statistics")
    initial_stats = get_detailed_stats()
    
    # Example workflow - simple text-to-image
    # You should replace this with your actual workflow
    example_workflow = {
        "3": {
            "inputs": {
                "seed": 156680208700286,
                "steps": 20,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        },
        "4": {
            "inputs": {
                "ckpt_name": "flux1-dev.safetensors"
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {
            "inputs": {
                "width": 512,
                "height": 512,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {
            "inputs": {
                "text": "A beautiful landscape with mountains and a lake, photorealistic, high quality",
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "7": {
            "inputs": {
                "text": "text, watermark, low quality, blurry",
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "8": {
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            },
            "class_type": "VAEDecode"
        },
        "9": {
            "inputs": {
                "filename_prefix": "ComfyUI",
                "images": ["8", 0]
            },
            "class_type": "SaveImage"
        }
    }
    
    # Example with workflow file
    workflow_file = "test_input.json"
    if os.path.exists(workflow_file):
        print(f"\n3️⃣  Loading workflow from {workflow_file}")
        try:
            with open(workflow_file, 'r') as f:
                test_data = json.load(f)
                if 'input' in test_data and 'workflow' in test_data['input']:
                    workflow = test_data['input']['workflow']
                    print("✓ Loaded workflow from file")
                else:
                    workflow = example_workflow
                    print("⚠️  Using example workflow (file format not recognized)")
        except Exception as e:
            print(f"✗ Error loading workflow file: {e}")
            workflow = example_workflow
            print("⚠️  Using example workflow")
    else:
        print(f"\n3️⃣  Using example workflow")
        workflow = example_workflow
    
    # Example with input images (optional)
    images = []
    # Uncomment and modify the following if you have input images:
    # if os.path.exists("input_image.png"):
    #     print("📎 Loading input image...")
    #     base64_image = encode_image("input_image.png")
    #     images.append({
    #         "name": "input_image.png",
    #         "image": f"data:image/png;base64,{base64_image}"
    #     })
    #     print("✓ Input image loaded")
    
    # Submit the job
    print("\n4️⃣  Job Submission")
    job_id = submit_job(workflow, images)
    if not job_id:
        print("❌ Failed to submit job")
        return
    
    # Wait for completion
    print("\n5️⃣  Job Processing")
    result = wait_for_completion(job_id)
    if not result:
        print("❌ Job processing failed or timed out")
        return
    
    # Process results
    print("\n6️⃣  Results Processing")
    if result['status'] == 'completed':
        # Save generated images
        images_data = result.get('result', {}).get('images', [])
        if images_data:
            print(f"🖼️  Generated {len(images_data)} image(s)")
            
            # Create output directory
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            
            for i, image_data in enumerate(images_data):
                filename = image_data.get('filename', f'generated_image_{i}.png')
                output_path = output_dir / filename
                
                if image_data.get('type') == 'base64':
                    save_base64_image(image_data['data'], output_path)
                    print(f"💾 Saved image to {output_path}")
                elif image_data.get('type') == 's3_url':
                    print(f"☁️  Image available at S3 URL: {image_data['data']}")
        else:
            print("ℹ️  No images generated")
    else:
        print(f"❌ Job failed: {result.get('error', 'Unknown error')}")
    
    # Show updated statistics
    print("\n7️⃣  Updated Statistics")
    final_stats = get_detailed_stats()
    
    # Optional: Demonstrate admin functions
    print("\n8️⃣  Admin Functions (Optional)")
    
    # Ask user if they want to run admin functions
    try:
        choice = input("Run admin functions? (y/N): ").lower().strip()
        if choice == 'y':
            print("\n🔧 Testing admin functions...")
            
            # Reset any stuck jobs
            print("Resetting stuck jobs...")
            reset_stuck_jobs()
            
            # Cleanup very old jobs (1 hour for demo purposes)
            print("Cleaning up old jobs...")
            cleanup_old_jobs(max_age_hours=1)
            
            # Show final stats
            print("\nFinal statistics after cleanup:")
            get_detailed_stats()
        else:
            print("Skipping admin functions")
    except KeyboardInterrupt:
        print("\nSkipping admin functions")
    
    print("\n✅ Example client completed successfully!")

if __name__ == "__main__":
    main() 