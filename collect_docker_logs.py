#!/usr/bin/env python2

import os

from kubernetes import client, config, watch
from multiprocessing import Process
from inotifyx import init, IN_MODIFY, add_watch, rm_watch, get_events
from setproctitle import setproctitle, getproctitle
import json


CONTAINER_WATCHES = {}
PODS = {}


def container_watch(container_id, pod):
    setproctitle(getproctitle() + ' ' + container_id)
    log_filename = '/var/lib/docker/containers/%s/%s-json.log' % (
        container_id, container_id)
    ifd = init()
    try:
        log_file = open(log_filename)
        log_file.seek(0, 2)  # seek to end
        watch = add_watch(ifd, log_filename, IN_MODIFY)
        while container_id in PODS[pod.metadata.uid]:
            get_events(ifd, 5)
            line = log_file.readline()
            while line:
                print pod.metadata.name, ': ', json.loads(line)['log'],
                line = log_file.readline()
    finally:
        rm_watch(ifd, watch)
        os.close(ifd)
        log_file.close()


def start_container_watch(container_id, pod):
    p = Process(target=container_watch, args=(container_id, pod))
    p.name += ' ' + container_id
    p.start()
    CONTAINER_WATCHES[container_id] = p


def start_pod_watch(pod):
    PODS[pod.metadata.uid] = set()


def stop_pod_watch(pod):
    for c in PODS[pod.metadata.uid]:
        stop_container_watch(c)
    del PODS[pod.metadata.uid]


def update_pod_watch(pod):
    try:
        assert pod.status.container_statuses
        api_container_ids = set(c.container_id.replace('docker://', '')
                                for c in pod.status.container_statuses)
    except (AttributeError, AssertionError):
        return
    local_container_ids = PODS[pod.metadata.uid]
    to_stop, to_start = (local_container_ids - api_container_ids,
                         api_container_ids - local_container_ids)
    PODS[pod.metadata.uid] = api_container_ids
    for container_id in to_stop:
        stop_container_watch(container_id)
    for container_id in to_start:
        start_container_watch(container_id, pod)


def stop_container_watch(container_id):
    print 'terminating ' + container_id
    p = CONTAINER_WATCHES[container_id]
    p.terminate()
    p.join(1)
    del CONTAINER_WATCHES[container_id]


def main():
    try:
        config.load_kube_config()
    except IOError:
        config.load_incluster_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    while True:
        for pod in v1.list_pod_for_all_namespaces().items:
            start_pod_watch(pod)
            update_pod_watch(pod)
        for pod in w.stream(v1.list_pod_for_all_namespaces):
            type_ = pod['type']
            pod = pod['object']
            if pod.status.container_statuses:
                container_ids = [s.container_id
                                 for s in pod.status.container_statuses]
            else:
                container_ids = ''
            print("%s\t%s\t%s\t%s" % (pod.status.pod_ip, pod.metadata.namespace,
                                      pod.metadata.name, container_ids))
            if type_ == 'ADDED':
                start_pod_watch(pod)
            elif type_ == 'DELETED':
                stop_pod_watch(pod)
            elif type_ == 'MODIFIED':
                update_pod_watch(pod)
            else:
                raise RuntimeError('Unhandled type ' + type_)


if __name__ == '__main__':
    import sys
    sys.exit(main())
