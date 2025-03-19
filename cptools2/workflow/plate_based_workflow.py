#!/usr/bin/env python3
"""
Module for implementing a plate-based workflow for CellProfiler analysis.
Process one plate at a time with parallel processing within each plate.
"""

import os
import sys
import argparse
from datetime import datetime
import textwrap
from collections import defaultdict

from cptools2 import job, utils, colours, parse_yaml, generate_scripts
from cptools2.colours import pretty_print


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run plate-based CellProfiler analysis")
    parser.add_argument("config_file", help="Path to YAML configuration file")
    parser.add_argument("--plate", help="Process only a specific plate (optional)")
    parser.add_argument("--no-submit", action="store_true", help="Create scripts but don't submit jobs")
    return parser.parse_args()


def extract_plate_commands(jobber, plate_name, pipeline, location, commands_location):
    """
    Extract commands for a specific plate only.
    
    Parameters:
    -----------
    jobber : cptools2.job.Job
        Job instance with all experiment data
    plate_name : str
        Name of the plate to process
    pipeline : str
        Path to CellProfiler pipeline
    location : str
        Path to output location
    commands_location : str
        Path to commands location
        
    Returns:
    --------
    dict: Dictionary with staging, cp_commands, and destaging commands
    """
    # Store original plate store
    original_plate_store = jobber.plate_store.copy()
    original_loaddata_store = jobber.loaddata_store.copy() if jobber.has_loaddata else None
    
    # Filter to just the requested plate
    if plate_name not in jobber.plate_store:
        raise ValueError(f"Plate '{plate_name}' not found in plates: {list(jobber.plate_store.keys())}")
    
    # Keep only the requested plate
    jobber.plate_store = {plate_name: original_plate_store[plate_name]}
    
    # Create loaddata if needed for this plate
    if not jobber.has_loaddata:
        jobber._create_loaddata()
    elif original_loaddata_store:
        jobber.loaddata_store = {plate_name: original_loaddata_store[plate_name]}
    
    # Create a command capture class to get commands without writing to disk
    class CommandCapture:
        def __init__(self):
            self.commands = {"staging": [], "cp_commands": [], "destaging": []}
            
        def write(self, commands_location, rsync_commands, cp_commands, rm_commands):
            self.commands["staging"] = rsync_commands
            self.commands["cp_commands"] = cp_commands
            self.commands["destaging"] = rm_commands
    
    # Capture commands
    from cptools2 import commands
    capture = CommandCapture()
    original_write_commands = commands.write_commands
    commands.write_commands = capture.write
    
    # Call create_commands
    jobber.create_commands(
        pipeline=pipeline,
        location=location,
        commands_location=commands_location,
        job_size=None  # Should be set already in the Job
    )
    
    # Restore original methods and data
    commands.write_commands = original_write_commands
    jobber.plate_store = original_plate_store
    if original_loaddata_store:
        jobber.loaddata_store = original_loaddata_store
    
    return capture.commands


def create_concatenation_script(plate_name, location, job_hex):
    """
    Create a script to concatenate CSV files by type.
    
    Parameters:
    -----------
    plate_name : str
        Name of the plate
    location : str
        Path to main output location
    job_hex : str
        Job identifier hex for naming
        
    Returns:
    --------
    str: Script content
    """
    concat_script = textwrap.dedent(f"""
    #!/bin/bash
    
    # Script to concatenate CSV files for plate {plate_name}
    # Created by cptools2 plate-based workflow
    
    # Set up directories
    RAW_DATA_DIR="{os.path.join(location, 'raw_data')}"
    OUTPUT_DIR="{os.path.join(location, 'plate_csv', plate_name)}"
    
    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"
    
    # Find all CSV files for this plate
    find "$RAW_DATA_DIR" -name "{plate_name}_*.csv" | while read -r file; do
        # Get just the filename without path
        filename=$(basename "$file")
        # Extract the type (after the chunk identifier)
        filetype=$(echo "$filename" | sed 's/{plate_name}_[0-9]\\+_//')
        
        # Append to a list of files by type
        echo "$file" >> "$OUTPUT_DIR/.filelist_$filetype"
    done
    
    # Process each file type
    for filelist in "$OUTPUT_DIR/.filelist_"*; do
        filetype=$(basename "$filelist" | sed 's/.filelist_//')
        output_file="$OUTPUT_DIR/$filetype"
        
        # Get header from first file
        head -1 $(head -1 "$filelist") > "$output_file"
        
        # Append data (skipping headers) from all files
        cat "$filelist" | while read -r file; do
            tail -n +2 "$file" >> "$output_file"
        done
        
        echo "Created concatenated file: $output_file"
        
        # Remove temporary filelist
        rm "$filelist"
    done
    
    echo "All CSV files concatenated for plate {plate_name}"
    """)
    
    return concat_script


