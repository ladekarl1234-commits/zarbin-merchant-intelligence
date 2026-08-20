# Convenience container. The primary tested path is: uv run zarin
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY zarin ./zarin
COPY pipeline ./pipeline
RUN pip install --no-cache-dir uv && uv pip install --system .
EXPOSE 8630
ENV ZARIN_DATA_PATH=/app/data/other_challenge_data.csv.gz
ENV ZARIN_HOST=0.0.0.0
CMD ["python", "-m", "zarin"]
