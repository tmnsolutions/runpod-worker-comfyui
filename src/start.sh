#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

# Ensure ComfyUI-Manager runs in offline network mode inside the container
comfy-manager-set-mode offline || echo "worker-comfyui - Could not set ComfyUI-Manager network_mode" >&2

echo "worker-comfyui: Starting ComfyUI"

# Allow operators to tweak verbosity; default is DEBUG.
: "${COMFY_LOG_LEVEL:=DEBUG}"

# Check if we're in HTTP API mode
if [ "$HTTP_API_MODE" == "true" ]; then
    echo "worker-comfyui: Starting in HTTP API mode"
    
    # Start ComfyUI in background
    python -u /comfyui/main.py --disable-auto-launch --disable-metadata --listen --verbose "${COMFY_LOG_LEVEL}" --log-stdout &
    
    # Start the HTTP API handler
    echo "worker-comfyui: Starting HTTP API Handler"
    python -u -m api.handler

# Legacy support for SERVE_API_LOCALLY
elif [ "$SERVE_API_LOCALLY" == "true" ]; then
    echo "worker-comfyui: Starting in legacy API mode"
    
    # Start ComfyUI in background
    python -u /comfyui/main.py --disable-auto-launch --disable-metadata --listen --verbose "${COMFY_LOG_LEVEL}" --log-stdout &

    # Start the legacy handler
    echo "worker-comfyui: Starting RunPod Handler"
    python -u -m api.handler --rp_serve_api --rp_api_host=0.0.0.0 --rp_api_concurrency=20

# Default serverless mode
else
    echo "worker-comfyui: Starting in serverless mode"
    
    # Start ComfyUI in background
    python -u /comfyui/main.py --disable-auto-launch --disable-metadata --verbose "${COMFY_LOG_LEVEL}" --log-stdout &

    # Start the serverless handler
    echo "worker-comfyui: Starting RunPod Handler"
    python -u -m api.handler
fi