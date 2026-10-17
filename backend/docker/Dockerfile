FROM python:3.12-slim

RUN python -m pip install --no-cache-dir pandas==2.3.3 matplotlib==3.10.7 tabulate==0.9.0 \
    && useradd --uid 1000 --create-home --shell /bin/bash agentloom

USER 1000:1000
WORKDIR /mnt/user-data/workspace

CMD ["python", "--version"]
