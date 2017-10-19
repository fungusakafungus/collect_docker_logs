#!/usr/bin/env python3

import json
import asyncio
import pyinotify
import logging
import graypy.handler
graypy.handler.make_message_dict = lambda x, *args: x  # get out of my way


LOGGER = logging.getLogger()
INOTIFY_WATCH_MANAGER = pyinotify.WatchManager()
CONTAINER_WATCHES = {}
PODS = {}
OPEN_FILES = {}
GL_HANDLER = None
CLUSTER = None


class AsyncIteratorExecutor:
    """
    Converts a regular iterator into an asynchronous
    iterator, by executing the iterator in a thread.

    see "Adapting regular iterators to asynchronous iterators in python" blog
    post at
    https://blogs.gentoo.org/zmedico/2016/09/17/adapting-regular-iterators-to-asynchronous-iterators-in-python/
    """
    def __init__(self, iterator, loop=None, executor=None):
        self._iterator = iterator
        self._loop = loop or asyncio.get_event_loop()
        self._executor = executor

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self._loop.run_in_executor(self._executor, next, self._iterator, self)
        if value is self:
            raise StopAsyncIteration
        return value


def find_container_status_in_pod(pod, container_id):
    for cs in pod.status.container_statuses:
        if container_id in cs.container_id:
            return cs
    LOGGER.warn('Container status for %s not found in pod %s',
                container_id, pod.metadata.name)
    return None


def process_log_entry(log_entry, pod, container_id):
    LOGGER.info('%s %s',
                pod.metadata.name,
                log_entry['log'].strip())
    gl_event = dict(
        version="1.1",
        host=pod.spec.node_name or pod.metadata.name,
        short_message=log_entry['log'],
        timestamp=log_entry['time'],
        level=6,

        _cluster=CLUSTER,
        _namespace=pod.metadata.namespace,
    )
    container_status = find_container_status_in_pod(pod, container_id)
    if container_status:
        gl_event['_container_image'] = container_status.image
        gl_event['_container_restart_count'] = container_status.restart_count
        if container_status.name:
            gl_event['_container_name'] = container_status.name
            container_spec = [
                c for c in pod.spec.containers
                if c.name == container_status.name
            ]
            if len(container_spec) == 1:
                container_spec = container_spec[0]

    pickle = GL_HANDLER.makePickle(gl_event)
    GL_HANDLER.send(pickle)


class EventHandler(pyinotify.ProcessEvent):

    def __init__(self, fname, pod, container_id):
        pyinotify.ProcessEvent.__init__(self)
        self.fname = fname
        self.pod = pod
        self.container_id = container_id
        self.file = None

    def process_IN_MODIFY(self, event):
        LOGGER.debug('processing %s', self.fname)
        if not self.file:
            try:
                self.file = open(self.fname)
                self.file.seek(0, 2)  # seek to end
            except FileNotFoundError:
                LOGGER.debug('FileNotFound %s', self.fname)
                return
        line = self.file.readline()
        while line:
            log_entry = json.loads(line)
            process_log_entry(log_entry, self.pod, self.container_id)
            line = self.file.readline()


def process_file(open_file, fname):
    import json
    LOGGER.debug('processing %s', fname)
    line = open_file.readline()
    while line:
        LOGGER.info(json.loads(line)['time'].strip())
        LOGGER.info(json.loads(line)['log'].strip())
        line = open_file.readline()

def process_IN_MODIFY(event):
    fname = event.pathname
    LOGGER.debug("IN_MODIFY %s", fname)
    open_file = OPEN_FILES.get(fname)
    if not open_file:
        LOGGER.debug('event for %s, opening file', fname)
        open_file = OPEN_FILES[fname] = open(fname)
        open_file.seek(0, 2)  # seek to end
    process_file(open_file, fname)


def start_container_watch(container_id, pod):
    log_filename = '/var/lib/docker/containers/%s/%s-json.log' % (
        container_id, container_id)
    LOGGER.info('starting container watch %s:%s', pod.metadata.name, container_id)
    wdd = INOTIFY_WATCH_MANAGER.add_watch(
        log_filename,
        pyinotify.IN_MODIFY,
        EventHandler(log_filename, pod, container_id),
    )
    CONTAINER_WATCHES.update(wdd)
    LOGGER.info("# CONTAINER_WATCHES after: %s", len(CONTAINER_WATCHES))


def stop_container_watch(container_id):
    log_filename = '/var/lib/docker/containers/%s/%s-json.log' % (
        container_id, container_id)
    print('terminating watch for ' + container_id)
    wd = CONTAINER_WATCHES[log_filename]
    INOTIFY_WATCH_MANAGER.rm_watch(wd, pyinotify.IN_MODIFY)
    del CONTAINER_WATCHES[log_filename]
    LOGGER.info("# CONTAINER_WATCHES after: %s", len(CONTAINER_WATCHES))


def start_pod_watch(pod):
    if pod.metadata.uid in PODS:
        LOGGER.info('pod %s already started', pod.metadata.name)
        return
    LOGGER.info('starting pod %s', pod.metadata.name)
    PODS[pod.metadata.uid] = set()
    update_pod_watch(pod)


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


async def watch_pods(loop):
    global KUBERNETES_POD_WATCH
    from kubernetes import client, config, watch
    try:
        config.load_kube_config()
    except IOError:
        config.load_incluster_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    while True:
        async for pod in AsyncIteratorExecutor(w.stream(v1.list_pod_for_all_namespaces)):
            type_ = pod['type']
            pod = pod['object']
            LOGGER.info('pod event %s %s', pod.metadata.name, type_)
            if type_ == 'ADDED':
                start_pod_watch(pod)
            elif type_ == 'DELETED':
                stop_pod_watch(pod)
            elif type_ == 'MODIFIED':
                update_pod_watch(pod)
            else:
                raise RuntimeError('Unhandled type ' + type_)


def main(args):
    global GL_HANDLER, CLUSTER
    assert len(args) == 3, "Two arguments, graylog_ip cluster_name"
    gl_ip = args[1]
    CLUSTER = args[2]
    GL_HANDLER = graypy.handler.GELFHandler(gl_ip)

    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    loop = asyncio.get_event_loop()
    loop.set_default_executor(executor)
    loop.set_debug(True)
    notifier = pyinotify.AsyncioNotifier(
        INOTIFY_WATCH_MANAGER,
        loop=loop,
    )
    loop.create_task(watch_pods(loop))
    try:
        loop.run_forever()
    finally:
        import os, traceback, faulthandler
        faulthandler.dump_traceback(all_threads=True)
        traceback.print_exc()
        os.killpg(os.getpgrp(), 15)


if __name__ == '__main__':
    import logging
    import sys
    logging.basicConfig(
        level=logging.WARN,
        format="%(filename)s:%(lineno)-4s %(levelname)5s %(funcName)s: %(message)s"
    )
    main(sys.argv)
