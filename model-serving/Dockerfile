FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY serve_model.py /app/serve_model.py
CMD ["python","/app/serve_model.py"]
