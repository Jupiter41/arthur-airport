"""Enable Pi memory cgroups, preserving a boot backup; reboot separately."""
from pathlib import Path
import argparse
import shutil

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
path = Path("/boot/firmware/cmdline.txt")
before = path.read_text().strip()
tokens = [t for t in before.split() if t != "cgroup_disable=memory"]
for token in ("cgroup_enable=memory", "cgroup_memory=1"):
    if token not in tokens:
        tokens.append(token)
after = " ".join(tokens) + "\n"
print("Remove: cgroup_disable=memory")
print("Add: cgroup_enable=memory cgroup_memory=1")
if args.apply:
    backup = path.with_name("cmdline.txt.before-airport")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(after)
    print(f"Applied. Backup: {backup}. Reboot required.")
else:
    print("Preview only. Pass --apply to write; reboot is a separate action.")
