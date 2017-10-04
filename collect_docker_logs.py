#!/usr/bin/env python2
from __future__ import print_function

import json
from multiprocessing import Process

from setproctitle import setproctitle, getproctitle

import os


CONTAINER_WATCHES = {}
PODS = {}


def container_watch(container_id, pod):
    import inotifyx
    setproctitle(getproctitle() + ' ' + container_id)
    log_filename = '/var/lib/docker/containers/%s/%s-json.log' % (
        container_id, container_id)
    ifd = inotifyx.init()
    try:
        log_file = open(log_filename)
        log_file.seek(0, 2)  # seek to end
        watch = inotifyx.add_watch(ifd, log_filename, inotifyx.IN_MODIFY|inotifyx.IN_DELETE)
        while True:
            # next line blocks until file is modified or deleted
            deleted = any(e.mask & inotifyx.IN_DELETE for e in inotifyx.get_events(ifd, 5))
            if deleted:
                print('%s:%s: log deleted' % (pod.metadata.name, container_id))
                return
            line = log_file.readline()
            while line:
                print(pod.metadata.name, ': ', json.loads(line)['log'], end='')
                line = log_file.readline()
    finally:
        inotifyx.rm_watch(ifd, watch)
        os.close(ifd)
        log_file.close()


def start_container_watch(container_id, pod):
    if container_id in CONTAINER_WATCHES:
        if CONTAINER_WATCHES[container_id].is_alive():
            raise RuntimeError(
                'Container %s:%s already being watched, something is broken' %
                (pod.metadata.name, container_id)
            )
        else:
            print('watch for container %s:%s died, restarting')

    print('starting container %s:%s' % (pod.metadata.name, container_id))
    p = Process(target=container_watch, args=(container_id, pod),
                name='%s %s' % (pod.metadata.name, container_id))
    p.daemon = True
    CONTAINER_WATCHES[container_id] = p
    p.start()


def start_pod_watch(pod):
    if pod.metadata.uid in PODS:
        print('pod %s already started' % pod.metadata.name)
        return
    print('starting pod ' + pod.metadata.name)
    PODS[pod.metadata.uid] = set()


def stop_pod_watch(pod):
    print('stopping pod ' + pod.metadata.name)
    for c in PODS[pod.metadata.uid]:
        stop_container_watch(c)
    del PODS[pod.metadata.uid]


def update_pod_watch(pod):
    if not pod.status.container_statuses: return
    api_container_ids = set(c.container_id.replace('docker://', '')
                            for c in pod.status.container_statuses
                            if c.container_id)
    local_container_ids = PODS[pod.metadata.uid]
    to_stop, to_start = (local_container_ids - api_container_ids,
                         api_container_ids - local_container_ids)
    print('local_container_ids', local_container_ids)
    print('to_stop', to_stop)
    print('to_start', to_start)
    print([c for c in pod.status.container_statuses
           if c.container_id
           and c.container_id.replace('docker://', '') in to_start])
    PODS[pod.metadata.uid] = api_container_ids
    for container_id in to_stop:
        stop_container_watch(container_id)
    for container_id in to_start:
        start_container_watch(container_id, pod)


def stop_container_watch(container_id):
    print('terminating ' + container_id)
    p = CONTAINER_WATCHES[container_id]
    p.terminate()
    p.join(1)
    del CONTAINER_WATCHES[container_id]


def main():
    from kubernetes import client, config, watch
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
            print(pod.metadata.name, type_)
            if type_ == 'ADDED':
                start_pod_watch(pod)
            elif type_ == 'DELETED':
                stop_pod_watch(pod)
            elif type_ == 'MODIFIED':
                update_pod_watch(pod)
            else:
                raise RuntimeError('Unhandled type ' + type_)


if __name__ == '__main__':
    main()
