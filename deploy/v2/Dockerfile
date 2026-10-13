FROM python:3.12-slim
WORKDIR /opt/xfagent
COPY requirements-v2.lock /tmp/requirements-v2.lock
RUN pip install --no-cache-dir -r /tmp/requirements-v2.lock
ENV PYTHONUNBUFFERED=1
