# Pharos backend container for HuggingFace Spaces (Docker SDK).
#
# At runtime the container pulls the licensed DrugBank SQLite from a
# PRIVATE HuggingFace Dataset owned by the deployer (using HF_TOKEN from
# the Space's "Secrets" tab) and stores it on the Space's ephemeral disk.
# The Pharos app then reads it via PHAROS_DB.
#
# HuggingFace Spaces convention: the container must listen on port 7860.

FROM python:3.11-slim

# huggingface_hub is the only third-party install — purely for fetching
# the DB from the private Dataset on container start.
RUN pip install --no-cache-dir huggingface_hub==0.24.7

WORKDIR /app

# Copy the app source.
COPY app.py ./
COPY neuropharm/ ./neuropharm/
COPY static/ ./static/
COPY start.sh ./
RUN chmod +x start.sh

# HF Spaces requires port 7860 and a non-root user.
RUN useradd -m -u 1000 pharos
USER pharos

# Where the DB will live inside the container after start.sh fetches it.
ENV PHAROS_DB=/app/data/drugbank_full.db \
    PHAROS_HOST=0.0.0.0 \
    PORT=7860

EXPOSE 7860

CMD ["./start.sh"]
