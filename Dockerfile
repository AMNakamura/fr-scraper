FROM python:3.15-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only selected scripts
COPY apis/ ./apis/
# COPY scrapers/ ./scrapers/

# No CMD needed. Default, just run the apis.
# Placeholder for future changes.
CMD ["python", "--version"]