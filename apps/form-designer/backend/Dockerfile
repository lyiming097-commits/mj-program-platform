ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY apps/form-designer/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/platform-backend /platform-backend
COPY apps/form-designer/backend /app
ENV PYTHONPATH=/platform-backend PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "entrypoint.py"]
