FROM python:3.13-slim

# junos-eznc needs build tools for some C extensions (ncclient, paramiko, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev libxml2-dev libxslt1-dev \
    iputils-ping traceroute dnsutils nmap curl net-tools iproute2 git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server.py .

# Shared device inventory is mounted at runtime via docker-compose
# Volume: ./shared:/app/shared:ro

EXPOSE 8000
CMD ["python", "mcp_server.py"]
