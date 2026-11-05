#!/bin/bash
# Ujian pembuktian: adakah runner GitHub boleh capai Telegram? Bandingkan dengan laman lain.
for host in api.telegram.org core.telegram.org example.com github.com google.com; do
  code=$(curl -4 -s -o /dev/null -m 10 -w "%{http_code}|%{time_total}|%{remote_ip}" "https://$host/" 2>&1 || echo "GAGAL|0|0")
  echo "$host -> $code"
done
echo "--- TCP crux ke IP Telegram 149.154.167.220:443 ---"
timeout 8 bash -c 'cat < /dev/null > /dev/tcp/149.154.167.220/443' 2>&1 && echo "TCP 443 BUKA" || echo "TCP 443 GAGAL/timeout"
echo "--- DNS ---"
getent ahostsv4 api.telegram.org | head -3
