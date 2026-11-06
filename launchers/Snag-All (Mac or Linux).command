#!/bin/bash
# Double-click to sort your Downloads folder. You'll see a preview and be asked before anything moves.
# To sort a different folder: open Terminal, drag this file in, add a space, drag the folder in, press Enter.
if ! command -v uv >/dev/null 2>&1; then
  echo "First run: installing uv, the free helper that runs this tool. This only happens once."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uvx --from git+https://github.com/anjavera/Snag-All-Sorting-Script organize "$@"
echo
read -n 1 -r -s -p "Press any key to close this window..."
echo