def create_cleanup_script(plate_name, location):
    """
    Create a script to clean up temporary files for a plate.
    
    Parameters:
    -----------
    plate_name : str
        Name of the plate
    location : str
        Path to main output location
        
    Returns:
    --------
    str: Script content
    """
    cleanup_script = textwrap.dedent(f"""
    #!/bin/bash
    
    # Script to clean up temporary files for plate {plate_name}
    # Created by cptools2 plate-based workflow
    
    # Remove all staged image data for this plate
    find "{os.path.join(location, 'img_data')}" -name "{plate_name}_*" -type d -exec rm -rf {{}} \\;
    
    # Remove raw data directories for this plate (after concatenation)
    find "{os.path.join(location, 'raw_data')}" -name "{plate_name}_*" -type d -exec rm -rf {{}} \\;
    
    # Remove loaddata files for this plate
    find "{os.path.join(location, 'loaddata')}" -name "{plate_name}_*.csv" -exec rm {{}} \\;
    
    # Remove filelist files for this plate
    find "{os.path.join(location, 'filelist')}" -name "{plate_name}_*" -exec rm {{}} \\;
    
    echo "Cleanup completed for plate {plate_name}"
    """)
    
    return cleanup_script


def process_plate(config, plate_name, no_submit=False):
    """
    Process a single plate with parallelized analysis.
    
    Parameters:
    -----------
    config : dict
        Configuration dictionary from YAML
    plate_name : str
        Name of the plate to process
    no_submit : bool
        If True, don't submit jobs
        
    Returns:
    --------
    str: Path to the submission script
    """
    # Create jobber instance
    jobber = job.Job(is_new_ix=config.get('new_ix', False))
    
    # Setup jobber with experiment data
    if 'experiment' in config:
        jobber.add_experiment(config['experiment'])
    
    # Handle plate additions
    if 'add plate' in config:
        add_plate_config = config['add plate']
        for item in add_plate_config:
            if 'experiment' in item and 'plates' in item:
                jobber.add_plate(item['plates'], item['experiment'])
    
    # Handle plate removals
    if 'remove plate' in config:
        jobber.remove_plate(config['remove plate'])
    
    # Set chunking
    chunk_size = config.get('chunk', 96)
    jobber.chunk(job_size=chunk_size)
    
    # Extract commands for the plate
    pretty_print(f"Creating commands for plate: {colours.yellow(plate_name)}")
    commands_dict = extract_plate_commands(
        jobber,
        plate_name,
        config['pipeline'],
        config['location'],
        config['commands location']
    )
    
    # Create necessary directories
    utils.make_dir(os.path.join(config['location'], 'plate_csv'))
    utils.make_dir(os.path.join(config['location'], 'plate_csv', plate_name))
    
    # Create log directories
    logfile_location = os.path.join(config['location'], 'logfiles', plate_name)
    for subdir in ['staging', 'analysis', 'concatenation', 'cleanup']:
        utils.make_dir(os.path.join(logfile_location, subdir))
    
    # Create command files
    time_now = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    job_hex = os.urandom(2).hex()
    
    scripts_dir = os.path.join(config['commands location'], f"plate_{plate_name}_{time_now}")
    utils.make_dir(scripts_dir)
    
    # Write command files
    staging_file = os.path.join(scripts_dir, "staging_commands.txt")
    cp_file = os.path.join(scripts_dir, "cp_commands.txt")
    destaging_file = os.path.join(scripts_dir, "destaging_commands.txt")
    
    with open(staging_file, "w") as f:
        for cmd in commands_dict['staging']:
            f.write(f"{cmd}\n")
    
    with open(cp_file, "w") as f:
        for cmd in commands_dict['cp_commands']:
            f.write(f"{cmd}\n")
    
    with open(destaging_file, "w") as f:
        for cmd in commands_dict['destaging']:
            f.write(f"{cmd}\n")
    
    # Create job scripts
    from scissorhands import script_generator
    
    # Create staging script
    stage_job = f"stage_{plate_name}_{job_hex}"
    stage_script = script_generator.AnalysisScript(
        name=stage_job,
        tasks=len(commands_dict['staging']),
        memory="1G",
        output=os.path.join(logfile_location, "staging"),
        queue="staging"
    )
    stage_script += "#$ -p -500\n"  # Lower priority
    stage_script += "#$ -tc 20\n"   # Limit concurrent tasks
    stage_script.loop_through_file(staging_file)
    stage_loc = os.path.join(scripts_dir, "staging_script.sh")
    stage_script.save(stage_loc)
    
    # Create analysis script
    analyze_job = f"analyze_{plate_name}_{job_hex}"
    analysis_script = script_generator.AnalysisScript(
        name=analyze_job,
        tasks=len(commands_dict['cp_commands']),
        memory="12G",
        pe="sharedmem 1",
        hold_jid_ad=stage_job,
        output=os.path.join(logfile_location, "analysis")
    )
    # Update module loading
    analysis_script += textwrap.dedent(
        """
        module load anaconda/2024.02
        source activate cellprofiler
        """
    )
    analysis_script.loop_through_file(cp_file)
    analysis_loc = os.path.join(scripts_dir, "analysis_script.sh")
    analysis_script.save(analysis_loc)
    
    # Create concatenation script
    concat_job = f"concat_{plate_name}_{job_hex}"
    concat_script_content = create_concatenation_script(plate_name, config['location'], job_hex)
    concat_loc = os.path.join(scripts_dir, "concatenation_script.sh")
    with open(concat_loc, "w") as f:
        f.write(concat_script_content)
    
    # Make concatenation script executable
    utils.make_executable(concat_loc)
    
    # Create concatenation job submission script
    concat_submit = script_generator.AnalysisScript(
        name=concat_job,
        memory="4G",
        hold_jid_ad=analyze_job,
        output=os.path.join(logfile_location, "concatenation")
    )
    concat_submit += f"\n{concat_loc}\n"
    concat_submit_loc = os.path.join(scripts_dir, "concatenation_submission.sh")
    concat_submit.save(concat_submit_loc)
    
    # Create destaging script
    destage_job = f"destage_{plate_name}_{job_hex}"
    destaging_script = script_generator.AnalysisScript(
        name=destage_job,
        tasks=len(commands_dict['destaging']),
        memory="1G",
        hold_jid_ad=concat_job,
        output=os.path.join(logfile_location, "destaging")
    )
    destaging_script.loop_through_file(destaging_file)
    destage_loc = os.path.join(scripts_dir, "destaging_script.sh")
    destaging_script.save(destage_loc)
    
    # Create cleanup script
    cleanup_job = f"cleanup_{plate_name}_{job_hex}"
    cleanup_script_content = create_cleanup_script(plate_name, config['location'])
    cleanup_loc = os.path.join(scripts_dir, "cleanup_script.sh")
    with open(cleanup_loc, "w") as f:
        f.write(cleanup_script_content)
    
    # Make cleanup script executable
    utils.make_executable(cleanup_loc)
    
    # Create cleanup job submission script
    cleanup_submit = script_generator.AnalysisScript(
        name=cleanup_job,
        memory="2G",
        hold_jid_ad=destage_job,
        output=os.path.join(logfile_location, "cleanup")
    )
    cleanup_submit += f"\n{cleanup_loc}\n"
    cleanup_submit_loc = os.path.join(scripts_dir, "cleanup_submission.sh")
    cleanup_submit.save(cleanup_submit_loc)
    
    # Create master submission script
    submit_script = os.path.join(scripts_dir, "submit_all.sh")
    with open(submit_script, "w") as f:
        f.write(textwrap.dedent(f"""
        #!/bin/bash
        
        # Master submission script for plate: {plate_name}
        # Created by cptools2 plate-based workflow
        
        echo "Submitting jobs for plate: {plate_name}"
        qsub {stage_loc}
        qsub {analysis_loc}
        qsub {concat_submit_loc}
        qsub {destage_loc}
        qsub {cleanup_submit_loc}
        echo "All jobs submitted for plate: {plate_name}"
        """))
    
    # Make submission script executable
    utils.make_executable(submit_script)
    
    # Submit if requested
    if not no_submit:
        pretty_print(f"Submitting jobs for plate: {colours.yellow(plate_name)}")
        os.system(submit_script)
    
    return submit_script


