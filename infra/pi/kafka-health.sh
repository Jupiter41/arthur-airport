#!/bin/bash
# Kafka ApiVersions v0 probe; no second JVM inside the broker memory budget.
set -euo pipefail
exec 3<>/dev/tcp/127.0.0.1/9092
# Frame length 12, API key 18, version 0, correlation 42, client ID "pi".
printf '\000\000\000\014\000\022\000\000\000\000\000\052\000\002pi' >&3
header=$(timeout 3 dd bs=8 count=1 iflag=fullblock <&3 2>/dev/null | od -An -tx1 | tr -d ' \n')
[[ "$header" =~ ^[0-9a-f]{8}0000002a$ && "${header:0:8}" != 00000000 ]]
