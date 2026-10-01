#!/data/data/com.termux/files/usr/bin/sh
# Keeps Signal Lab running on the phone. Lives at ~/signal-lab/start.sh.
#
# It runs whichever version current.txt names. Exit code 3 means "restart me" (after an
# install or a roll back) and restarts at once; anything else is a crash and waits 10 seconds
# first, so a broken start can't spin the phone hot.

export SIGNAL_LAB_HOME="$HOME/signal-lab"
cd "$SIGNAL_LAB_HOME" || exit 1
command -v termux-wake-lock >/dev/null && termux-wake-lock

while true; do
  V=$(cat current.txt)
  python "versions/$V/server.py"
  code=$?
  if [ "$code" -ne 3 ]; then
    echo "Signal Lab stopped (exit $code); restarting in 10 seconds"
    sleep 10
  fi
done
