#!/bin/bash -x

if [[ $(minikube status --format={{.ClusterStatus}}) != Running ]]; then
	minikube start
fi
kubectl config use-context minikube-system
test -z "$DOCKER_API_VERSION" || eval $(minikube docker-env)
cat deploy.yaml.tmpl | sed 's#$PWD#'$PWD'#' | kubectl apply -f-
VENV_POD=$(kubectl -oname get pod -lrun=venv | sed 's#.*/##')
test -z "$VENV_POD" && { echo no venv pod; exit 2;}
kubectl exec -ti $VENV_POD -- ./collect_docker_logs.py $@
