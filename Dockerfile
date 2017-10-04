FROM debian:stretch

RUN apt-get update -y
RUN apt-get install -y python python-inotifyx

RUN apt-get install -y python-six
RUN apt-get install -y python-urllib3
RUN apt-get install -y python-websocket
RUN apt-get install -y python-requests

RUN apt-get install -y python-virtualenv
RUN apt-get install -y python-graypy
RUN apt-get install -y python-setproctitle
RUN virtualenv --system-site-packages /usr/local
ADD requirements.txt .
RUN /usr/local/bin/pip install -r requirements.txt
RUN /usr/local/bin/python -mkubernetes.client.api_client
WORKDIR /code
