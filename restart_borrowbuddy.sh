#!/opt/bin/bash
# Restart BorrowBuddy Flask Server

echo "Stopping BorrowBuddy server..."
pkill -f 'start_prod.py'
pkill -f 'port=7781'
sleep 2

echo "Starting BorrowBuddy server on port 7781..."
cd /volume1/Web/BorrowBuddy
HOME=/home/<user> nohup /volume1/.@plugins/AppCentral/python3/bin/python3 -u start_prod.py \
< /dev/null &

sleep 3
echo "Server status:"
ps aux | grep 'start_prod.py' | grep python | grep -v grep
echo ""

# Verify server is responding
if curl -sk https://127.0.0.1:7781/BorrowBuddy/ -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q '200\|302'; then
    echo "Server verified - responding on https://192.168.x.x:7781"
else
    echo "Warning: Server may not be responding yet. Check: tail /tmp/borrowbuddy_7781.log"
fi
