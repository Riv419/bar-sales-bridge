#!/bin/bash
# Removes the Mac mini trigger jobs and the saved token.
#   curl -fsSL https://raw.githubusercontent.com/Riv419/bar-sales-bridge/main/mac/uninstall.sh | bash
for LABEL in com.alpenglow.bar-sales-trigger com.alpenglow.cedar-lodging-trigger; do
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
done
rm -rf "$HOME/.config/alpenglow-bridge"
echo "Removed the trigger jobs and the saved token. (Revoke the token on GitHub too if you're done with it.)"
