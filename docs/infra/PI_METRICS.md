# Raspberry metrics job and local dashboard

The host runs `raspberry_monitor.py collect` once per minute via a systemd timer.
It stores seven days in `/opt/arthur-airport/metrics/metrics.sqlite3`. SQLite WAL
allows the collector and SSH exports to run concurrently. No metrics HTTP port
is opened on the Pi. The job observes the whole host, including other websites;
it never changes their settings or restarts containers.

The same dependency-free Python script, copied to
`C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py`, opens a local
dashboard at `http://127.0.0.1:8765`. It fetches snapshots through authenticated
SSH every 30 seconds and displays history, danger bands, container health, and
recommendations. SSH uses existing known-host verification and key credentials.
Credentials and environment variables are never collected.

Warning/danger thresholds are operational defaults and can be inspected in the
script. Temperature is 70/80 C; available RAM 750/450 MiB; disk free 10/5 GiB;
CPU use 85/95%; load 1.0/1.5 per core. Current firmware undervoltage/throttling
is a danger; historical firmware flags are informational. Measurements that
cannot be read stay unavailable, rather than being reported as zero.

Temperature thresholds give headroom before documented thermal throttling:
[Raspberry Pi hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
Container resource settings follow the
[Docker Compose service reference](https://docs.docker.com/reference/compose-file/services/).

Examples:

```powershell
python C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py
python C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py --hours 6
python C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py --once
```

On the Pi:

```bash
systemctl status airport-metrics.timer
journalctl -u airport-metrics.service --since today
python3 /opt/arthur-airport/scripts/raspberry_monitor.py export --hours 24
```
