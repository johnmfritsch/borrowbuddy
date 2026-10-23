#!/opt/bin/bash
# Thin env wrapper (prod). All logic lives in _borrowbuddy_server_lib.sh.
DIR="$(dirname "$(readlink -f "$0")")"
. "$DIR/_borrowbuddy_server_lib.sh"
app_stop /volume1/Web/BorrowBuddy/borrowbuddy_prod.pid 7781
