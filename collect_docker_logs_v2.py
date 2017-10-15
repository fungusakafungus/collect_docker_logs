#!/usr/bin/env python3

import json
import asyncio


LOGGER = logging.getLogger()
INOTIFY_WATCH_MANAGER = =pyinotify.WatchManager()


def start_container_watch(container_id, pod):
    log_filename = '/var/lib/docker/containers/%s/%s-json.log' % (
        container_id, container_id)
    LOGGER.info('starting container %s:%s' % (pod.metadata.name, container_id))
    container_watch(container_id, pod)


def start_pod_watch(pod):
    if pod.metadata.uid in PODS:
        LOGGER.info('pod %s already started' % pod.metadata.name)
        return
    LOGGER.info('starting pod ' + pod.metadata.name)
    PODS[pod.metadata.uid] = set()


def update_pod_watch(pod):
    if not pod.status.container_statuses: return
    api_container_ids = set(c.container_id.replace('docker://', '')
                            for c in pod.status.container_statuses
                            if c.container_id)
    local_container_ids = PODS[pod.metadata.uid]
    to_stop, to_start = (local_container_ids - api_container_ids,
                         api_container_ids - local_container_ids)
    LOGGER.debug('local_container_ids %s', local_container_ids)
    LOGGER.debug('to_stop %s', to_stop)
    LOGGER.debug('to_start %s', to_start)
    LOGGER.debug([c for c in pod.status.container_statuses
                 if c.container_id and
                 c.container_id.replace('docker://', '') in to_start])
    PODS[pod.metadata.uid] = api_container_ids
    for container_id in to_stop:
        stop_container_watch(container_id)
    for container_id in to_start:
        start_container_watch(container_id, pod)


async def watch_pods():
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
            LOGGER.info(pod.metadata.name, type_)
            if type_ == 'ADDED':
                start_pod_watch(pod)
            elif type_ == 'DELETED':
                stop_pod_watch(pod)
            elif type_ == 'MODIFIED':
                update_pod_watch(pod)
            else:
                raise RuntimeError('Unhandled type ' + type_)
            await asyncio.sleep(0)


def main():
    loop = asyncio.get_event_loop()
    loop.create_task()
    loop.run_forever()


if __name__ == '__main__':
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(filename)s:%(lineno)-4s %(levelname)5s %(funcName)s: %(message)s"
    )
    main()
