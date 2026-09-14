#!/bin/bash
# One-time setup on the always-on Mac mini. Run it in Terminal with:
#
#   curl -fsSL https://raw.githubusercontent.com/Riv419/bar-sales-bridge/main/mac/install.sh | bash
#
# What it does:
#   1. Asks you to paste a GitHub token (typed invisibly) and saves it in
#      ~/.config/alpenglow-bridge/github-token, readable only by you.
#   2. Installs trigger.sh next to it.
#   3. Creates two launchd jobs (macOS's built-in scheduler) that poke GitHub
#      at exact times so the Actions run on time instead of whenever GitHub
#      feels like it:
#        - bar sales:     every 30 min from 4:05 PM to 12:35 AM, plus 12:50 AM
#        - Cedar lodging: 12:45 AM, 7:05 AM, 12:05 PM, 5:05 PM, 9:05 PM
#      Times are the Mac's local time (Eastern), so daylight-saving is automatic.
#   4. Fires one test run of each and shows you the result.
#
# Safe to re-run: it just overwrites the previous setup.

set -e
CONF_DIR="$HOME/.config/alpenglow-bridge"
AGENTS="$HOME/Library/LaunchAgents"
RAW="https://raw.githubusercontent.com/Riv419/bar-sales-bridge/main/mac"
mkdir -p "$CONF_DIR" "$AGENTS" "$HOME/Library/Logs"
chmod 700 "$CONF_DIR"

echo
echo "== Alpenglow bridge trigger setup =="
echo
if [ -s "$CONF_DIR/github-token" ]; then
  echo "A GitHub token is already saved. Press Return to keep it, or paste a new one:"
else
  echo "Paste your GitHub token (fine-grained, Actions: Read and write on both repos)."
  echo "Nothing will show while you paste — that's normal. Then press Return:"
fi
read -r -s TOKEN < /dev/tty
echo
if [ -n "$TOKEN" ]; then
  printf '%s' "$TOKEN" | tr -d '[:space:]' > "$CONF_DIR/github-token"
  chmod 600 "$CONF_DIR/github-token"
  echo "Token saved."
fi
if [ ! -s "$CONF_DIR/github-token" ]; then
  echo "No token saved — stopping. Run this again and paste the token."; exit 1
fi

# Fresh copy of the trigger script.
curl -fsSL "$RAW/trigger.sh" -o "$CONF_DIR/trigger.sh"
chmod 700 "$CONF_DIR/trigger.sh"

# ---- launchd plists ---------------------------------------------------------
write_plist() {  # label repo workflow "HH:MM HH:MM ..."
  local LABEL="$1" REPO="$2" WF="$3" TIMES="$4"
  local PLIST="$AGENTS/$LABEL.plist"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0"><dict>'
    echo "  <key>Label</key><string>$LABEL</string>"
    echo '  <key>ProgramArguments</key><array>'
    echo '    <string>/bin/bash</string>'
    echo "    <string>$CONF_DIR/trigger.sh</string>"
    echo "    <string>$REPO</string>"
    echo "    <string>$WF</string>"
    echo '  </array>'
    echo '  <key>StartCalendarInterval</key><array>'
    for t in $TIMES; do
      echo "    <dict><key>Hour</key><integer>${t%%:*}</integer><key>Minute</key><integer>${t##*:}</integer></dict>"
    done
    echo '  </array>'
    echo "  <key>StandardOutPath</key><string>$HOME/Library/Logs/alpenglow-bridge.log</string>"
    echo "  <key>StandardErrorPath</key><string>$HOME/Library/Logs/alpenglow-bridge.log</string>"
    echo '</dict></plist>'
  } > "$PLIST"
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Scheduled $LABEL -> $REPO / $WF at: $TIMES"
}

BAR_TIMES="16:05 16:35 17:05 17:35 18:05 18:35 19:05 19:35 20:05 20:35 21:05 21:35 22:05 22:35 23:05 23:35 0:05 0:35 0:50"
LODGING_TIMES="0:45 7:05 12:05 17:05 21:05"

write_plist com.alpenglow.bar-sales-trigger   Riv419/bar-sales-bridge     pull-sales.yml "$BAR_TIMES"
write_plist com.alpenglow.cedar-lodging-trigger Riv419/cedar-pricing-bridge lodging.yml   "$LODGING_TIMES"

# ---- test fire --------------------------------------------------------------
echo
echo "Test-firing both workflows now..."
if bash "$CONF_DIR/trigger.sh" Riv419/bar-sales-bridge pull-sales.yml; then
  echo "  bar sales: started OK"
else
  echo "  bar sales: FAILED — see $HOME/Library/Logs/alpenglow-bridge.log (usually a token problem)"
fi
if bash "$CONF_DIR/trigger.sh" Riv419/cedar-pricing-bridge lodging.yml; then
  echo "  Cedar lodging: started OK"
else
  echo "  Cedar lodging: FAILED — see $HOME/Library/Logs/alpenglow-bridge.log"
fi
echo
echo "Done. Check https://github.com/Riv419/bar-sales-bridge/actions in a minute —"
echo "you should see a fresh run marked 'Manually run by Riv419'."
echo "Log file: $HOME/Library/Logs/alpenglow-bridge.log"
