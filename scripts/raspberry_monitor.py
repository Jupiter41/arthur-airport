"""Pi host metrics collector and SSH dashboard. Python standard library only.

Pi: raspberry_monitor.py collect (systemd timer, once per minute)
PC: raspberry_dashboard.py [--remote arthur@arthurrasp.local] [--hours 24]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser

REMOTE_SCRIPT = "/opt/arthur-airport/scripts/raspberry_monitor.py"
DEFAULT_DB = "/opt/arthur-airport/metrics/metrics.sqlite3"
MIB = 1024**2
GIB = 1024**3
THRESHOLDS = {
    "temperature_c": {"warning": 70, "danger": 80, "direction": "high", "unit": "°C"},
    "cpu_percent": {"warning": 85, "danger": 95, "direction": "high", "unit": "%"},
    "mem_available_mib": {"warning": 750, "danger": 450, "direction": "low", "unit": "MiB"},
    "disk_free_gib": {"warning": 10, "danger": 5, "direction": "low", "unit": "GiB"},
    "disk_used_percent": {"warning": 80, "danger": 90, "direction": "high", "unit": "%"},
    "swap_used_mib": {"warning": 512, "danger": 1024, "direction": "high", "unit": "MiB"},
    "load_per_core": {"warning": 1, "danger": 1.5, "direction": "high", "unit": "load/core"},
}


def run(command: list[str], timeout: float = 10) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def zone(key: str, value: float | None) -> str:
    if value is None:
        return "unknown"
    rule = THRESHOLDS[key]
    for status in ("danger", "warning"):
        if (value <= rule[status] if rule["direction"] == "low" else value >= rule[status]):
            return status
    return "normal"


def analyse(sample: dict, previous: dict | None = None) -> dict:
    zones = {key: zone(key, sample.get(key)) for key in THRESHOLDS}
    advice = []
    if zones["temperature_c"] in ("warning", "danger"):
        advice.append("Temperature is elevated: check airflow/fan and reduce sustained work.")
    if zones["mem_available_mib"] in ("warning", "danger"):
        advice.append("RAM headroom is low: reduce simulation demand and inspect the largest containers.")
    if zones["disk_free_gib"] in ("warning", "danger") or zones["disk_used_percent"] != "normal":
        advice.append("Disk is filling: inspect logs and data volumes; back up before removing data.")
    if zones["cpu_percent"] in ("warning", "danger") or zones["load_per_core"] in ("warning", "danger"):
        advice.append("CPU demand is high: check container CPU and I/O wait; avoid concurrent builds/training.")
    flags = sample.get("throttled_flags")
    current_flags = flags & 0xF if isinstance(flags, int) else None
    if current_flags:
        zones["firmware"] = "danger"
        advice.append("Firmware reports a current voltage/clock/thermal limit. Check power supply and cooling.")
    else:
        zones["firmware"] = "normal" if flags is not None else "unknown"
    if flags and flags & 0xF0000:
        advice.append("Firmware records a past voltage/thermal limit since boot; current flags are shown separately.")
    containers = sample.get("containers", [])
    unhealthy = [c["name"] for c in containers if "unhealthy" in c.get("status", "").lower()
                 or c.get("state") == "restarting"
                 or (c["name"].startswith("arthur-airport-pi-")
                     and "kafka-init" not in c["name"]
                     and c.get("state") in {"exited", "dead", "created"})]
    paused = [c["name"] for c in containers if c.get("state") == "paused"]
    zones["containers"] = ("danger" if unhealthy else "warning" if paused else
                           "normal" if sample.get("docker_available") else "unknown")
    if unhealthy:
        advice.append("Unhealthy or unexpectedly stopped containers: " + ", ".join(unhealthy))
    if paused:
        advice.append("Paused containers: inspect the airport resource guard before resuming: " + ", ".join(paused))
    if not sample.get("docker_available"):
        advice.append("Docker health readings are unavailable; container health could not be verified this minute.")
    if previous:
        elapsed = sample["ts"] - previous["ts"]
        if 0 < elapsed <= 180 and sample.get("temperature_c") is not None and previous.get("temperature_c") is not None:
            rate = (sample["temperature_c"] - previous["temperature_c"]) * 60 / elapsed
            if rate > 2:
                advice.append(f"Temperature rose {rate:.1f} °C/min over the last sample; watch the trend.")
    overall = "danger" if "danger" in zones.values() else "warning" if "warning" in zones.values() else "normal"
    if not advice:
        advice.append("Measured host resources are within the configured operating zones.")
    return {"overall": overall, "zones": zones, "recommendations": advice}


def connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    return db


def collect(db_path: str) -> dict:
    with connect(db_path) as db:
        row = db.execute("SELECT payload FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
        previous = json.loads(row[0]) if row else None
        now = int(time.time())
        mem = {key: int(value.split()[0]) * 1024 for key, value in
               (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}
        cpu = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        total_cpu, idle_cpu, io_cpu = sum(cpu), cpu[3] + cpu[4], cpu[4]
        cpu_percent = iowait_percent = None
        if previous and "_cpu_total" in previous:
            total_delta = total_cpu - previous["_cpu_total"]
            idle_delta = idle_cpu - previous["_cpu_idle"]
            io_delta = io_cpu - previous["_cpu_iowait"]
            if total_delta > 0 and 0 <= idle_delta <= total_delta:
                cpu_percent = round((1 - idle_delta / total_delta) * 100, 1)
                iowait_percent = round(max(0, io_delta) / total_delta * 100, 1)
        temperature = None
        vc_temp = run(["vcgencmd", "measure_temp"], 2)
        match = re.search(r"=(-?[\d.]+)", vc_temp or "")
        if match:
            temperature = float(match.group(1))
        else:
            thermal = Path("/sys/class/thermal/thermal_zone0/temp")
            if thermal.exists():
                temperature = int(thermal.read_text()) / 1000
        flags_text = run(["vcgencmd", "get_throttled"], 2)
        flags = int(flags_text.split("=", 1)[1], 16) if flags_text and "=" in flags_text else None
        disk = shutil.disk_usage("/")
        cores = os.cpu_count() or 1
        load = os.getloadavg()
        frequency_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
        net_rx = net_tx = 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip().startswith(("eth", "wlan", "en", "wl")):
                parts = data.split(); net_rx += int(parts[0]); net_tx += int(parts[8])
        elapsed = now - previous["ts"] if previous else 0
        def net_rate(key: str, value: int):
            if previous and elapsed > 0 and value >= previous.get(key, value):
                return round((value - previous.get(key, value)) / elapsed / 1024, 1)
            return None
        ps = run(["docker", "ps", "--all", "--format", "{{json .}}"], 5)
        stats = run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], 8)
        stats_by_name = {r["Name"]: r for r in (json.loads(line) for line in (stats or "").splitlines())}
        containers = []
        for raw in (ps or "").splitlines():
            item = json.loads(raw); name = item["Names"]; stat = stats_by_name.get(name, {})
            containers.append({"name": name, "state": item.get("State"), "status": item.get("Status", ""),
                               "cpu": stat.get("CPUPerc"), "memory": stat.get("MemUsage"),
                               "memory_percent": stat.get("MemPerc"), "pids": stat.get("PIDs")})
        sample = {"ts": now, "host": socket.gethostname(), "cores": cores,
                  "temperature_c": temperature, "cpu_percent": cpu_percent, "iowait_percent": iowait_percent,
                  "load1": load[0], "load5": load[1], "load15": load[2], "load_per_core": round(load[0] / cores, 2),
                  "mem_available_mib": round(mem["MemAvailable"] / MIB, 1), "mem_total_mib": round(mem["MemTotal"] / MIB, 1),
                  "swap_used_mib": round((mem["SwapTotal"] - mem["SwapFree"]) / MIB, 1),
                  "disk_free_gib": round(disk.free / GIB, 2), "disk_total_gib": round(disk.total / GIB, 2),
                  "disk_used_percent": round(disk.used / disk.total * 100, 1),
                  "frequency_mhz": int(frequency_path.read_text()) / 1000 if frequency_path.exists() else None,
                  "uptime_seconds": float(Path("/proc/uptime").read_text().split()[0]),
                  "throttled_flags": flags, "network_rx_kib_s": net_rate("_net_rx", net_rx),
                  "network_tx_kib_s": net_rate("_net_tx", net_tx), "docker_available": ps is not None,
                  "containers": containers, "_cpu_total": total_cpu, "_cpu_idle": idle_cpu,
                  "_cpu_iowait": io_cpu, "_net_rx": net_rx, "_net_tx": net_tx}
        sample["analysis"] = analyse(sample, previous)
        db.execute("INSERT OR REPLACE INTO samples VALUES (?,?)", (now, json.dumps(sample, separators=(",", ":"))))
        db.execute("DELETE FROM samples WHERE ts < ?", (now - 7 * 86400,))
    return sample


def export(db_path: str, hours: float) -> dict:
    if not Path(db_path).exists():
        raise RuntimeError("Metrics database is not present; run the collector first")
    with sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=10) as db:
        rows = db.execute("SELECT payload FROM samples WHERE ts >= ? ORDER BY ts", (time.time() - hours * 3600,)).fetchall()
    samples = [json.loads(row[0]) for row in rows]
    if not samples:
        raise RuntimeError("No samples in the selected period")
    latest = {k: v for k, v in samples[-1].items() if not k.startswith("_")}
    keys = [*THRESHOLDS, "ts", "load1", "iowait_percent", "network_rx_kib_s", "network_tx_kib_s"]
    history = [{k: sample.get(k) for k in keys} for sample in samples]
    summary = {}
    for key in THRESHOLDS:
        values = [s[key] for s in samples if s.get(key) is not None]
        if values:
            summary[key] = {"min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 2),
                            "danger_samples": sum(zone(key, v) == "danger" for v in values)}
    return {"latest": latest, "history": history, "summary": summary,
            "thresholds": THRESHOLDS, "generated_at": int(time.time()), "sample_interval_seconds": 60}


# Filled below; the UI contains no third-party libraries or external requests.
PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raspberry · Health Observatory</title>
<style>
:root{color-scheme:dark;--bg:#0a101b;--panel:#111d2c;--ink:#edf4fd;--muted:#9db0c6;--line:#26374b;--cyan:#58d5ed;--green:#71e3b0;--amber:#ffcb71;--red:#ff8693}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px system-ui,sans-serif}main{max-width:1440px;margin:auto;padding:30px}header{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:28px}h1{font-size:29px;margin:5px 0 7px;letter-spacing:-.7px}h2{font-size:17px;font-weight:600;margin:0 0 16px}p{line-height:1.6;margin:8px 0}.eyebrow{color:var(--cyan);font-size:12px;letter-spacing:2px;text-transform:uppercase}.muted{color:var(--muted)}.badge{display:inline-flex;gap:8px;align-items:center;border-radius:40px;padding:7px 12px;background:#243247;font-size:12px;white-space:nowrap}.badge.normal{color:var(--green);background:#11382f}.badge.warning{color:var(--amber);background:#41331d}.badge.danger{color:var(--red);background:#44232e}.badge.unknown{color:var(--muted)}.badge:before{content:'●';font-size:10px}.grid{display:grid;gap:16px}.kpis{grid-template-columns:repeat(4,1fr)}.card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:21px}.value{font-size:34px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-1px;margin:13px 0 8px}.value small{font-size:15px;color:var(--muted);font-weight:400;letter-spacing:0}.card-top{display:flex;align-items:center;justify-content:space-between;gap:10px}.card-label{color:var(--muted);font-size:13px}.bands{height:6px;border-radius:4px;margin:15px 0 7px;background:linear-gradient(to right,#71e3b0 0% 60%,#ffcb71 60% 80%,#ff8693 80%);position:relative}.bands i{position:absolute;top:-4px;height:14px;width:3px;background:var(--ink);border-radius:2px}.subline{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}.charts{grid-template-columns:repeat(2,1fr);margin-top:17px}.chart{width:100%;height:190px;overflow:visible}.chart text{fill:var(--muted);font:11px system-ui,sans-serif}.chart .gridline{stroke:var(--line);stroke-width:1}.chart .series{stroke:var(--cyan);stroke-width:2;fill:none;stroke-linejoin:round;stroke-linecap:round}.chart .warning{fill:#ffcb710b}.chart .danger{fill:#ff869312}.chart .threshold{stroke:#ff869370;stroke-width:1;stroke-dasharray:4 5}.chart-meta{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted)}.toolbar{display:flex;align-items:center;justify-content:space-between;margin:28px 0 12px;gap:15px}.toolbar h2{margin:0}select,button{font:inherit;font-size:13px;color:var(--ink);border:1px solid var(--line);background:var(--panel);padding:8px 12px;border-radius:8px;cursor:pointer}.bottom{grid-template-columns:1fr 2fr;margin-top:17px}.advice{list-style:none;padding:0;margin:0}.advice li{padding:12px 0;border-top:1px solid var(--line);font-size:13px;line-height:1.6}.advice li:first-child{border:0;padding-top:0}.details{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:17px}.detail b{display:block;margin:5px 0 0;font-variant-numeric:tabular-nums;font-size:18px;font-weight:500}.error{display:none;border:1px solid #ff869370;background:#44232e;padding:15px;border-radius:12px;margin-bottom:18px;white-space:pre-wrap;font-size:13px}.table-wrap{overflow:auto;max-height:420px}table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}th{color:var(--muted);text-align:left;font-weight:500;position:sticky;top:0;background:var(--panel)}td,th{padding:10px 8px;border-bottom:1px solid var(--line)}td:first-child{max-width:300px;overflow:hidden;text-overflow:ellipsis}td .badge{padding:4px 8px;font-size:11px}footer{margin-top:24px;color:var(--muted);font-size:12px;line-height:1.8}.loading{margin:40px 0;color:var(--muted)}a{color:var(--cyan)}@media(max-width:1000px){.kpis{grid-template-columns:repeat(2,1fr)}.bottom{grid-template-columns:1fr}.details{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){main{padding:18px}.charts{grid-template-columns:1fr}.kpis{gap:10px}.card{padding:16px}.value{font-size:28px}header{align-items:flex-start;flex-direction:column}.details{grid-template-columns:repeat(2,1fr)}.chart-meta{flex-wrap:wrap}}
</style></head><body><main>
<header><div><div class="eyebrow">Raspberry health observatory</div><h1 id="title">Your Pi, in perspective.</h1><div class="muted" id="freshness">Connecting securely over SSH…</div></div><div class="badge unknown" id="overall">Waiting for data</div></header>
<div id="error" class="error" role="alert"></div><div id="loading" class="loading">Fetching recorded metrics from the Raspberry. The dashboard opens no public port on the Pi.</div>
<section id="content" hidden><div class="grid kpis" id="kpis"></div>
<div class="toolbar"><h2>Operating history</h2><div><select id="period" aria-label="Displayed history"><option value="1">Last hour</option><option value="6">Last 6 hours</option><option value="24" selected>Last 24 hours</option><option value="168">Last 7 days</option></select> <button id="export">Export JSON</button></div></div>
<div class="grid charts" id="charts"></div><div class="grid details card" id="details"></div>
<div class="grid bottom"><section class="card"><h2>What needs attention</h2><ul class="advice" id="advice"></ul></section><section class="card"><div class="card-top"><h2>Container health</h2><span class="muted" id="container-count"></span></div><div class="table-wrap"><table><thead><tr><th>Container</th><th>State</th><th>CPU / core</th><th>RAM / limit</th><th>RAM %</th></tr></thead><tbody id="containers"></tbody></table></div></section></div>
<footer>Collected every minute · SSH refresh every 30 seconds · History retained for 7 days · Amber = warning, red = danger. Thresholds are conservative operating targets; no automated restart or cleanup is performed by this monitor. Missing readings are shown as unavailable. <a href="https://www.raspberrypi.com/documentation/computers/raspberry-pi.html" target="_blank" rel="noreferrer">Temperature reference</a></footer></section>
</main><script>
let snapshot=null;
const $=id=>document.getElementById(id), colors={normal:'Within range',warning:'Warning',danger:'Danger',unknown:'Unavailable'};
const fmt=(v,d=1)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const labels={temperature_c:'Temperature',cpu_percent:'CPU use',mem_available_mib:'Available RAM',disk_free_gib:'Free disk',load_per_core:'Load per core',swap_used_mib:'Swap used'};
function badge(status){const node=document.createElement('span');node.className='badge '+status;node.textContent=colors[status]||status;return node;}
function kpi(key,value,unit,rule,status,max){const el=document.createElement('article');el.className='card';const top=document.createElement('div');top.className='card-top';const label=document.createElement('span');label.className='card-label';label.textContent=labels[key];top.append(label,badge(status));el.append(top);const number=document.createElement('div');number.className='value';number.textContent=fmt(value,key==='mem_available_mib'?0:1)+' ';const u=document.createElement('small');u.textContent=unit;number.append(u);el.append(number);const track=document.createElement('div');track.className='bands';if(rule.direction==='low')track.style.background='linear-gradient(to right,#ff8693 0% '+rule.danger/max*100+'%,#ffcb71 '+rule.danger/max*100+'% '+rule.warning/max*100+'%,#71e3b0 '+rule.warning/max*100+'%)';else track.style.background='linear-gradient(to right,#71e3b0 0% '+rule.warning/max*100+'%,#ffcb71 '+rule.warning/max*100+'% '+rule.danger/max*100+'%,#ff8693 '+rule.danger/max*100+'%)';if(value!=null){const point=document.createElement('i');point.style.left=Math.max(0,Math.min(100,value/max*100))+'%';track.append(point);}el.append(track);const limits=document.createElement('div');limits.className='subline';limits.textContent=(rule.direction==='low'?'Below ':'Above ')+rule.warning+' '+unit+' warning · '+rule.danger+' '+unit+' danger';el.append(limits);return el;}
function chart(key,rows,rule){const el=document.createElement('section');el.className='card';const h=document.createElement('h2');h.textContent=labels[key];el.append(h);const points=rows.filter(r=>r[key]!=null),W=620,H=190,L=48,R=15,T=12,B=30;let max=Math.max(rule.danger*1.2,...points.map(r=>r[key]*1.1));if(key==='mem_available_mib')max=Math.max(max,snapshot.latest.mem_total_mib);if(key==='cpu_percent')max=100;const minX=rows.length?rows[0].ts:0,maxX=rows.length?rows[rows.length-1].ts:minX+1;const x=v=>L+(v-minX)/(maxX-minX||1)*(W-L-R),y=v=>T+(1-v/max)*(H-T-B);let svg=`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${labels[key]} history with warning and danger zones">`;const band=(lo,hi,c)=>`<rect class="${c}" x="${L}" y="${y(hi)}" width="${W-L-R}" height="${y(lo)-y(hi)}"/>`;svg+=rule.direction==='low'?band(0,rule.danger,'danger')+band(rule.danger,rule.warning,'warning'):band(rule.danger,max,'danger')+band(rule.warning,rule.danger,'warning');for(let i=0;i<=4;i++){let v=max*i/4;svg+=`<line class="gridline" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-8}" y="${y(v)+4}" text-anchor="end">${fmt(v,0)}</text>`;}svg+=`<line class="threshold" x1="${L}" x2="${W-R}" y1="${y(rule.danger)}" y2="${y(rule.danger)}"/>`;let path='',prev=null;for(const p of points){path+=(prev&&p.ts-prev.ts<180?' L':' M')+x(p.ts).toFixed(2)+','+y(p[key]).toFixed(2);prev=p;}svg+=`<path class="series" d="${path}"/>`;for(let i=0;i<3;i++){const t=minX+(maxX-minX)*i/2;svg+=`<text x="${x(t)}" y="${H-5}" text-anchor="${i===0?'start':i===2?'end':'middle'}">${new Date(t*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</text>`;}svg+='</svg>';el.insertAdjacentHTML('beforeend',svg);const meta=document.createElement('div');meta.className='chart-meta';const vals=points.map(p=>p[key]),danger=vals.filter(v=>rule.direction==='low'?v<=rule.danger:v>=rule.danger).length;meta.textContent=vals.length?`Min ${fmt(Math.min(...vals))} · Max ${fmt(Math.max(...vals))} ${rule.unit} · ${danger} danger samples · ${vals.length} readings`:'Not enough measurements yet';el.append(meta);return el;}
function render(){if(!snapshot)return;const d=snapshot,s=d.latest,z=s.analysis.zones;const age=Math.floor(Date.now()/1000-s.ts);$('title').textContent=s.host+' · health at a glance';$('freshness').textContent='Sample '+new Date(s.ts*1000).toLocaleString()+' · '+age+'s ago · '+d.history.length+' recorded readings';const status=age>180?'danger':s.analysis.overall;$('overall').className='badge '+status;$('overall').textContent=age>180?'Metrics are stale':colors[status];$('loading').hidden=true;$('content').hidden=false;$('kpis').replaceChildren(...[['temperature_c',s.temperature_c,'°C',100],['cpu_percent',s.cpu_percent,'%',100],['mem_available_mib',s.mem_available_mib,'MiB',s.mem_total_mib],['disk_free_gib',s.disk_free_gib,'GiB',s.disk_total_gib]].map(([key,value,unit,max])=>kpi(key,value,unit,d.thresholds[key],z[key],max)));const cutoff=Date.now()/1000-Number($('period').value)*3600,rows=d.history.filter(r=>r.ts>=cutoff);$('charts').replaceChildren(...['temperature_c','cpu_percent','mem_available_mib','load_per_core'].map(key=>chart(key,rows,d.thresholds[key])));const flags=s.throttled_flags;$('details').replaceChildren(...[['Clock',fmt(s.frequency_mhz,0)+' MHz'],['Swap in use',fmt(s.swap_used_mib,0)+' MiB'],['Load 1 / 5 / 15',s.load1.toFixed(2)+' / '+s.load5.toFixed(2)+' / '+s.load15.toFixed(2)],['Network RX / TX',fmt(s.network_rx_kib_s)+' / '+fmt(s.network_tx_kib_s)+' KiB/s'],['Firmware flags',flags==null?'Unavailable':'0x'+flags.toString(16)+' · '+(flags&15?'current limit':'no current limit')],['Uptime',fmt(s.uptime_seconds/3600)+' hours']].map(([label,value])=>{const el=document.createElement('div');el.className='detail';const l=document.createElement('span');l.className='muted';l.textContent=label;const v=document.createElement('b');v.textContent=value;el.append(l,v);return el;}));$('advice').replaceChildren(...s.analysis.recommendations.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));$('container-count').textContent=s.containers.length+' containers';$('containers').replaceChildren(...s.containers.sort((a,b)=>a.name.localeCompare(b.name)).map(c=>{const tr=document.createElement('tr');for(const [i,value] of [c.name,c.status,c.cpu||'—',c.memory||'—',c.memory_percent||'—'].entries()){const td=document.createElement('td');if(i===1){const status=/unhealthy|restarting/i.test(value)?'danger':/paused|starting/i.test(value)?'warning':c.state==='running'?'normal':'unknown';const b=badge(status);b.textContent=value;td.append(b);}else td.textContent=value;tr.append(td);}return tr;}));}
async function refresh(){try{const response=await fetch('/api/metrics');const result=await response.json();if(result.data)snapshot=result.data;$('error').style.display=result.error?'block':'none';$('error').textContent=result.error?'SSH connection issue: '+result.error+'\nRetaining the last available readings.':'';render();}catch(e){$('error').style.display='block';$('error').textContent='Local dashboard connection lost. Keep the Python script running.';}}
$('period').onchange=render;$('export').onclick=()=>{if(!snapshot)return;const blob=new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='raspberry-metrics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};refresh();setInterval(refresh,10000);
</script></body></html>'''


def fetch_remote(remote: str, hours: float) -> dict:
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote,
                             "python3", REMOTE_SCRIPT, "export", "--hours", str(hours)],
                            capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "SSH metrics export failed")
    return json.loads(result.stdout)


def serve(remote: str, hours: float, port: int, open_browser: bool) -> None:
    shared: dict = {"data": None, "error": "Connecting to the Raspberry…", "fetched_at": None}
    lock = threading.Lock()
    stop = threading.Event()
    def refresh():
        while not stop.is_set():
            try:
                data = fetch_remote(remote, hours)
                with lock: shared.update(data=data, error=None, fetched_at=int(time.time()))
            except Exception as exc:
                with lock: shared["error"] = str(exc)
            stop.wait(30)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host", "") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.send_error(403); return
            if self.path == "/":
                content, mime = PAGE.encode(), "text/html; charset=utf-8"
            elif self.path == "/api/metrics":
                with lock: content = json.dumps(shared, ensure_ascii=False).encode()
                mime = "application/json"
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(content)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=refresh, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    print(f"Raspberry dashboard: {url}\nSSH target: {remote}\nPress Ctrl+C to stop.", flush=True)
    if open_browser: webbrowser.open(url)
    try: server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt: pass
    finally: stop.set(); server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["collect", "export", "serve"], default="serve")
    parser.add_argument("--remote", default="arthur@arthurrasp.local")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--once", action="store_true", help="Fetch and print one remote metrics export")
    args = parser.parse_args()
    if not 0 < args.hours <= 168: parser.error("hours must be between 0 and 168")
    if not 1024 <= args.port <= 65535: parser.error("port must be between 1024 and 65535")
    if not re.fullmatch(r"[\w.-]+@[\w.:-]+", args.remote): parser.error("remote must be user@hostname")
    if args.mode == "collect":
        sample = collect(args.db)
        print(json.dumps({"ts": sample["ts"], "analysis": sample["analysis"]}, ensure_ascii=False))
    elif args.mode == "export": print(json.dumps(export(args.db, args.hours), separators=(",", ":")))
    elif args.once: print(json.dumps(fetch_remote(args.remote, args.hours), indent=2))
    else: serve(args.remote, args.hours, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
