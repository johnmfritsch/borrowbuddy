#!/opt/bin/bash
# Thin env wrapper (prod). All logic lives in _borrowbuddy_server_lib.sh.
#   app_restart <env> <appdir> <pid_file> <port> <prefix> <log>
DIR="$(dirname "$(readlink -f "$0")")"
. "$DIR/_borrowbuddy_server_lib.sh"
app_restart prod \
    /volume1/Web/BorrowBuddy \
    /volume1/Web/BorrowBuddy/borrowbuddy_prod.pid \
    7781 \
    /BorrowBuddy \
    /volume1/Web/BorrowBuddy/logs/borrowbuddy_prod.log
