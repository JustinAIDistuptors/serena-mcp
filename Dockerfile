FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server implementation
COPY serena_server.py .

# Set environment variables
ENV PORT=8000
ENV LOG_LEVEL=debug
ENV PYTHONUNBUFFERED=1

# Expose the port
EXPOSE 8000

# Run the MCP server
CMD ["python", "serena_server.py"]
