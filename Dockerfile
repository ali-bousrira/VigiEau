FROM python:3.11-slim

# Dépendances système (PyMuPDF, drivers DB)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python en premier (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY . .

# Répertoire pour artefacts ML
RUN mkdir -p model_artifacts

# Utilisateur non-root — /data est un point de montage séparé (volume
# nommé vigieau_data), doit être préparé et chowné ici pour que le volume
# nommé hérite de ces permissions à sa création (sinon SQLite ne peut pas
# ouvrir le fichier de base : "unable to open database file")
RUN useradd -m -u 1000 vigieau && mkdir -p /data && chown -R vigieau /app /data
USER vigieau

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", \
     "main:app"]
