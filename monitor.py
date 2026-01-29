import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
import os
import signal
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

# ================= 配置区域 =================
# 定义要监控的主机列表
HOSTS = [f"zxcpu{i}" for i in range(1, 6)]
# ===========================================

st.set_page_config(
    page_title="CSE GPU Cluster",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded",
)

# ==========================================
# 侧边栏：资源概览
# ==========================================
with st.sidebar:
    st.subheader("📊 Availability")
    status_placeholder = st.empty()
    st.caption("Free = Memory < 500 MiB")

# ==========================================

st.title("⚡ HKUST CSE GPU Monitor")

st.markdown(
    """
<style>
    .stProgress > div > div > div > div { background-color: #00CC96; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
    .small-font { font-size: 0.8em; color: #666; }
    /* 侧边栏表格样式优化 */
    [data-testid="stSidebar"] [data-testid="stDataFrame"] { font-size: 0.9em; }
    /* 增加侧边栏宽度 */
    [data-testid="stSidebar"] {
        min-width: 480px;
        width: 480px;
    }
    /* 主内容区域自适应宽度，确保侧边栏收起后不留白 */
    div[data-testid="block-container"],
    .block-container {
        max-width: 100% !important;
        padding-left: 2rem;
        padding-right: 2rem;
        margin-left: 0 !important;
        margin-right: auto !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

# 强制页面首次加载时展开侧边栏，避免浏览器保存折叠状态
components.html(
    """
    <script>
        const ensureSidebarOpen = () => {
            const doc = window.parent.document;
            const sidebar = doc.querySelector('section[data-testid="stSidebar"]');
            if (!sidebar || sidebar.getAttribute('aria-expanded') === 'true') { return; }
            const toggle = doc.querySelector('[data-testid="collapsedControl"]')
                || doc.querySelector('button[title="Show sidebar"]')
                || doc.querySelector('button[kind="header"]')
                || doc.querySelector('[data-testid="baseButton-header"]');
            if (toggle) { toggle.click(); }
        };
        setTimeout(ensureSidebarOpen, 100);
        setTimeout(ensureSidebarOpen, 1000);
    </script>
    """,
    height=0,
    width=0,
)

def read_gpu_status_file(host):
    """
    Read status.json for the given host.
    Logic:
    - If host is current hostname, read locally: ./status.json
    - Else, read from NFS: /export/<host>/junle/monitor/status.json
    """
    current_host = socket.gethostname()
    host_clean = host.split(".")[0] # handle qualified names if any
    
    # Path construction
    if host == current_host or host == "localhost":
        # Assume usage in the same directory as this script
        file_path = "status.json"
    else:
        # Construct NFS path based on user description
        # /export/zxcpuX/junle/monitor/status.json
        # NOTE: user said /export/zxcpux/junle access works. 
        # I am adding 'monitor' subdir assumption because that's where we are.
        # If user puts it directly in junle, we might need adjustment.
        # Given the previous context, it's safer to check both or assume structure. 
        # I will stick to the 'monitor' subdir as that's where I placed the collector.
        file_path = f"/export/{host_clean}/junle/monitor/status.json"

    try:
        if not os.path.exists(file_path):
            return host, None, None, None, f"File not found: {file_path}"
        
        with open(file_path, "r") as f:
            data = json.load(f)
            
        # Check freshness (e.g., if file is older than 2 minutes, warn?)
        # For now just return data
        
        if "error" in data:
             return host, None, None, None, f"Collector Error: {data['error']}"

        return host, data.get("gpu_csv", ""), data.get("proc_csv", ""), data.get("user_txt", ""), None

    except Exception as e:
        return host, None, None, None, str(e)


def parse_data(gpu_csv, proc_csv, user_txt):
    try:
        gpu_cols = ["idx", "uuid", "name", "mem_used", "mem_total", "util_gpu", "temp"]
        df_gpu = pd.read_csv(
            StringIO(gpu_csv), header=None, names=gpu_cols, skipinitialspace=True
        )
        df_gpu["uuid"] = df_gpu["uuid"].astype(str).str.strip()
    except:
        df_gpu = pd.DataFrame()

    try:
        if not proc_csv:
            df_proc = pd.DataFrame()
        else:
            proc_cols = ["gpu_uuid", "pid", "mem_used", "process_name"]
            df_proc = pd.read_csv(
                StringIO(proc_csv), header=None, names=proc_cols, skipinitialspace=True
            )
            df_proc["process_name"] = df_proc["process_name"].astype(str).str.strip()
            df_proc["gpu_uuid"] = df_proc["gpu_uuid"].astype(str).str.strip()
            df_proc["pid"] = pd.to_numeric(df_proc["pid"], errors="coerce")
            df_proc = df_proc.dropna(subset=["pid"])
            df_proc["pid"] = df_proc["pid"].astype(int)
    except:
        df_proc = pd.DataFrame()

    try:
        if not user_txt:
            df_user = pd.DataFrame(columns=["pid", "user"])
        else:
            df_user = pd.read_csv(
                StringIO(user_txt), sep=r"\s+", names=["pid", "user"], header=None
            )
            df_user["pid"] = pd.to_numeric(df_user["pid"], errors="coerce")
            df_user = df_user.dropna(subset=["pid"])
            df_user["pid"] = df_user["pid"].astype(int)
    except:
        df_user = pd.DataFrame(columns=["pid", "user"])

    if not df_proc.empty:
        if not df_user.empty:
            df_proc = pd.merge(df_proc, df_user, on="pid", how="left")
            df_proc["user"] = df_proc["user"].fillna("Unknown")
        else:
            df_proc["user"] = "Unknown"

        if not df_gpu.empty and "uuid" in df_gpu.columns:
            uuid_map = dict(zip(df_gpu["uuid"], df_gpu["idx"]))
            df_proc["gpu_idx"] = df_proc["gpu_uuid"].map(uuid_map)

    return df_gpu, df_proc


placeholder = st.empty()
time_placeholder = st.empty()

try:
    while True:
        # 准备收集统计数据
        print(f"[{time.strftime('%H:%M:%S')}] Refreshing data...", flush=True)
        stats_list = []

        with placeholder.container():
            # Use simple loop or threadpool (file I/O is fast but network FS might lag)
            with ThreadPoolExecutor(max_workers=len(HOSTS)) as executor:
                results = list(executor.map(read_gpu_status_file, HOSTS))

            cols = st.columns(3) + st.columns(3)

            for i, (host, gpu_raw, proc_raw, user_raw, err) in enumerate(results):
                # 先计算该主机的可用 GPU 数量，用于侧边栏统计
                host_name = host.split(".")[0]
                total_gpu = 0
                free_gpu = 0
                free_gpu_ids = "-"
                used_gpu_info = "-"

                # 数据解析
                df_gpu, df_proc = pd.DataFrame(), pd.DataFrame()
                if not err and gpu_raw:
                    df_gpu, df_proc = parse_data(gpu_raw, proc_raw, user_raw)
                    total_gpu = len(df_gpu)
                    # 计算 Free: 显存 < 500 MiB 视为 Free
                    if not df_gpu.empty:
                        free_df = df_gpu[df_gpu["mem_used"] < 500]
                        free_gpu = len(free_df)
                        if not free_df.empty:
                            # 记录空闲 GPU 的 ID 列表，例如 "GPU 0, 1, 3"
                            try:
                                ids = [str(int(idx)) for idx in free_df["idx"]]
                            except Exception:
                                ids = [str(idx) for idx in free_df["idx"]]
                            if ids:
                                free_gpu_ids = "GPU " + ", ".join(ids)
                        # 计算非 Free GPU 的显存使用情况，多行显示
                        used_df = df_gpu[df_gpu["mem_used"] >= 500]
                        if not used_df.empty:
                            lines = []
                            for _, row in used_df.iterrows():
                                try:
                                    gpu_idx = int(row["idx"])
                                    mem_used_mb = float(row["mem_used"])
                                    mem_total_mb = float(row["mem_total"])
                                except Exception:
                                    continue
                                mem_used_g = (
                                    mem_used_mb / 1024.0 if mem_total_mb > 0 else 0
                                )
                                mem_total_g = (
                                    mem_total_mb / 1024.0 if mem_total_mb > 0 else 0
                                )
                                line = f"GPU {gpu_idx}: {int(mem_used_g)}G / {int(mem_total_g)}G"
                                lines.append(line)
                            if lines:
                                used_gpu_info = "\n".join(lines)

                # 存入统计列表
                stats_list.append(
                    {
                        "Server": host_name,
                        "Free": f"{free_gpu} / {total_gpu}",
                        "Free GPUs": free_gpu_ids,
                        "Used GPUs": used_gpu_info,
                        "Status": (
                            "🔴 Down"
                            if err
                            else ("🟢 OK" if free_gpu > 0 else "🟡 Full")
                        ),
                    }
                )

                # --- 下面是主界面的渲染逻辑 ---
                if i >= len(cols):
                    continue
                with cols[i]:
                    st.subheader(f"🖥️ {host_name}")
                    # 折叠区域：GPU 详细信息
                    with st.expander("GPU 详情", expanded=False):
                        if err:
                            st.error(err)
                        elif not df_gpu.empty:
                            for _, row in df_gpu.iterrows():
                                try:
                                    gpu_idx = int(row["idx"])
                                    mem_used = float(row["mem_used"])
                                    mem_total = float(row["mem_total"])
                                    util = float(row["util_gpu"])
                                    temp = int(row["temp"])
                                except:
                                    continue

                                ratio = mem_used / mem_total if mem_total > 0 else 0
                                gpu_name = (
                                    str(row["name"])
                                    .replace("NVIDIA ", "")
                                    .replace("GeForce ", "")
                                    .replace("RTX ", "")
                                )

                                with st.container(border=True):
                                    c1, c2 = st.columns([7, 3])
                                    c1.write(f"**GPU {gpu_idx}**: {gpu_name}")
                                    color = "red" if temp > 80 else "grey"
                                    c2.markdown(f":{color}[{temp}°C]")

                                    st.progress(
                                        ratio,
                                        text=f"RAM: {int(mem_used)} / {int(mem_total)} MB",
                                    )
                                    st.metric(
                                        "Utility",
                                        f"{int(util)}%",
                                        label_visibility="collapsed",
                                    )

                                    if (
                                        not df_proc.empty
                                        and "gpu_idx" in df_proc.columns
                                    ):
                                        my_procs = df_proc[
                                            df_proc["gpu_idx"] == gpu_idx
                                        ].copy()
                                        if not my_procs.empty:
                                            my_procs["process_name"] = my_procs[
                                                "process_name"
                                            ].apply(
                                                lambda x: (
                                                    x.split("/")[-1] if "/" in x else x
                                                )
                                            )
                                            display_df = my_procs[
                                                [
                                                    "user",
                                                    "pid",
                                                    "mem_used",
                                                    "process_name",
                                                ]
                                            ]
                                            display_df.columns = [
                                                "User",
                                                "PID",
                                                "Mem",
                                                "Proc",
                                            ]
                                            st.dataframe(
                                                display_df,
                                                hide_index=True,
                                                use_container_width=True,
                                            )
                                        else:
                                            st.caption("No active processes")
                                    else:
                                        st.caption("Idle")
                        else:
                            st.warning("No GPU Info")

        # 循环结束后，统一更新侧边栏状态
        with status_placeholder.container():
            if stats_list:
                # 使用 Markdown 表格手动渲染，使 Used GPUs 列可以通过 <br> 多行显示
                headers = ["Server", "Free", "Free GPUs", "Used GPUs", "Status"]
                md_lines = [
                    "| " + " | ".join(headers) + " |",
                    "|" + " | ".join(["---"] * len(headers)) + "|",
                ]
                for row in stats_list:
                    server = row.get("Server", "")
                    free = row.get("Free", "")
                    free_gpus = row.get("Free GPUs", "")
                    used_gpus_raw = row.get("Used GPUs", "-") or "-"
                    # 将 \n 换成 <br>，在单元格内真正换行
                    used_gpus = used_gpus_raw.replace("\n", "<br>")
                    status = row.get("Status", "")
                    md_lines.append(
                        f"| {server} | {free} | {free_gpus} | {used_gpus} | {status} |"
                    )
                st.markdown("\n".join(md_lines), unsafe_allow_html=True)

        time_placeholder.caption(f"Last updated: {time.strftime('%H:%M:%S')}")
        time.sleep(15) # Refresh every 15 seconds to match collector default
except Exception:
    pass

finally:
    # 只要脚本停止运行（包括关闭网页、刷新网页），就杀死进程
    print("Browser closed or refreshed. Killing process...")
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except:
        pass
