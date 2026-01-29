import subprocess
import json
import time
import os
import socket
import argparse
from datetime import datetime

def get_nvidia_smi_data():
    data = {}
    
    # [1] GPU Info
    # query: index, uuid, name, memory.used, memory.total, utilization.gpu, temperature.gpu
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
    # query: gpu_uuid, pid, used_memory, process_name
    try:
        cmd = [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory,process_name",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data['proc_csv'] = result.stdout.strip()
            
            # [3] User Info (Dependent on PIDs found)
            # We need to find users for the PIDs
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
                    # ps -o pid=,user= -p dict
                    # Using a simple command to get users for these PIDs
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
        # It's okay if process info fails, we still have GPU info
        data['proc_csv'] = ""
        data['user_txt'] = ""

    return data

def main():
    parser = argparse.ArgumentParser(description="GPU Status Collector")
    parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds")
    parser.add_argument("--output", type=str, default="status.json", help="Output JSON file path")
    args = parser.parse_args()

    # Ensure output directory exists (if path has dirs)
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    print(f"Starting GPU Collector on {socket.gethostname()}...")
    print(f"Saving to {os.path.abspath(args.output)}")
    print(f"Interval: {args.interval}s")

    while True:
        try:
            timestamp = time.time()
            readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            
            gpu_data = get_nvidia_smi_data()
            
            output_data = {
                "hostname": socket.gethostname(),
                "timestamp": timestamp,
                "readable_time": readable_time,
                **gpu_data
            }
            
            # Write to temporary file then atomically rename to avoid read conflicts
            temp_file = args.output + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(output_data, f, indent=2)
            os.replace(temp_file, args.output)
            
            # print(f"[{readable_time}] Updated {args.output}")
            
        except Exception as e:
            print(f"Error in collection loop: {e}")
            
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
