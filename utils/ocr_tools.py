import os
import boto3
# pyrefly: ignore [missing-import]
import cv2
from typing import Optional

# Ensure the temp directory exists
TEMP_DIR = "temp_processed_images"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def clean_image_with_opencv(image_path: str) -> Optional[str]:
    """
    Reads an image, converts it to grayscale, applies adaptive thresholding to
    binarize it, saves it to a temporary file, and returns the new path.

    Args:
        image_path: The path to the input image.

    Returns:
        The path to the cleaned image, or None if an error occurs.
    """
    print(f"---Cleaning image with OpenCV: {os.path.basename(image_path)}---")
    try:
        # Read the image
        img = cv2.imread(image_path)
        if img is None:
            print(f"Error: Could not read image from path: {image_path}")
            return None

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply adaptive thresholding
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Define the output path
        file_name, file_ext = os.path.splitext(os.path.basename(image_path))
        output_path = os.path.join(TEMP_DIR, f"{file_name}_cleaned.png")

        # Save the cleaned image
        cv2.imwrite(output_path, binary)
        print(f"Cleaned image saved to: {output_path}")
        return output_path

    except Exception as e:
        print(f"An error occurred during OpenCV image cleaning: {e}")
        return None


def _format_table_as_markdown(table_matrix: list[list[str]]) -> str:
    """Formats a 2D list of strings into a Markdown table."""
    if not table_matrix:
        return ""

    # Calculate the maximum width for each column
    num_columns = max(len(row) for row in table_matrix) if table_matrix else 0
    if num_columns == 0:
        return ""
        
    column_widths = [0] * num_columns
    for row in table_matrix:
        for i, cell in enumerate(row):
            if i < num_columns:
                column_widths[i] = max(column_widths[i], len(cell))

    # Build the Markdown table
    markdown_table = ""
    # Header row
    if table_matrix[0]:
        header = " | ".join(f"{cell:<{column_widths[i]}}" for i, cell in enumerate(table_matrix[0]))
        markdown_table += f"| {header} |\n"
    
        # Separator line
        separator = " | ".join("-" * (width + 2) for width in column_widths)
        markdown_table += f"|{separator}|\n"
    
    # Body rows
    for row in table_matrix[1:]:
        body = " | ".join(f"{cell:<{column_widths[i] if i < len(column_widths) else 0}}" for i, cell in enumerate(row))
        markdown_table += f"| {body} |\n"
        
    return markdown_table

def extract_tables_with_textract(file_bytes: bytes) -> str:
    """
    Uses AWS Textract to analyze a document, parse table structures, and
    return them as a formatted Markdown string.
    """
    print("---Extracting tables with AWS Textract (Production Parser)---")
    try:
        textract_client = boto3.client("textract")
        response = textract_client.analyze_document(
            Document={'Bytes': file_bytes},
            FeatureTypes=['TABLES']
        )
        
        blocks = response['Blocks']
        block_map = {block['Id']: block for block in blocks}
        table_blocks = [b for b in blocks if b['BlockType'] == 'TABLE']

        if not table_blocks:
            return "No tables found by AWS Textract."

        all_markdown_tables = []
        for i, table in enumerate(table_blocks):
            # Determine table dimensions dynamically
            max_row, max_col = 0, 0
            for relationship in table.get('Relationships', []):
                if relationship['Type'] == 'CHILD':
                    for cell_id in relationship['Ids']:
                        cell = block_map.get(cell_id)
                        if cell:
                            max_row = max(max_row, cell.get('RowIndex', 0))
                            max_col = max(max_col, cell.get('ColumnIndex', 0))
            
            if max_row == 0 or max_col == 0:
                continue

            # Create an empty matrix for the table
            table_matrix = [["" for _ in range(max_col)] for _ in range(max_row)]

            # Populate the matrix with cell text
            for relationship in table.get('Relationships', []):
                if relationship['Type'] == 'CHILD':
                    for cell_id in relationship['Ids']:
                        cell = block_map.get(cell_id)
                        if not cell:
                            continue
                        
                        row_index = cell.get('RowIndex', 1) - 1
                        col_index = cell.get('ColumnIndex', 1) - 1
                        
                        cell_text = ""
                        for rel in cell.get('Relationships', []):
                            if rel['Type'] == 'CHILD':
                                for word_id in rel['Ids']:
                                    word = block_map.get(word_id)
                                    if word and 'Text' in word:
                                        cell_text += word['Text'] + " "
                        
                        if 0 <= row_index < max_row and 0 <= col_index < max_col:
                            table_matrix[row_index][col_index] = cell_text.strip()
            
            all_markdown_tables.append(f"Table {i+1}:\n{_format_table_as_markdown(table_matrix)}")

        if not all_markdown_tables:
            return "No valid tables parsed."

        print(f"Successfully parsed {len(all_markdown_tables)} table(s).")
        return "\n\n".join(all_markdown_tables)

    except Exception as e:
        print(f"An error occurred during Textract API call or parsing: {e}")
        return "Error extracting and parsing tables."
