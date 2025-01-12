#!/usr/bin/env python3
# vntyper/scripts/motif_processing.py
"""
motif_processing.py

Module Purpose:
---------------
Handles all logic for working with MUC1 VNTR motifs:
  - Loading references from FASTA
  - Preprocessing insertion/deletion data by merging them with motif info
  - Performing final motif correction & annotation based on the Kestrel
    config thresholds (position_threshold, exclude lists).

Typical Flow:
-------------
1. Load the main MUC1 reference to map 'Motif' IDs to sequences.
2. Preprocess insertion/deletion variants by renaming columns and merging
   them with the reference.
3. Possibly load additional motifs from 'MUC1_motifs_Rev_com.fa' for annotation.
4. Correct annotation by splitting left/right motifs, dropping duplicates,
   applying threshold-based logic from the config.

References:
-----------
- Saei et al., iScience 26, 107171 (2023).
"""

import logging
import pandas as pd
from Bio import SeqIO


def load_muc1_reference(reference_file):
    """
    Loads the MUC1 VNTR reference motifs from a FASTA file into a DataFrame.

    Args:
        reference_file (str):
            Path to the FASTA file containing MUC1 VNTR reference motifs.
            Each record ID is treated as 'Motifs', and the sequence as 'Motif_sequence'.

    Returns:
        pd.DataFrame:
            Columns: ['Motifs', 'Motif_sequence']
    """
    identifiers = []
    sequences = []

    with open(reference_file) as fasta_file:
        for seq_record in SeqIO.parse(fasta_file, 'fasta'):
            identifiers.append(seq_record.id)
            sequences.append(seq_record.seq)

    return pd.DataFrame({
        "Motifs": identifiers,
        "Motif_sequence": sequences
    })


def preprocessing_insertion(df, muc1_ref):
    """
    Preprocess insertion variants by merging them with the MUC1 reference motifs.

    Steps:
      - Rename '#CHROM' → 'Motifs'
      - Drop unused columns (ID, QUAL, FILTER, INFO, FORMAT)
      - Rename last column → 'Sample'
      - Merge with 'muc1_ref' to link motif IDs

    Args:
        df (pd.DataFrame): Insertion variants from a filtered VCF.
        muc1_ref (pd.DataFrame): MUC1 reference DataFrame with 'Motifs' & 'Motif_sequence'.

    Returns:
        pd.DataFrame: Updated with columns for 'Variant' = 'Insertion'.
    """
    df.rename(columns={'#CHROM': 'Motifs'}, inplace=True)
    columns_to_drop = ['ID', 'QUAL', 'FILTER', 'INFO', 'FORMAT']
    df.drop(columns=columns_to_drop, axis=1, inplace=True)
    last_column_name = df.columns[-1]
    df.rename(columns={last_column_name: 'Sample'}, inplace=True)
    df = pd.merge(df, muc1_ref, on='Motifs', how='left')
    df['Variant'] = 'Insertion'
    return df


def preprocessing_deletion(df, muc1_ref):
    """
    Preprocess deletion variants by merging them with the MUC1 reference motifs.

    Steps:
      - Rename '#CHROM' → 'Motifs'
      - Drop unused columns
      - Merge with MUC1 reference
      - Mark 'Variant' = 'Deletion'

    Args:
        df (pd.DataFrame): Deletion variants from a filtered VCF.
        muc1_ref (pd.DataFrame): MUC1 reference DataFrame with 'Motifs' & 'Motif_sequence'.

    Returns:
        pd.DataFrame: Updated with columns for 'Variant' = 'Deletion'.
    """
    df.rename(columns={'#CHROM': 'Motifs'}, inplace=True)
    columns_to_drop = ['ID', 'QUAL', 'FILTER', 'INFO', 'FORMAT']
    df.drop(columns=columns_to_drop, axis=1, inplace=True)
    last_column_name = df.columns[-1]
    df.rename(columns={last_column_name: 'Sample'}, inplace=True)
    df = pd.merge(df, muc1_ref, on='Motifs', how='left')
    df['Variant'] = 'Deletion'
    return df


def load_additional_motifs(config):
    """
    Load additional motifs from a FASTA file (e.g., 'MUC1_motifs_Rev_com.fa').

    Typically used to annotate the final results with reversed/complemented motifs
    or other expansions of the MUC1 motif set.

    Args:
        config (dict):
            The pipeline config containing
            ["reference_data"]["muc1_motifs_rev_com"].

    Returns:
        pd.DataFrame:
            Columns: ['Motif', 'Motif_sequence']
    """
    from Bio import SeqIO

    identifiers = []
    sequences = []

    muc1_motifs_rev_com_file = config["reference_data"]["muc1_motifs_rev_com"]

    with open(muc1_motifs_rev_com_file) as motif_file:
        for seq_record in SeqIO.parse(motif_file, 'fasta'):
            identifiers.append(seq_record.id)
            sequences.append(str(seq_record.seq.upper()))

    return pd.DataFrame({
        'Motif': identifiers,
        'Motif_sequence': sequences
    })


