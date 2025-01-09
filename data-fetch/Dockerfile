FROM python:3.10-slim
WORKDIR /app
COPY fetch_github_data.py /app/fetch_github_data.py
RUN pip install --no-cache-dir PyGithub==1.58.1 pymongo==4.6.0 requests==2.31.0 hvac==0.11.2
CMD ["python","/app/fetch_github_data.py"]
