#!/bin/bash
# ===================================================
# Script: install_cptools2.sh
# Purpose: Install cptools2 and related tools into an existing CellProfiler Conda environment
# Author: Mungo J.B. Harvey, Scott Warchal
# Date: 11/02/2025
# ===================================================

set -e
set -o pipefail

trap 'echo "[Error] An unexpected error occurred. Exiting..." >&2' ERR

# Define all critical variables upfront
ENV_NAME=cellprofiler
GROUP_NAME=igmm_datastore_Drug-Discovery  # UPDATE: Replace with your data storage group name
PREFIX=/exports/igmm/eddie/Drug-Discovery      # UPDATE: Replace with your group directory path
USER_PREFIX="$USER"
CONDA_PKGS="$USER_PREFIX/.conda_pkgs"
CONDA_ENVS="$USER_PREFIX/.conda_envs"

# Function to validate yes/no input
# Parameters:
#   $1 (prompt): The question to display to the user
# Returns:
#   0 for yes/y, 1 for no/n
# Description: Continuously prompts user for y/n input until valid response received
get_yes_no() {
    local prompt="$1"
    local response
    while true; do
        read -p "$prompt (y/n): " response
        case "$response" in
            [Yy]) return 0 ;;
            [Nn]) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

# Initial validation of user settings
echo "=== Current Configuration ==="
echo "Group Name: $GROUP_NAME"
echo "Prefix Directory: $PREFIX"
echo "================================================"
echo "IMPORTANT: Please verify these settings are correct"
echo "If not, please edit the script and update the"
echo "GROUP_NAME and PREFIX variables before proceeding."
echo "================================================"

if ! get_yes_no "Are these settings correct and do you want to proceed with installation?"; then
    echo "Please update the settings in the script and try again."
    echo "You can edit the script using:"
    echo "  nano install_new_cellprofiler_v4.sh"
    echo "  or"
    echo "  vim install_new_cellprofiler_v4.sh"
    echo "Then save with a new name to preserve the original."
    exit 1
fi

# Load Anaconda
module load anaconda/2024.02
source "$(conda info --base)/etc/profile.d/conda.sh"

# Check if environment exists
if ! conda env list | grep -qw "$ENV_NAME"; then
    echo "Error: Environment '$ENV_NAME' not found."
    echo "Please install CellProfiler first using install_new_cellprofiler_v4.sh"
    exit 1
fi

# Create template directory
setup_directory() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" || { echo "Error: Failed to create directory $dir"; exit 1; }
        echo "Directory created: $dir"
    else
        echo "Directory exists: $dir"
    fi
}

# Define template directory path
TEMPLATE_DIR="$USER_PREFIX/cptools2_templates"
setup_directory "$TEMPLATE_DIR"

# Activate environment and install packages
conda activate "$ENV_NAME"

echo "Installing cptools2 and dependencies..."
pip install --upgrade pip

# Install required packages
pip install pyyaml>=5.1 pandas>=0.16
pip install git+https://github.com/carragherlab/parserix.git@new_ix
pip install git+https://github.com/carragherlab/scissorhands.git
pip install git+https://github.com/swarchal/cptools2.git

# Create template YAML
cat <<EOF > "$TEMPLATE_DIR/template_config.yml"
experiment: /exports/imaging/screening/experiment_001  # Path to your ImageXpress experiment
chunk: 96                                             # Number of images per job (96 recommended)
pipeline: /exports/analysis/pipeline.cppipe           # Your CellProfiler pipeline file
location: /exports/eddie/scratch/$USER/analysis       # Temporary analysis directory
commands location: /home/$USER                        # Where to save job submission scripts
EOF

# Create README
cat <<EOF > "$TEMPLATE_DIR/README_instructions.txt"
# Instructions for Using cptools2

1. Edit template_config.yml with your paths:
   - experiment: Location of your ImageXpress data
   - pipeline: Path to your CellProfiler pipeline
   - location: Where analysis will be performed (use scratch space)

2. Load required modules:
   module load anaconda/2024.02

3. Activate the environment:
   conda activate $ENV_NAME

4. Run cptools2:
   cptools2 template_config.yml

5. Submit jobs:
   bash SUBMIT_JOBS.sh

For more information:
- https://github.com/swarchal/cptools2
- https://github.com/CarragherLab/cptools2/wiki
EOF

# Verify installation
if cptools2 --help &> /dev/null; then
    echo "✓ cptools2 installed successfully!"
    echo "✓ Template files created in: $TEMPLATE_DIR"
    echo ""
    echo "To get started:"
    echo "1. conda activate $ENV_NAME"
    echo "2. Edit: $TEMPLATE_DIR/template_config.yml"
    echo "3. Run: cptools2 path/to/your_config.yml"
else
    echo "Installation failed. Please check the error messages above."
    exit 1
fi
