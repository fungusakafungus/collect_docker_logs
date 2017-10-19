FROM debian:stretch

RUN apt-get update -y
RUN apt-get install -y \
	python3-certifi \
	python3-dateutil \
	python3-graypy \
	python3-pyasn1 \
	python3-pyasn1-modules \
	python3-requests \
	python3-rsa \
	python3-six \
	python3-urllib3 \
	python3-websocket \
	python3-yaml \
	python3-pyinotify
RUN apt-get install -y virtualenv
RUN virtualenv --system-site-packages -p python3.5 /usr/local
ADD requirements.txt .
RUN /usr/local/bin/pip install -r requirements.txt
RUN /usr/local/bin/python -mkubernetes.client.api_client
ADD collect_docker_logs_v2.py /code/
WORKDIR /code
