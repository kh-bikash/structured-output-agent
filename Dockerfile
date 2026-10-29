FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir . && useradd --uid 10001 --create-home app && mkdir -p /data && chown app:app /data
USER app
ENV AGENT_WEB_HOST=0.0.0.0
EXPOSE 8080
ENTRYPOINT ["python","-m","structured_output_agent"]
