FROM python:3.10-slim

# Install system dependencies and Node.js (for gemini-cli)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    git \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install gemini-cli globally
# Note: Assuming 'gemini-cli' is the package name. Adjust if it's scoped (e.g., @google/gemini-cli)
# The prototype says 'gemini-cli', so we stick with it.
# RUN npm install -g gemini-cli
RUN npm install -g @google/gemini-cli

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py .

# Create the workspace directory (mount point)
RUN mkdir /workspace

# Environment variable for the workspace directory
ENV WORKSPACE_DIR=/workspace

# Command to run the bot
CMD ["python", "bot.py"]
