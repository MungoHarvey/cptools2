#!/usr/bin/env python3
"""
Utilities for working with CSV files from CellProfiler output.
"""

import os
import glob
import pandas as pd
from cptools2 import utils
from cptools2.colours import pretty_print


def find_csv_types(input_dir, plate_name):
    """
    Find all CSV file types for a given plate.
    
    Parameters:
    -----------
    input_dir : str
        Path to directory containing raw CellProfiler output
    plate_name : str
        Name of the plate
        
    Returns:
    --------
    dict: Dictionary mapping CSV types to lists of files
    """
    csv_files = {}
    
    # Find all raw data directories for this plate
    plate_dirs = glob.glob(os.path.join(input_dir, f"{plate_name}_*"))
    
    for plate_dir in plate_dirs:
        # Find all CSV files in this directory
        for csv_file in glob.glob(os.path.join(plate_dir, "*.csv")):
            # Extract just the file type (e.g., Image.csv, Cells.csv)
            file_type = os.path.basename(csv_file)
            
            if file_type not in csv_files:
                csv_files[file_type] = []
            
            csv_files[file_type].append(csv_file)
    
    return csv_files


def concatenate_csvs(file_list, output_path):
    """
    Concatenate CSV files of the same type.
    
    Parameters:
    -----------
    file_list : list
        List of CSV file paths to concatenate
    output_path : str
        Path to save the concatenated file
        
    Returns:
    --------
    bool: True if successful, False otherwise
    """
    if not file_list:
        return False
    
    try:
        # Read the files into a list of dataframes
        dfs = []
        for i, file_path in enumerate(file_list):
            if i == 0:
                # Keep header from first file
                df = pd.read_csv(file_path)
                dfs.append(df)
            else:
                # Skip header for subsequent files
                df = pd.read_csv(file_path, skiprows=1)
                dfs.append(df)
        
        # Concatenate the dataframes
        if dfs:
            result = pd.concat(dfs, ignore_index=True)
            result.to_csv(output_path, index=False)
            return True
        
        return False
    
    except Exception as e:
        pretty_print(f"Error concatenating CSV files: {e}")
        return False


def process_plate_csvs(plate_name, input_dir, output_dir):
    """
    Process all CSV files for a plate.
    
    Parameters:
    -----------
    plate_name : str
        Name of the plate
    input_dir : str
        Path to directory containing raw CellProfiler output
    output_dir : str
        Path to directory where concatenated CSVs should be saved
        
    Returns:
    --------
    dict: Dictionary of created CSV files
    """
    # Create output directory if it doesn't exist
    utils.make_dir(output_dir)
    
    # Find all CSV types for this plate
    csv_types = find_csv_types(input_dir, plate_name)
    
    results = {}
    for file_type, files in csv_types.items():
        output_path = os.path.join(output_dir, file_type)
        success = concatenate_csvs(files, output_path)
        
        if success:
            results[file_type] = output_path
    
    return results
