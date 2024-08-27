import subprocess as sp
import logging
import os
import pandas as pd
from pathlib import Path
from Bio import SeqIO
from vntyper.scripts.file_processing import filter_vcf, filter_indel_vcf

# Construct the Kestrel command based on kmer size and config settings
def construct_kestrel_command(kmer_size, kestrel_path, reference_vntr, output_dir, fastq_1, fastq_2, temp_dir, vcf_out, java_path, java_memory, max_align_states, max_hap_states):
    """
    Constructs the command for running Kestrel based on various settings.
    """
    if not fastq_1 or not fastq_2:
        raise ValueError("FASTQ input files are missing or invalid.")
    
    return (
        f"{java_path} -Xmx{java_memory} -jar {kestrel_path} -k {kmer_size} "
        f"--maxalignstates {max_align_states} --maxhapstates {max_hap_states} "
        f"-r {reference_vntr} -o {vcf_out} "
        f"{fastq_1} {fastq_2} "
        f"--temploc {temp_dir} "
        f"--hapfmt sam -p {temp_dir}/output.sam"
    )

# Kestrel processing logic
def run_kestrel(vcf_path, output_dir, fastq_1, fastq_2, reference_vntr, kestrel_path, temp_dir, kestrel_settings):
    """
    Orchestrates the Kestrel genotyping process by iterating through kmer sizes and processing the VCF output.
    """
    java_path = kestrel_settings.get("java_path", "java")
    java_memory = kestrel_settings.get("java_memory", "15g")
    kmer_sizes = kestrel_settings.get("kmer_sizes", [20, 17, 25, 41])
    max_align_states = kestrel_settings.get("max_align_states", 30)
    max_hap_states = kestrel_settings.get("max_hap_states", 30)
    
    for kmer_size in kmer_sizes:
        kmer_command = construct_kestrel_command(
            kmer_size=kmer_size,
            kestrel_path=kestrel_path,
            reference_vntr=reference_vntr,
            output_dir=output_dir,
            fastq_1=fastq_1,
            fastq_2=fastq_2,
            temp_dir=temp_dir,
            vcf_out=vcf_path,
            java_path=java_path,
            java_memory=java_memory,
            max_align_states=max_align_states,
            max_hap_states=max_hap_states
        )
        
        if vcf_path.is_file():
            logging.info("VCF file already exists, skipping Kestrel run...")
            return
        else:
            logging.info(f"Launching Kestrel with kmer size {kmer_size}...")
            process = sp.Popen(kmer_command, shell=True)
            process.wait()
            logging.info(f"Mapping-free genotyping of MUC1-VNTR with kmer size {kmer_size} done!")

            if vcf_path.is_file():
                process_kestrel_output(output_dir, vcf_path, reference_vntr)
                break  # If successful, break out of the loop and stop trying other kmer sizes

def process_kestrel_output(output_dir, vcf_path, reference_vntr):
    logging.info("Processing Kestrel VCF results...")

    indel_vcf = os.path.join(output_dir, "output_indel.vcf")
    output_ins = os.path.join(output_dir, "output_insertion.vcf")
    output_del = os.path.join(output_dir, "output_deletion.vcf")
    
    # Filter the VCF to extract indels, insertions, and deletions
    filter_vcf(vcf_path, indel_vcf)
    filter_indel_vcf(indel_vcf, output_ins, output_del)

    # Manually read the VCF file to remove '##' comments and retain the header
    def read_vcf_without_comments(vcf_file):
        data = []
        header = None
        with open(vcf_file, 'r') as f:
            for line in f:
                if line.startswith("#CHROM"):
                    header = line.strip().split('\t')
                elif not line.startswith("##"):
                    data.append(line.strip().split('\t'))
        return pd.DataFrame(data, columns=header)

    # Load the filtered VCF files into DataFrames
    vcf_insertion = read_vcf_without_comments(output_ins)
    vcf_deletion = read_vcf_without_comments(output_del)

    # Load MUC1 VNTR reference motifs
    MUC1_ref = load_muc1_reference(reference_vntr)

    # Preprocess insertion and deletion dataframes
    insertion_df = preprocessing_insertion(vcf_insertion, MUC1_ref)
    deletion_df = preprocessing_deletion(vcf_deletion, MUC1_ref)
        
    # Combine insertion and deletion dataframes
    combined_df = pd.concat([insertion_df, deletion_df], axis=0)

    # Process and filter results based on frameshifts and confidence scores
    processed_df = process_kmer_results(combined_df)

    # Save the intermediate pre-result as `_pre_result.tsv`
    pre_result_path = os.path.join(output_dir, "kestrel_pre_result.tsv")
    combined_df.to_csv(pre_result_path, sep='\t', index=False)
    logging.info(f"Intermediate results saved as {pre_result_path}")
    
    # Save the final processed dataframe as `kestrel_result.tsv`
    final_output_path = os.path.join(output_dir, "kestrel_result.tsv")
    processed_df.to_csv(final_output_path, sep='\t', index=False)
    
    logging.info("Kestrel VCF processing completed.")
    return processed_df

