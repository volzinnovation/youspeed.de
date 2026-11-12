ARG WOLADEN_RUNTIME_IMAGE
FROM ${WOLADEN_RUNTIME_IMAGE}

USER root
COPY inspector/requirements.txt /tmp/inspector-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/inspector-requirements.txt
COPY inspector /opt/youspeed-inspector/inspector
COPY shared /opt/youspeed-inspector/shared
COPY iphone /opt/youspeed-inspector/iphone

WORKDIR /opt/youspeed-inspector
USER 10001:10001
ENTRYPOINT ["python", "inspector/server.py"]
