import matplotlib
matplotlib.use('Agg')  # Use the Agg backend to avoid Qt-related warnings

import pandas as pd
import os
import logging
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import base64

# Function to load Kestrel results
def load_kestrel_results(kestrel_result_file):
    sample_id = Path(kestrel_result_file).parents[1].name  # Extract the sample ID
    logging.info(f"Loading Kestrel results from {kestrel_result_file}")
    if not os.path.exists(kestrel_result_file):
        logging.warning(f"Kestrel result file not found: {kestrel_result_file}")
        return pd.DataFrame({'Sample': [sample_id]})  # Return DataFrame with Sample ID only
    
    try:
        df = pd.read_csv(kestrel_result_file, sep='\t', comment='#')
        df['Sample'] = sample_id  # Add sample ID column

        # Define the required columns and their human-readable headers
        columns_to_display = {
            'Sample': 'Sample',
            'Motif': 'Motif',
            'Variant': 'Variant',
            'POS': 'Position',
            'REF': 'REF',
            'ALT': 'ALT',
            'Motif_sequence': 'Motif\nSequence',
            'Estimated_Depth_AlternateVariant': 'Depth\n(Alternate Variant)',
            'Estimated_Depth_Variant_ActiveRegion': 'Depth\n(Active Region)',
            'Depth_Score': 'Depth\nScore',
            'Confidence': 'Confidence'
        }

        # Select only the columns that are present in the DataFrame
        available_columns = {col: columns_to_display[col] for col in columns_to_display if col in df.columns}
        missing_columns = set(columns_to_display) - set(available_columns)

        if missing_columns:
            logging.warning(f"Missing columns in {kestrel_result_file}: {missing_columns}")

        # Rename the columns to human-readable names
        df = df[list(available_columns.keys())]
        df = df.rename(columns=available_columns)

        return df
    except pd.errors.ParserError as e:
        logging.error(f"Failed to parse Kestrel result file: {e}")
        return pd.DataFrame({'Sample': [sample_id]})  # Return DataFrame with Sample ID only

# Function to load adVNTR results
def load_advntr_results(advntr_result_file):
    sample_id = Path(advntr_result_file).parents[1].name  # Extract the sample ID
    logging.info(f"Loading adVNTR results from {advntr_result_file}")
    if not os.path.exists(advntr_result_file):
        logging.warning(f"adVNTR result file not found: {advntr_result_file}")
        return pd.DataFrame({'Sample': [sample_id]})  # Return DataFrame with Sample ID only
    
    try:
        df = pd.read_csv(advntr_result_file, sep='\t', comment='#')
        df['Sample'] = sample_id  # Add sample ID column

        # Return only the sample column and any relevant data (if present)
        return df[['Sample'] + [col for col in df.columns if col != 'Sample']]
    except pd.errors.ParserError as e:
        logging.error(f"Failed to parse adVNTR result file: {e}")
        return pd.DataFrame({'Sample': [sample_id]})  # Return DataFrame with Sample ID only

# Function to recursively find all files with a specific name in a directory tree
def find_results_files(root_dir, filename):
    result_files = []
    for root, dirs, files in os.walk(root_dir):
        if filename in files:
            result_files.append(Path(root) / filename)
    return result_files

# Function to load results from all matching files across all subdirectories
def load_results_from_dirs(input_dirs, filename, file_loader):
    dfs = []
    for input_dir in input_dirs:
        result_files = find_results_files(input_dir, filename)
        if not result_files:
            # Handle cases where there are no result files in the directory
            sample_id = Path(input_dir).name
            dfs.append(pd.DataFrame({'Sample': [sample_id]}))  # Append empty DataFrame with Sample ID
        else:
            for file in result_files:
                df = file_loader(file)
                dfs.append(df)
        # log the final df
        logging.info(f"Loaded {len(dfs)} results from {input_dir}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# Helper function to encode image as base64
def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:image/png;base64,{encoded_string}"

# Main function to aggregate cohort results
def aggregate_cohort(input_dirs, output_dir, summary_file, config_path=None):
    # Load results using the individual functions
    kestrel_df = load_results_from_dirs(input_dirs, "kestrel_result.tsv", load_kestrel_results)
    advntr_df = load_results_from_dirs(input_dirs, "output_adVNTR.tsv", load_advntr_results)

    # log the kesrel and advntr df
    logging.info(f"Kestrel results: {kestrel_df}")
    logging.info(f"adVNTR results: {advntr_df}")

    # Generate summary report and plot
    generate_cohort_summary_report(output_dir, kestrel_df, advntr_df, summary_file)

# Function to generate the cohort summary report
def generate_cohort_summary_report(output_dir, kestrel_df, advntr_df, summary_file):
    # Create plots directory within the output directory
    plots_dir = Path(output_dir) / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Generate summary statistics
    kestrel_positive = kestrel_df[kestrel_df['Confidence'] != 'Negative']
    kestrel_negative = kestrel_df[kestrel_df['Confidence'] == 'Negative']

    total_kestrel_positive = len(kestrel_positive)
    total_kestrel_negative = len(kestrel_negative)
    total_advntr = len(advntr_df)

    # Plot summary and save the plot
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Stacked bar plot
    ax.bar('Kestrel Results', total_kestrel_positive, label='Non-Negative', color='skyblue')
    ax.bar('Kestrel Results', total_kestrel_negative, bottom=total_kestrel_positive, label='Negative', color='lightcoral')

    ax.bar('adVNTR Results', total_advntr, color='skyblue')

    ax.set_ylabel('Sample Count')
    ax.legend()

    plot_path = plots_dir / "cohort_summary_plot.png"
    plt.savefig(plot_path)
    plt.close()

    # Convert plot to base64
    plot_base64 = encode_image_to_base64(plot_path)

    # Load the template
    template_dir = "vntyper/templates"
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('cohort_summary_template.html')

    # Render the HTML report
    rendered_html = template.render(
        report_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        kestrel_positive=kestrel_df.to_html(classes='table table-striped table-bordered', index=False),
        advntr_positive=advntr_df.to_html(classes='table table-striped table-bordered', index=False),
        plot_base64=plot_base64
    )

    # Save the HTML report
    report_file_path = Path(output_dir) / summary_file
    with open(report_file_path, 'w') as f:
        f.write(rendered_html)

    logging.info(f"Cohort summary report generated and saved to {report_file_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cohort Summary Report Generator")
    parser.add_argument("-i", "--input_dirs", nargs='+', required=True, help="List of input directories or a text file with directories")
    parser.add_argument("-o", "--output_dir", required=True, help="Output directory for the summary report")
    parser.add_argument("-s", "--summary_file", default="cohort_summary.html", help="Name of the summary report file")
    args = parser.parse_args()

    input_dirs = []
    for i in args.input_dirs:
        if os.path.isfile(i) and i.endswith('.txt'):
            with open(i, 'r') as f:
                input_dirs.extend([line.strip() for line in f])
        else:
            input_dirs.append(i)

    aggregate_cohort(input_dirs, args.output_dir, args.summary_file)