def load_muc1_reference(reference_file):
    """
    Loads the MUC1 VNTR reference motifs from a FASTA file.
    """
    identifiers = []
    sequences = []
    with open(reference_file) as fasta_file:
        for seq_record in SeqIO.parse(fasta_file, 'fasta'):
            identifiers.append(seq_record.id)
            sequences.append(seq_record.seq)
    
    return pd.DataFrame({"Motifs": identifiers, "Motif_sequence": sequences})

def preprocessing_insertion(df, muc1_ref):
    """
    Preprocesses insertion variants by merging with the reference motifs.
    """
    # Rename the '#CHROM' column to 'Motifs'
    df.rename(columns={'#CHROM': 'Motifs'}, inplace=True)
    
    # Drop unwanted columns
    df.drop(['ID', 'QUAL', 'FILTER', 'INFO', 'FORMAT'], axis=1, inplace=True)
    
    # Rename the last column to 'Sample'
    last_column_name = df.columns[-1]
    df.rename(columns={last_column_name: 'Sample'}, inplace=True)
    
    # Merge with the MUC1 reference motifs
    df = pd.merge(df, muc1_ref, on='Motifs', how='left')
    
    # Add a 'Variant' column to indicate this is an insertion
    df['Variant'] = 'Insertion'
    
    return df

def preprocessing_deletion(df, muc1_ref):
    """
    Preprocesses deletion variants by merging with the reference motifs.
    """
    # Rename the '#CHROM' column to 'Motifs'
    df.rename(columns={'#CHROM': 'Motifs'}, inplace=True)
    
    # Drop unwanted columns
    df.drop(['ID', 'QUAL', 'FILTER', 'INFO', 'FORMAT'], axis=1, inplace=True)
    
    # Rename the last column to 'Sample'
    last_column_name = df.columns[-1]
    df.rename(columns={last_column_name: 'Sample'}, inplace=True)
    
    # Merge with the MUC1 reference motifs
    df = pd.merge(df, muc1_ref, on='Motifs', how='left')
    
    # Add a 'Variant' column to indicate this is a deletion
    df['Variant'] = 'Deletion'
    
    return df

# Function 1: Split Depth and Calculate Frame Score
def split_depth_and_calculate_frame_score(df):
    """
    Splits the Depth column (Sample) into Del, Estimated_Depth_AlternateVariant, and Estimated_Depth_Variant_ActiveRegion.
    Calculates the frame score and filters out non-frameshift variants.
    """
    # Rename 'Sample' column to 'Depth'
    df = df.rename(columns={'Sample': 'Depth'})

    # Split the 'Depth' column into components
    df[['Del', 'Estimated_Depth_AlternateVariant', 'Estimated_Depth_Variant_ActiveRegion']] = df['Depth'].str.split(':', expand=True)

    # Select relevant columns
    df = df[['Motifs', 'Variant', 'POS', 'REF', 'ALT', 'Motif_sequence', 'Estimated_Depth_AlternateVariant', 'Estimated_Depth_Variant_ActiveRegion']]

    # Calculate reference and alternate allele lengths
    df["ref_len"] = df["REF"].str.len()
    df["alt_len"] = df["ALT"].str.len()

    # Calculate frame score
    df["Frame_Score"] = round((df["alt_len"] - df["ref_len"]) / 3, 2)
    df['Frame_Score'] = df['Frame_Score'].astype(str).apply(lambda x: x.replace('.0', 'C'))

    # Filter out non-frameshift variants
    df["TrueFalse"] = df['Frame_Score'].str.contains('C', regex=True)
    df = df[df["TrueFalse"] == False].copy()

    return df

