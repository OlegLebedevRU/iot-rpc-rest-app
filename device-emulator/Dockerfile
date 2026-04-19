FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY device_emulator.py /app/device_emulator.py

# Run as a non-root user
RUN useradd --create-home --uid 1000 emulator
USER emulator

ENTRYPOINT ["python", "-u", "/app/device_emulator.py"]
