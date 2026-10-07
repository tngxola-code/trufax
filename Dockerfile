FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[api]' \
    && useradd --uid 10001 --create-home trufax \
    && mkdir -p /data && chown trufax:trufax /data

ENV TRUFAX_HOME=/data
VOLUME /data
USER trufax
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["trufax", "serve", "--host", "0.0.0.0", "--port", "8000"]
