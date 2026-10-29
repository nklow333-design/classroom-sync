FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY app ./app
COPY static ./static
USER appuser
ENV PYTHONUNBUFFERED=1 PORT=3000
EXPOSE 3000
CMD ["python", "-m", "app.server"]