def main():
    """Main function for plate-based workflow."""
    args = parse_arguments()
    
    # Check if on a staging node
    if not utils.on_staging_node():
        raise RuntimeError("Not on a staging node, cannot access datastore")
    
    # Parse the YAML file
    if not os.path.isfile(args.config_file):
        raise ValueError(f"Config file '{args.config_file}' does not exist")
    
    with open(args.config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Create temporary Job to get list of plates
    jobber = job.Job(is_new_ix=config.get('new_ix', False))
    
    # Setup jobber with experiment data
    if 'experiment' in config:
        jobber.add_experiment(config['experiment'])
    
    # Handle plate additions
    if 'add plate' in config:
        add_plate_config = config['add plate']
        for item in add_plate_config:
            if 'experiment' in item and 'plates' in item:
                jobber.add_plate(item['plates'], item['experiment'])
    
    # Handle plate removals
    if 'remove plate' in config:
        jobber.remove_plate(config['remove plate'])
    
    # Create necessary output directories
    utils.make_dir(os.path.join(config['location'], 'plate_csv'))
    
    # Process specific plate or all plates
    submit_scripts = []
    
    if args.plate:
        if args.plate not in jobber.plate_store:
            raise ValueError(f"Plate '{args.plate}' not found")
        
        pretty_print(f"Processing plate: {colours.yellow(args.plate)}")
        submit_script = process_plate(config, args.plate, args.no_submit)
        submit_scripts.append(submit_script)
    else:
        # Process all plates sequentially
        for plate in sorted(jobber.plate_store.keys()):
            pretty_print(f"Processing plate: {colours.yellow(plate)}")
            submit_script = process_plate(config, plate, args.no_submit)
            submit_scripts.append(submit_script)
    
    # Create master submission script for all plates
    if len(submit_scripts) > 1:
        time_now = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        master_script = os.path.join(config['commands location'], f"{time_now}_ALL_PLATES.sh")
        
        with open(master_script, "w") as f:
            f.write("#!/bin/bash\n\n")
            f.write("# Master script for submitting all plates\n\n")
            
            for script in submit_scripts:
                plate_name = os.path.basename(os.path.dirname(script))
                plate_name = plate_name.split('_', 2)[1]  # Extract plate name from directory
                
                f.write(f"echo 'Processing plate: {plate_name}'\n")
                f.write(f"{script}\n")
                f.write("echo 'Waiting for completion...'\n")
                f.write("sleep 5\n\n")
        
        utils.make_executable(master_script)
        pretty_print(f"Created master script: {colours.yellow(master_script)}")
        
        if not args.no_submit:
            pretty_print("Starting sequential plate processing...")
            os.system(master_script)
    
    pretty_print("Plate-based workflow setup complete!")


if __name__ == "__main__":
    main()
