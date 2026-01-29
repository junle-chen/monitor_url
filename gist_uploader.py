#!/usr/bin/env python3
"""
Gist Uploader - Aggregates GPU status from all servers and uploads to GitHub Gist.

This script runs on zxcpu1 and reads status.json files from all servers via NFS,
then uploads them to a single GitHub Gist for Streamlit Cloud to access.

Usage:
  python3 gist_uploader.py --gist-id YOUR_GIST_ID --github-token YOUR_TOKEN
"""
import json
import time
import os
import argparse
import requests
from datetime import datetime

# Server configuration
HOSTS = [f"zxcpu{i}" for i in range(1, 6)]
LOCAL_STATUS_FILE = "status.json"
NFS_PATH_TEMPLATE = "/export/{host}/junle/monitor/status.json"


def get_status_file_path(host):
    """Get the path to status.json for a given host."""
    import socket
    current_host = socket.gethostname()
    
    if host == current_host:
        return LOCAL_STATUS_FILE
    else:
        return NFS_PATH_TEMPLATE.format(host=host)


def read_all_status_files():
    """Read status.json from all servers."""
    all_data = {}
    
    for host in HOSTS:
        file_path = get_status_file_path(host)
        try:
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    all_data[host] = json.load(f)
            else:
                all_data[host] = {"error": f"File not found: {file_path}"}
        except Exception as e:
            all_data[host] = {"error": str(e)}
    
    return all_data


def update_gist(gist_id, github_token, all_data):
    """Update all files in the Gist."""
    url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Prepare all files
    files = {}
    for host, data in all_data.items():
        filename = f"{host}.json"
        files[filename] = {"content": json.dumps(data, indent=2)}
    
    payload = {"files": files}
    
    try:
        response = requests.patch(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            return True
        else:
            print(f"Gist update failed: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        print(f"Gist update error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="GPU Status Gist Uploader")
    parser.add_argument("--interval", type=int, default=10, help="Update interval in seconds")
    parser.add_argument("--gist-id", type=str, required=True, help="GitHub Gist ID")
    parser.add_argument("--github-token", type=str, default=None, help="GitHub token")
    args = parser.parse_args()

    # Get token from argument or environment
    github_token = args.github_token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("Error: --github-token or GITHUB_TOKEN env var required")
        return

    print(f"Starting Gist Uploader...")
    print(f"Gist ID: {args.gist_id}")
    print(f"Monitoring hosts: {', '.join(HOSTS)}")
    print(f"Interval: {args.interval}s")

    while True:
        try:
            readable_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Read all status files
            all_data = read_all_status_files()
            
            # Upload to Gist
            success = update_gist(args.gist_id, github_token, all_data)
            
            if success:
                print(f"[{readable_time}] Updated Gist with {len(all_data)} hosts")
            
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
