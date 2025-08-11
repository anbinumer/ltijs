FROM node:20-bookworm

# System deps for Python
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in virtual environment
COPY requirements.txt .
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Add venv to PATH so python scripts can find packages
ENV PATH="/opt/venv/bin:$PATH"

# Install Node deps
COPY package*.json ./
RUN npm ci --omit=dev

# Copy app
COPY . .

# Use Railway PORT
ENV NODE_ENV=production
CMD ["node", "qa-automation-lti.js"]
