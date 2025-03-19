#!/bin/bash
# ===================================================
# Script: install_new_cellprofiler_v3.sh
# Purpose: Install CellProfiler into a dedicated Conda environment
# Requirements:
#   - Anaconda module (anaconda/2024.02)
#   - A valid PREFIX directory (e.g., /exports/igmm/eddie/mharvey2/)
#   - Group membership verification and interactive prompts
# Author: Mungo J.B. Harvey, Scott Warchal 
# Date: 11/02/2025  
# ===================================================
# Usage:
#   1. Update GROUP_NAME and PREFIX variables
#   2. Ensure anaconda/2024.02 module is available
#   3. Run: bash install_new_cellprofiler_v4.sh
#   4. Follow interactive prompts

set -e
set -o pipefail

trap 'echo "[Error] An unexpected error occurred. Exiting..." >&2' ERR

# Define all critical variables upfront
ENV_NAME=cellprofiler
GROUP_NAME=igmm_datastore_Drug-Discovery  # UPDATE: Replace with your data storage group name
PREFIX=/exports/igmm/eddie/Drug-Discovery      # UPDATE: Replace with your user directory path
USER_PREFIX="$PREFIX/$USER"
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

# Helper function to create directories if they do not exist
# Parameters:
#   $1 (dir): The directory path to create/check
# Returns: None
# Description: Creates directory if it doesn't exist, displays status message
setup_directory() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" || { echo "Error: Failed to create directory $dir"; exit 1; }
        echo "Directory created: $dir"
    else
        echo "Directory exists: $dir"
    fi
}

# Function to configure conda settings
# Parameters:
#   $1 (key): The conda config key to set
#   $2 (value): The value to set for the given key
# Returns: None
# Description: Adds new conda config if not already present
configure_conda() {
    local key="$1"
    local value="$2"
    if ! conda config --get "$key" | grep -q "$value"; then
        echo "Adding $value to $key"
        conda config --add "$key" "$value"
    else
        echo "$key already includes $value"
    fi
}

# Check if the user is in the specified group
if ! groups "$USER" | grep -qw "$GROUP_NAME"; then
    echo "$USER not found in $GROUP_NAME group"
    if ! get_yes_no "Cannot be found in $GROUP_NAME, do you wish to proceed?"; then
        exit 1
    fi
fi

# Set up user-specific directories using the helper function
echo "Setting up user-specific directories..."
setup_directory "$USER_PREFIX"
setup_directory "$CONDA_PKGS"
setup_directory "$CONDA_ENVS"

# Load the Anaconda module
module load anaconda/2024.02

# Ensure Conda is initialized
source "$(conda info --base)/etc/profile.d/conda.sh"

# Update Conda configurations to use custom package and environment directories
echo "Checking and updating Conda configurations..."

# Check and set package directories
configure_conda "pkgs_dirs" "$CONDA_PKGS"

# Check and set environment directories
configure_conda "envs_dirs" "$CONDA_ENVS"

# Check and configure channels
for channel in conda-forge anaconda bioconda defaults; do
    if ! conda config --get channels | grep -q "^- $channel\$"; then
        echo "Adding channel: $channel"
        conda config --add channels "$channel"
    else
        echo "Channel $channel already configured"
    fi
done

# Check and set channel priority
current_priority=$(conda config --get channel_priority)
if [[ "$current_priority" != "strict" ]]; then
    echo "Setting channel priority to strict"
    conda config --set channel_priority strict
else
    echo "Channel priority already set to strict"
fi

# Check if Conda is available
if ! command -v conda &> /dev/null; then
    echo "Conda command not found. Please ensure that the anaconda module is loaded."
    exit 1
fi

# Create the environment.yml file with updated CellProfiler version
cat <<EOT > environment.yml
name: $ENV_NAME

channels:
  - conda-forge
  - anaconda
  - bioconda
  - defaults

dependencies:
  - python=3.8
  - pip
  - numpy
  - matplotlib-base
  - pandas
  - mysqlclient=1.4.4
  - openjdk
  - scikit-learn>=0.20,<1
  - mahotas
  - gtk2
  - Jinja2
  - wxpython
  - sentry-sdk
  - h5py>=3.6.0,<4
  - scikit-image==0.18.3
  - scipy==1.9.0
  - tifffile<2022.4.22
  - pip:
      - cellprofiler==4.2.8
EOT

# Check if environment already exists
if conda env list | grep -qw "$ENV_NAME"; then
    # Create timestamp for backup
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_NAME="${ENV_NAME}_backup_${TIMESTAMP}"
    
    echo "Found existing environment '$ENV_NAME'"
    echo "Recommending backup before proceeding with new installation"
    
    if get_yes_no "Would you like to create a backup of the existing environment?"; then
        echo "Creating backup as '$BACKUP_NAME'..."
        conda create --name "$BACKUP_NAME" --clone "$ENV_NAME"
        if get_yes_no "Proceed with removing existing environment and creating new one?"; then
            conda env remove -n "$ENV_NAME"
        else
            echo "Backup created as '$BACKUP_NAME'. Exiting without modifying existing environment."
            exit 1
        fi
    else
        echo "Proceeding without backup is not recommended."
        exit 1
    fi
fi

# Create the Conda environment
echo "Creating the Conda environment '$ENV_NAME'..."
conda env create -f environment.yml

# Activate the environment
echo "Activating the environment..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# Verify installation
echo "Verifying CellProfiler installation..."
if python -c "import cellprofiler" &> /dev/null; then
    echo "CellProfiler installed successfully."
else
    echo "CellProfiler installation failed."
    exit 1
fi

echo "CellProfiler installation complete. You can activate the environment using:"
echo "conda activate $ENV_NAME"

log_step() {
    echo "====> $1"
    # Optionally log to file
    # echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$USER_PREFIX/cellprofiler_install.log"
}


exit 0
