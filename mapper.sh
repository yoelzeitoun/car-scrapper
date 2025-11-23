#!/bin/bash
# Wrapper script to run yad2_mapper.py with the correct Python environment

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Use the virtual environment Python
PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Run the mapper script with all arguments
"$PYTHON" "$SCRIPT_DIR/yad2_mapper.py" "$@"