# Function 2: Split Frame Score
def split_frame_score(df):
    """
    Splits the Frame_Score column into left and right parts. Adjusts the left column values.
    """
    # Split Frame_Score into left and right parts
    df[['left', 'right']] = df['Frame_Score'].str.split('.', expand=True)

    # Replace '-0' with '-1' in the 'left' column
    df['left'] = df['left'].replace('-0', '-1')

    # Drop unnecessary columns
    df.drop(['TrueFalse', 'ref_len', 'alt_len'], axis=1, inplace=True)

    return df

# Function 3: Extract Frameshifts
def extract_frameshifts(df):
    """
    Extracts insertion and deletion frameshifts based on the left and right parts of the Frame_Score.
    """
    # Extract good frameshifts (3n+1 for insertion and 3n+2 for deletion)
    ins = df[df["left"].apply(lambda x: '-' not in x) & df["right"].apply(lambda y: '33' in y)]
    del_ = df[df["left"].apply(lambda x: '-' in x) & df["right"].apply(lambda y: '67' in y)]
    
    # Concatenate insertions and deletions
    frameshifts_df = pd.concat([ins, del_], axis=0)

    return frameshifts_df

# Function 4: Calculate Depth Score and Assign Confidence
def calculate_depth_score_and_assign_confidence(df):
    """
    Calculates depth score and assigns confidence based on depth and variant region conditions.
    """
    # Convert depth-related columns to integers
    df['Estimated_Depth_AlternateVariant'] = df['Estimated_Depth_AlternateVariant'].astype(int)
    df['Estimated_Depth_Variant_ActiveRegion'] = df['Estimated_Depth_Variant_ActiveRegion'].astype(int)

    # Calculate depth score
    df['Depth_Score'] = df['Estimated_Depth_AlternateVariant'] / df['Estimated_Depth_Variant_ActiveRegion']

    # Define conditions for assigning confidence scores
    def assign_confidence(row):
        depth_score = row['Depth_Score']
        alt_depth = row['Estimated_Depth_AlternateVariant']
        var_active_region = row['Estimated_Depth_Variant_ActiveRegion']

        if depth_score <= 0.00469 or var_active_region <= 200:
            return 'Low_Precision'
        elif 21 <= alt_depth <= 100 and 0.00469 <= depth_score <= 0.00515:
            return 'Low_Precision'
        elif alt_depth > 100:
            return 'High_Precision'
        elif alt_depth <= 20:
            return 'Low_Precision'
        elif 21 <= alt_depth < 100 and depth_score >= 0.00515:
            return 'High_Precision'
        elif alt_depth >= 100 and depth_score >= 0.00515:
            return 'High_Precision*'
        else:
            return 'Low_Precision'

    # Apply confidence score assignment
    df['Confidence'] = df.apply(assign_confidence, axis=1)

    return df

# Function 5: Filter by ALT Values and Finalize Data
def filter_by_alt_values_and_finalize(df):
    """
    Filters based on specific ALT values and finalizes the dataframe.
    """
    # Filter based on specific ALT values (e.g., 'GG')
    if df['ALT'].str.contains(r'\bGG\b').any():
        gg_condition = df['ALT'] == 'GG'
        df = pd.concat([
            df[~gg_condition],
            df[gg_condition & (df['Depth_Score'] >= 0.00469)]
        ])

    # Filter out specific ALT sequences (CG, TG)
    df = df[~df['ALT'].isin(['CG', 'TG'])]

    # Drop unnecessary columns
    df.drop(['left', 'right'], axis=1, inplace=True)

    # Keep only high precision results
    if 'Confidence' in df.columns:
        df = df[df['Confidence'] != 'Low_Precision']

    return df

# Main Function: Process Kmer Results
def process_kmer_results(combined_df):
    """
    Processes and filters Kestrel results by applying several steps including frame score calculation,
    depth score assignment, and filtering based on ALT values and confidence scores.
    """
    # Step 1: Split Depth and Calculate Frame Score
    df = split_depth_and_calculate_frame_score(combined_df)

    # Step 2: Split Frame Score
    df = split_frame_score(df)

    # Step 3: Extract Frameshifts
    df = extract_frameshifts(df)

    # Step 4: Calculate Depth Score and Assign Confidence
    df = calculate_depth_score_and_assign_confidence(df)

    # Step 5: Filter by ALT Values and Finalize Data
    df = filter_by_alt_values_and_finalize(df)

    return df
