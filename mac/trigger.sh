#!/bin/bash
# Pokes GitHub to start a workflow right now ("workflow_dispatch").
# Usage: trigger.sh <owner/repo> <workflow-file.yml>
# The GitHub token lives in ~/.config/alpenglow-bridge/github-token (created by install.sh).
# Nothing here ever prints the token.

REPO="$1"
WORKFLOW="$2"
CONF_DIR="$HOME/.config/alpenglow-bridge"
TOKEN_FILE="$CONF_DIR/github-token"
LOG="$HOME/Library/Logs/alpenglow-bridge.log"
mkdir -p "$(dirname "$LOG")"

stamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }

if [ -z "$REPO" ] || [ -z "$WORKFLOW" ]; then
  echo "$(stamp) ERROR usage: trigger.sh <owner/repo> <workflow.yml>" | tee -a "$LOG"; exit 2
fi
if [ ! -s "$TOKEN_FILE" ]; then
  echo "$(stamp) ERROR no token at $TOKEN_FILE — re-run install.sh" | tee -a "$LOG"; exit 2
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

# Try up to 3 times in case the network hiccups.
for attempt in 1 2 3; do
  CODE=$(curl -s -o /tmp/alpenglow-trigger-body.txt -w '%{http_code}' \
    -X POST "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -d '{"ref":"main"}')
  if [ "$CODE" = "204" ]; then
    echo "$(stamp) OK   started $REPO / $WORKFLOW" >> "$LOG"
    exit 0
  fi
  echo "$(stamp) WARN attempt $attempt: HTTP $CODE $(head -c 200 /tmp/alpenglow-trigger-body.txt | tr -d '\n')" >> "$LOG"
  sleep 20
done
echo "$(stamp) FAIL could not start $REPO / $WORKFLOW after 3 tries" >> "$LOG"
exit 1
