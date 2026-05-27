import os
# pyrefly: ignore [missing-import]
from pdf2image import convert_from_path
from typing import Optional

# Create a temporary directory for processed images if it doesn't exist
TEMP_DIR = "temp_processed_images"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def convert_pdf_to_image(file_path: str) -> Optional[str]:
    """
    Lazily converts the first page of a PDF to a JPEG image.
    If the file is already an image, it returns the original path.
    Requires the 'poppler' utility to be installed on the system.

    Args:
        file_path: The absolute path to the file.

    Returns:
        The path to the converted JPEG image, or the original path if not a PDF.
        Returns None if conversion fails.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None

    file_name, file_ext = os.path.splitext(os.path.basename(file_path))
    
    # If it's not a PDF, assume it's an image and return the path
    if file_ext.lower() != ".pdf":
        print("File is not a PDF. Returning original path.")
        return file_path

    output_image_path = os.path.join(TEMP_DIR, f"{file_name}_page1.jpg")

    # If the image already exists, no need to convert again
    if os.path.exists(output_image_path):
        print(f"Converted image already exists: {output_image_path}")
        return output_image_path

    print(f"Converting PDF '{file_name}{file_ext}' to JPEG...")
    try:
        # Convert the first page of the PDF to an image
        images = convert_from_path(file_path, first_page=1, last_page=1, fmt='jpeg')
        
        if images:
            images[0].save(output_image_path, 'JPEG')
            print(f"Successfully converted and saved to {output_image_path}")
            return output_image_path
        else:
            print("Error: PDF conversion resulted in no images.")
            return None
    except Exception as e:
        print(f"An error occurred during PDF to image conversion: {e}")
        print("Please ensure 'poppler' is installed and in your system's PATH.")
        return None
