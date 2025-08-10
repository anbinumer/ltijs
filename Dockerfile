FROM node:20-bookworm

# System deps for Python
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install Node deps
COPY package*.json ./
RUN npm ci --omit=dev

# Copy app
COPY . .

# Use Railway PORT
ENV NODE_ENV=production
CMD ["node", "qa-automation-lti.js"]
