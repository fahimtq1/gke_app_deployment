# Use the official lightweight Python image.
FROM python:3.9-slim

# Create a non-root user and group with explicit UID/GID
# Using a fixed UID/GID helps with permission management in Kubernetes
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --home /app --shell /bin/sh --disabled-password appuser

# Set working directory to /app
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Change ownership of the application files to the non-root user
RUN chown -R appuser:appgroup /app

# Expose the port the app runs on
EXPOSE 8080

# Switch to the non-root user
USER appuser

# Run the application
CMD ["python", "api.py"]
