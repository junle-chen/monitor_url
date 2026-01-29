#!/usr/bin/env python3
"""
GPU Status Collector with GitHub Gist Support

Usage:
  # Local mode (original behavior):
  python3 gpu_collector.py

  # Gist mode (for Streamlit Cloud deployment):
  python3 gpu_collector.py --gist-id YOUR_GIST_ID --github-token YOUR_TOKEN
"""
import subprocess
import json
import time
import os
import socket
import argparse
from datetime import datetime

# Optional: requests for Gist upload
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_nvidia_smi_data():
    data = {}
    
    # [1] GPU Info
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data['gpu_csv'] = result.stdout.strip()
        else:
            data['error'] = f"nvidia-smi failed: {result.stderr}"
    except Exception as e:
        data['error'] = str(e)
        return data

    # [2] Process Info
    try:
        cmd = [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory,process_name",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data['proc_csv'] = result.stdout.strip()
            
            if data['proc_csv']:
                pids = []
                for line in data['proc_csv'].split('\n'):
                    parts = line.split(',')
                    if len(parts) >= 2:
                        try:
                            pids.append(parts[1].strip())
                        except:
                            pass
                
                if pids:
                    pid_str = ','.join(pids)
                    ps_cmd = ["ps", "-o", "pid=,user=", "-p", pid_str]
                    ps_res = subprocess.run(ps_cmd, capture_output=True, text=True)
                    if ps_res.returncode == 0:
                        data['user_txt'] = ps_res.stdout.strip()
                    else:
                        data['user_txt'] = ""
                else:
                    data['user_txt'] = ""
            else:
                data['user_txt'] = ""
        else:
            data['proc_csv'] = ""
            data['user_txt'] = ""
    except Exception as e:
        data['proc_csv'] = ""
        data['user_txt'] = ""

    return data


def update_gist(gist_id, github_token, hostname, data_json):
    """Update a specific file in a GitHub Gist."""
    if not HAS_REQUESTS:
        print("Error: 'requests' module not installed. Run: pip install requests")
        return False
    
    url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    filename = f"{hostname}.json"
    payload = {
        "files": {
            filename: {
                "content": data_json
            }
        }
    }
    
    try:
        response = requests.patch(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"Gist update failed: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        print(f"Gist update error: {e}")
        return False


def create_gist(github_token, hostname, data_json):
    """Create a new Gist and return its ID."""
    if not HAS_REQUESTS:
        print("Error: 'requests' module not installed. Run: pip install requests")
        return None
    
    url = "https://api.github.com/gists"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    payload = {
        "description": "GPU Monitor Status Data",
        "public": True,
        "files": {
            f"{hostname}.json": {
                "content": data_json
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 201:
            gist_id = response.json()["id"]
            print(f"Created new Gist: https://gist.github.com/{gist_id}")
            return gist_id
        else:
            print(f"Gist creation failed: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        print(f"Gist creation error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="GPU Status Collector")
    parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds")
    parser.add_argument("--output", type=str, default="status.json", help="Output JSON file path (local mode)")
    parser.add_argument("--gist-id", type=str, default=None, help="GitHub Gist ID for cloud mode")
    parser.add_argument("--github-token", type=str, default=None, help="GitHub token for Gist API")
    parser.add_argument("--create-gist", action="store_true", help="Create a new Gist (requires --github-token)")
    args = parser.parse_args()

    hostname = socket.gethostname()
    
    # Determine mode
    use_gist = args.gist_id is not None or args.create_gist
    
    if use_gist and not args.github_token:
        # Try environment variable
        args.github_token = os.environ.get("GITHUB_TOKEN")
        if not args.github_token:
            print("Error: --github-token or GITHUB_TOKEN env var required for Gist mode")
            return
    
    if args.create_gist and not args.gist_id:
        # Create initial gist
        initial_data = json.dumps({"hostname": hostname, "status": "initializing"}, indent=2)
        args.gist_id = create_gist(args.github_token, hostname, initial_data)
        if not args.gist_id:
            print("Failed to create Gist. Exiting.")
            return
        print(f"Use this Gist ID for other collectors: {args.gist_id}")

    # Ensure output directory exists (local mode)
    if not use_gist:
        out_dir = os.path.dirname(args.output)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

    mode_str = f"Gist mode (ID: {args.gist_id})" if use_gist else f"Local mode ({os.path.abspath(args.output)})"
    print(f"Starting GPU Collector on {hostname}...")
    print(f"Mode: {mode_str}")
    print(f"Interval: {args.interval}s")

    while True:
        try:
            timestamp = time.time()
            readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            
            gpu_data = get_nvidia_smi_data()
            
            output_data = {
                "hostname": hostname,
                "timestamp": timestamp,
                "readable_time": readable_time,
                **gpu_data
            }
            
            data_json = json.dumps(output_data, indent=2)
            
            if use_gist:
                # Upload to Gist
                success = update_gist(args.gist_id, args.github_token, hostname, data_json)
                if success:
                    print(f"[{readable_time}] Updated Gist")
            else:
                # Write to local file
                temp_file = args.output + ".tmp"
                with open(temp_file, "w") as f:
                    f.write(data_json)
                os.replace(temp_file, args.output)
            
        except Exception as e:
            print(f"Error in collection loop: {e}")
            
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
