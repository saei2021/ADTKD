import subprocess as sp
import logging
import os

def check_bwa_index(reference):
    """
    Check if the BWA index files exist for the given reference genome.
    The index files should have extensions: .amb, .ann, .bwt, .pac, and .sa
    """
    required_extensions = [".amb", ".ann", ".bwt", ".pac", ".sa"]
    for ext in required_extensions:
        if not os.path.exists(f"{reference}{ext}"):
            return False
    return True

def align_and_sort_fastq(fastq1, fastq2, reference, output_dir, output_name, threads, config):
    """
    Align FASTQ files to the reference genome using BWA, sort the SAM file, and convert to BAM using Samtools.

    Args:
        fastq1: Path to the first FASTQ file.
        fastq2: Path to the second FASTQ file.
        reference: Path to the reference genome in FASTA format.
        output_dir: Directory where output files will be saved.
        output_name: Base name for the output files.
        threads: Number of threads to use.
        config: Configuration dictionary with paths and parameters.
    """
    # Extract paths from the config
    samtools_path = config["tools"]["samtools"]

    sam_out = os.path.join(output_dir, f"{output_name}.sam")
    bam_out = os.path.join(output_dir, f"{output_name}.bam")
    sorted_bam_out = os.path.join(output_dir, f"{output_name}_sorted.bam")

    # Check if the BWA index files exist
    if not check_bwa_index(reference):
        logging.error(f"BWA index files not found for reference: {reference}. Please run 'bwa index' on the reference file.")
        return None

    # BWA MEM command
    bwa_command = f"bwa mem -t {threads} {reference} {fastq1} {fastq2} -o {sam_out}"

    logging.info("Starting BWA alignment...")
    process = sp.Popen(bwa_command, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        logging.error(f"BWA alignment failed: {stderr.decode().strip()}")
        return None

    if not os.path.exists(sam_out):
        logging.error(f"SAM file {sam_out} not created. BWA alignment might have failed.")
        return None

    logging.info("BWA alignment completed.")

    logging.info("Converting SAM to BAM with Samtools...")
    samtools_view_command = f"{samtools_path} view -@ {threads} -bS {sam_out} -o {bam_out}"
    process = sp.Popen(samtools_view_command, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        logging.error(f"SAM to BAM conversion failed: {stderr.decode().strip()}")
        return None

    if not os.path.exists(bam_out):
        logging.error(f"BAM file {bam_out} not created. SAM to BAM conversion might have failed.")
        return None

    logging.info("SAM to BAM conversion completed.")

    logging.info("Sorting BAM file with Samtools...")
    samtools_sort_command = f"{samtools_path} sort -@ {threads} -o {sorted_bam_out} {bam_out}"
    process = sp.Popen(samtools_sort_command, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        logging.error(f"BAM sorting failed: {stderr.decode().strip()}")
        return None

    if not os.path.exists(sorted_bam_out):
        logging.error(f"Sorted BAM file {sorted_bam_out} not created. BAM sorting might have failed.")
        return None

    logging.info("BAM sorting completed.")

    logging.info("Indexing sorted BAM file with Samtools...")
    samtools_index_command = f"{samtools_path} index {sorted_bam_out}"
    process = sp.Popen(samtools_index_command, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        logging.error(f"BAM indexing failed: {stderr.decode().strip()}")
        return None

    if not os.path.exists(f"{sorted_bam_out}.bai"):
        logging.error(f"BAM index file {sorted_bam_out}.bai not created. BAM indexing might have failed.")
        return None

    logging.info("Samtools indexing completed.")
    
    return sorted_bam_out
