FROM debian:stretch

RUN apt-get update -y
RUN apt-get install -y python python-inotifyx
ADD .venv /usr/local

RUN apt-get install -y python-six
RUN apt-get install -y python-urllib3
RUN apt-get install -y python-websocket
RUN apt-get install -y python-requests
RUN /usr/local/bin/python -mkubernetes.client.api_client

