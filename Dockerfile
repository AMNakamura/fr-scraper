FROM python:3.15-slim

WORKDIR /app
# Create /app inside the container and move all files into it
# COPY statements will put everything into /app inside the container

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only selected scripts
COPY main.py
COPY apis/ ./apis/
# COPY scrapers/ ./scrapers/

# No CMD needed. Default, just run the apis.

ENTRYPOINT ["python", "main.py"]
