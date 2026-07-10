# Use a slim, modern Python base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required for the 'pdf2image' library
RUN apt-get update && apt-get install -y poppler-utils && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port the app will run on. Render automatically sets the PORT env var.
EXPOSE 8000

# Command to start the Uvicorn server, binding to all interfaces
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