def motif_correction_and_annotation(df, merged_motifs, kestrel_config):
    """
    Final step of motif annotation: correct positions for left/right motifs,
    drop duplicates, handle special cases (e.g., 'GG' alt on the right motif).

    Steps:
      1) Split 'Motifs' column into 'Motif_left'/'Motif_right' if it has a dash.
      2) Filter by 'POS' to decide which side is left vs. right, referencing
         the 'position_threshold' from kestrel_config.
      3) Merge with the additional motifs for annotation.
      4) Apply exclude lists for certain motifs or ALTs (e.g., 'exclude_motifs_right').
      5) Adjust 'POS' for the right side so it's zero-based from the threshold.

    References:
        - Saei et al., iScience 26, 107171 (2023)

    Args:
        df (pd.DataFrame): DataFrame with columns (REF, ALT, Motifs, etc.).
        merged_motifs (pd.DataFrame): Additional motif data (from load_additional_motifs).
        kestrel_config (dict): Contains 'motif_filtering' subdict with thresholds.

    Returns:
        pd.DataFrame:
            Updated DataFrame with final annotated/filtered results. May be empty
            if all variants are excluded.
    """
    logging.debug("Entering motif_correction_and_annotation")
    logging.debug(f"Initial row count: {len(df)}, columns: {df.columns.tolist()}")

    # Exit early if empty
    if df.empty:
        logging.debug("DataFrame is empty. Exiting motif_correction_and_annotation.")
        return df

    mf = kestrel_config['motif_filtering']
    position_threshold = mf.get('position_threshold', 60)
    exclude_motifs_right = mf.get('exclude_motifs_right', [])
    alt_for_motif_right_gg = mf.get('alt_for_motif_right_gg', 'GG')
    motifs_for_alt_gg = mf.get('motifs_for_alt_gg', [])
    exclude_alts_combined = mf.get('exclude_alts_combined', [])
    exclude_motifs_combined = mf.get('exclude_motifs_combined', [])

    # Step 1) Rename to 'Motif_fasta' + split 'Motifs'
    pre_split_rows = len(df)
    pre_split_cols = df.columns.tolist()
    if 'Motifs' in df.columns:
        df['Motif_fasta'] = df['Motifs']

    if df['Motifs'].str.count('-').max() == 1:
        df[['Motif_left', 'Motif_right']] = df['Motifs'].str.split('-', expand=True)
    else:
        logging.error("Unexpected format in 'Motifs' column: cannot split as 'left-right'.")
        return pd.DataFrame()

    logging.debug("After splitting 'Motifs' into left/right:")
    logging.debug(f"Changed from {pre_split_rows} rows, {pre_split_cols} columns")
    logging.debug(f"To {len(df)} rows, {df.columns.tolist()} columns")

    # Step 2) Separate into motif_left, motif_right by POS threshold
    df['POS'] = df['POS'].astype(int)
    pre_filter_rows = len(df)
    pre_filter_cols = df.columns.tolist()
    motif_left = df[df['POS'] < position_threshold].copy()
    motif_right = df[df['POS'] >= position_threshold].copy()
    logging.debug("After splitting into left/right sub-DataFrames by POS threshold:")
    logging.debug(f"Original had {pre_filter_rows} rows, columns: {pre_filter_cols}")
    logging.debug(f"motif_left has {len(motif_left)} rows, motif_right has {len(motif_right)} rows")

    # Step 3) Merge + filter left side
    if not motif_left.empty:
        pre_left_merge_rows = len(motif_left)
        pre_left_merge_cols = motif_left.columns.tolist()
        motif_left.rename(columns={'Motif_right': 'Motif'}, inplace=True)
        motif_left.drop(['Motif_sequence'], axis=1, inplace=True)  # if it exists
        motif_left = motif_left.merge(merged_motifs, on='Motif', how='left')
        logging.debug("After merging left motif with 'merged_motifs':")
        logging.debug(f"Changed from {pre_left_merge_rows} rows, {pre_left_merge_cols} columns")
        logging.debug(f"To {len(motif_left)} rows, {motif_left.columns.tolist()} columns")

        keep_cols = [
            'Motif',
            'Motif_fasta',
            'Variant',
            'POS',
            'REF',
            'ALT',
            'Motif_sequence',
            'Estimated_Depth_AlternateVariant',
            'Estimated_Depth_Variant_ActiveRegion',
            'Depth_Score',
            'Confidence',
        ]
        motif_left = motif_left[keep_cols]
        pre_left_filter_rows = len(motif_left)

        # Sort by depth, drop duplicate ALTs but DO NOT do a final .tail(1)
        motif_left = motif_left.sort_values(
            ["Depth_Score", "POS"], ascending=[False, False]
        )

        # Drop duplicates on ALT, keep first in this order:
        motif_left = motif_left.drop_duplicates("ALT", keep="first")



        logging.debug("After final filtering on left motif variants:")
        logging.debug(f"Changed from {pre_left_filter_rows} rows to {len(motif_left)} rows")

    # Step 4) Merge + filter right side
    if not motif_right.empty:
        pre_right_merge_rows = len(motif_right)
        pre_right_merge_cols = motif_right.columns.tolist()
        motif_right.rename(columns={'Motif_left': 'Motif'}, inplace=True)
        motif_right.drop(['Motif_sequence'], axis=1, inplace=True)  # if it exists
        motif_right = motif_right.merge(merged_motifs, on='Motif', how='left')
        logging.debug("After merging right motif with 'merged_motifs':")
        logging.debug(f"Changed from {pre_right_merge_rows} rows, {pre_right_merge_cols} columns")
        logging.debug(f"To {len(motif_right)} rows, {motif_right.columns.tolist()} columns")

        keep_cols = [
            'Motif',
            'Motif_fasta',
            'Variant',
            'POS',
            'REF',
            'ALT',
            'Motif_sequence',
            'Estimated_Depth_AlternateVariant',
            'Estimated_Depth_Variant_ActiveRegion',
            'Depth_Score',
            'Confidence',
        ]
        motif_right = motif_right[keep_cols]

        # Special handling for 'GG' on the right
        pre_right_gg_rows = len(motif_right)
        if motif_right['ALT'].str.contains(r'\b' + alt_for_motif_right_gg + r'\b').any():
            motif_right = motif_right.loc[~motif_right['Motif'].isin(exclude_motifs_right)]
            motif_right = motif_right.loc[motif_right['ALT'] == alt_for_motif_right_gg]
            motif_right = (
                motif_right.sort_values('Depth_Score', ascending=False)
                .drop_duplicates('ALT', keep='first')
            )
            if motif_right['Motif'].isin(motifs_for_alt_gg).any():
                motif_right = motif_right[motif_right['Motif'].isin(motifs_for_alt_gg)]
        else:
            motif_right = (
                motif_right.sort_values('Depth_Score', ascending=False)
                .drop_duplicates('ALT', keep='first')
            )

        logging.debug("After handling 'GG' alt on right motif:")
        logging.debug(f"Changed from {pre_right_gg_rows} rows to {len(motif_right)} rows")

        pre_right_dedup_rows = len(motif_right)
        motif_right.drop_duplicates(subset=['REF', 'ALT'], inplace=True)
        logging.debug("After dropping duplicates on right motif:")
        logging.debug(f"Changed from {pre_right_dedup_rows} rows to {len(motif_right)} rows")

    # Step 5) Combine left/right, exclude certain ALTs/motifs
    pre_combine_rows = (0 if motif_left.empty else len(motif_left)) + (0 if motif_right.empty else len(motif_right))
    combined_df = pd.concat([motif_right, motif_left], axis=0)
    combined_df = combined_df[~combined_df['ALT'].isin(exclude_alts_combined)]
    combined_df = combined_df[~combined_df['Motif'].isin(exclude_motifs_combined)]
    logging.debug("After combining left/right and excluding ALTs/Motifs:")
    logging.debug(f"Combined row count: {pre_combine_rows}, now {len(combined_df)} rows")

    # Step 6) Adjust POS for the right side
    pre_pos_adjust_rows = len(combined_df)
    combined_df['POS'] = combined_df['POS'].astype(int)
    if 'POS' in combined_df.columns:
        combined_df['POS_fasta'] = combined_df['POS']
        combined_df.update(
            combined_df['POS'].mask(
                combined_df['POS'] >= position_threshold,
                lambda x: x - position_threshold
            )
        )
    logging.debug("After adjusting 'POS' for right side variants:")
    logging.debug(f"Changed from {pre_pos_adjust_rows} rows to {len(combined_df)} rows")
    logging.debug(f"Columns are now: {combined_df.columns.tolist()}")

    logging.debug("Exiting motif_correction_and_annotation")
    logging.debug(f"Final row count: {len(combined_df)}, columns: {combined_df.columns.tolist()}")
    return combined_df
