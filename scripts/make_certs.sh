#!/bin/bash
# iPhone から https で開くための証明書を certs/ に作る。
# - 信頼の元(rootCA)は最初の1回だけ作る。iPhone に入れるのはこの rootCA.crt
# - サーバーの証明書は、今の Wi-Fi の IP アドレスで毎回作り直す(IP が変わっても iPhone 側はそのままでよい)
# Mac 自身には何も登録しない
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs && cd certs

IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || true)"
[ -n "$IP" ] || { echo "Wi-Fi の IP アドレスが分かりません。Wi-Fi につないでください"; exit 1; }

if [ ! -f rootCA.crt ]; then
  # 家のネットワークの住所にしか使えないよう制限する。鍵が漏れても、普通のサイトの偽物は作れない
  cat > ca.cnf <<'EOF'
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = AI friend local CA
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, permitted;IP:192.168.0.0/255.255.0.0, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, permitted;IP:127.0.0.1/255.255.255.255, permitted;DNS:localhost
EOF
  openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 825 -keyout rootCA-key.pem -out rootCA.crt -config ca.cnf 2>/dev/null
  chmod 600 rootCA-key.pem
  echo "信頼の元を作りました: certs/rootCA.crt (iPhone に入れる。README の「iPhone で使う」)"
fi

cat > server.cnf <<EOF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = IP:$IP, IP:127.0.0.1, DNS:localhost
authorityKeyIdentifier = keyid
subjectKeyIdentifier = hash
EOF
# iPhone は有効期限が 398 日を超える証明書を受け付けない
openssl req -new -nodes -newkey rsa:2048 -keyout key.pem -out server.csr -subj "/CN=$IP" 2>/dev/null
openssl x509 -req -in server.csr -CA rootCA.crt -CAkey rootCA-key.pem -CAcreateserial -out cert.pem -days 397 -sha256 -extfile server.cnf 2>/dev/null
chmod 600 key.pem
echo "$IP" > ip.txt
