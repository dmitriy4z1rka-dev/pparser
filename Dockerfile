FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY leadgen ./leadgen
COPY yamaps_parser ./yamaps_parser
COPY parser-2gis-new ./parser-2gis-new
RUN useradd --create-home --uid 10001 collector && mkdir /data && chown collector:collector /data
USER collector
ENV LEADGEN_DATA=/data
EXPOSE 8090
CMD ["python", "-m", "leadgen", "serve", "--host", "0.0.0.0"]
