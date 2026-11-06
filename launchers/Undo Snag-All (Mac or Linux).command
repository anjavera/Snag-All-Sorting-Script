#!/bin/bash
# Double-click to put back everything the last sort moved.
if ! command -v uv >/dev/null 2>&1; then
  echo "First run: installing uv, the free helper that runs this tool. This only happens once."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uvx --from git+https://github.com/anjavera/Snag-All-Sorting-Script organize --undo
echo
read -n 1 -r -s -p "Press any key to close this window..."
echo
