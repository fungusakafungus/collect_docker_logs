#!/usr/bin/env python3
# encoding: utf-8

import json
import asyncio
import pyinotify
import logging
import re
import graypy.handler
import dateutil.parser



LOGGER = logging.getLogger()
APPLICATION_NAME = None

NEW_PODS = set()  # of pod uids


class AsyncIteratorExecutor:
    """
    Converts a regular iterator into an asynchronous
    iterator, by executing the iterator in a thread.

    see "Adapting regular iterators to asynchronous iterators in python" blog
    post at
    https://blogs.gentoo.org/zmedico/2016/09/17/adapting-regular-iterators-to-asynchronous-iterators-in-python/
    """
    def __init__(self, iterator):
        self._iterator = iterator

    def __aiter__(self):
        return self

    async def __anext__(self):
        # call next(self._iterator, self) in a thread. self will be returned
        # when the iterator is exhausted
        value = await asyncio.get_event_loop().run_in_executor(
            None,  # default executor
            next,
            self._iterator,
            self
        )
        # self is returned by next() to communicate end of iteration
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


graypy.handler.make_message_dict = lambda x, *args: x  # get out of my way

class GraylogForwarder(graypy.handler.GELFHandler):

    def __init__(self, graylog_host, cluster_name):
        graypy.handler.GELFHandler.__init__(self, graylog_host)
        self.cluster_name = cluster_name

    def process_log_entry(self, log_entry, pod, container_id):
        good_label_re = re.compile('[a-z-]*')  # we are very picky here
        boring_labels = 'pod-template-hash',
        LOGGER.info('%s %s',
                    pod.metadata.name,
                    log_entry['log'].strip())
        gl_event = dict(
            version="1.1",
            host=pod.spec.node_name or pod.metadata.name,
            short_message=log_entry['log'],
            timestamp=dateutil.parser.parse(log_entry['time']).timestamp(),
            level=6,
            _application_name=APPLICATION_NAME,
            _name=pod.metadata.name,

            _cluster=self.cluster_name,
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
        if pod.metadata.labels:
            for k, v in pod.metadata.labels.items():
                if k in boring_labels:
                    continue
                if not good_label_re.fullmatch(k):
                    continue
                k = k.replace('-', '_')
                k = '_pod_label_' + k
                gl_event[k] = v

        pickle = self.makePickle(gl_event)
        self.send(pickle)


class INotifyHandler(pyinotify.ProcessEvent):

    def __init__(self, graylog_forwarder, fname, pod, container_id, seek_to_end):
        pyinotify.ProcessEvent.__init__(self)
        self.graylog_forwarder = graylog_forwarder
        self.fname = fname
        self.pod = pod
        self.container_id = container_id
        self.file = None
        self.seek_to_end = seek_to_end

    def process_IN_MODIFY(self, event):
        LOGGER.debug('processing %s', self.fname)
        if not self.file:
            try:
                self.file = open(self.fname, encoding="utf-8")
                if self.seek_to_end:
                    # seek to end for old pods
                    self.file.seek(0, 2)
            except FileNotFoundError:
                LOGGER.debug('FileNotFound %s', self.fname)
                return
        line = self.file.readline()
        while line:
            log_entry = json.loads(line)
            self.graylog_forwarder.process_log_entry(log_entry, self.pod, self.container_id)
            line = self.file.readline()


class PodWatchManager(pyinotify.WatchManager):

    log_path_pattern = '/var/lib/docker/containers/{0}/{0}-json.log'

    def __init__(self, graylog_forwarder, my_node_name):
        pyinotify.WatchManager.__init__(self)
        self.graylog_forwarder = graylog_forwarder
        self.my_node_name = my_node_name
        self.container_watches = {}
        self.pods = {}

        # Pods are considered new if they appeared during runtime of the script.
        # In that case their whole log is sent to graylog. Otherwise only newly added
        # lines are sent.
        self.old_pods = set()

    def start_container_watch(self, container_id, pod):
        log_filename = self.log_path_pattern.format(container_id)
        LOGGER.info('starting container watch %s:%s', pod.metadata.name, container_id)
        seek_to_end = pod.metadata.uid in self.old_pods
        wdd = self.add_watch(
            log_filename,
            pyinotify.IN_MODIFY,
            INotifyHandler(self.graylog_forwarder, log_filename, pod, container_id, seek_to_end),
        )
        self.container_watches.update(wdd)
        LOGGER.info("# CONTAINER_WATCHES after: %s", len(self.container_watches))


    def stop_container_watch(self, container_id):
        log_filename = self.log_path_pattern.format(container_id)
        LOGGER.info('terminating watch for ' + container_id)
        wd = self.container_watches[log_filename]
        self.rm_watch(wd, pyinotify.IN_MODIFY)
        del self.container_watches[log_filename]
        LOGGER.info("# CONTAINER_WATCHES after: %s", len(self.container_watches))


    def start_pod_watch(self, pod):
        if pod.metadata.uid in self.pods:
            LOGGER.info('pod %s already started', pod.metadata.name)
            return
        LOGGER.info('starting pod %s', pod.metadata.name)
        self.pods[pod.metadata.uid] = set()
        self.update_pod_watch(pod)


    def stop_pod_watch(self, pod):
        LOGGER.info('stopping pod ' + pod.metadata.name)
        for c in self.pods[pod.metadata.uid]:
            self.stop_container_watch(c)
        del self.pods[pod.metadata.uid]


    def update_pod_watch(self, pod):
        if not pod.status.container_statuses: return
        if pod.spec.node_name != self.my_node_name: return

        api_container_ids = set(c.container_id.replace('docker://', '')
                                for c in pod.status.container_statuses
                                if c.container_id)
        local_container_ids = self.pods[pod.metadata.uid]
        to_stop, to_start = (local_container_ids - api_container_ids,
                            api_container_ids - local_container_ids)
        LOGGER.debug('local_container_ids %s', local_container_ids)
        LOGGER.debug('to_stop %s', to_stop)
        LOGGER.debug('to_start %s', to_start)
        LOGGER.debug([c for c in pod.status.container_statuses
                    if c.container_id and
                    c.container_id.replace('docker://', '') in to_start])
        self.pods[pod.metadata.uid] = api_container_ids
        for container_id in to_stop:
            self.stop_container_watch(container_id)
        for container_id in to_start:
            self.start_container_watch(container_id, pod)


async def watch_pods(pod_watch_manager):
    from kubernetes import client, config, watch
    try:
        config.load_kube_config()
    except IOError:
        config.load_incluster_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    while True:
        for pod in v1.list_pod_for_all_namespaces().items:
            pod_watch_manager.old_pods.add(pod.metadata.uid)
        async for pod in AsyncIteratorExecutor(w.stream(v1.list_pod_for_all_namespaces)):
            type_ = pod['type']
            pod = pod['object']
            LOGGER.info('pod event %s %s', pod.metadata.name, type_)
            if type_ == 'ADDED':
                pod_watch_manager.start_pod_watch(pod)
            elif type_ == 'DELETED':
                pod_watch_manager.stop_pod_watch(pod)
            elif type_ == 'MODIFIED':
                pod_watch_manager.update_pod_watch(pod)
            else:
                raise RuntimeError('Unhandled type ' + type_)


def find_myself():
    import socket
    from kubernetes import client, config, watch
    try:
        config.load_kube_config()
    except IOError:
        config.load_incluster_config()
    v1 = client.CoreV1Api()
    pod = v1.read_namespaced_pod(socket.gethostname(), 'kube-system')
    return pod.spec.node_name


def main(args):
    global CLUSTER, NODE_NAME
    my_node_name = find_myself()

    graylog_forwarder = GraylogForwarder(args.graylog_host, args.cluster_name)
    pod_watch_manager = PodWatchManager(graylog_forwarder, my_node_name)


    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    loop = asyncio.get_event_loop()
    loop.set_default_executor(executor)
    if args.verbose > 0:
        loop.set_debug(True)
    pyinotify.AsyncioNotifier(pod_watch_manager, loop=loop)
    task = loop.create_task(watch_pods(pod_watch_manager))
    try:
        loop.run_until_complete(task)
    finally:
        import os, traceback, faulthandler
        faulthandler.dump_traceback(all_threads=True)
        traceback.print_exc()
        os.killpg(os.getpgrp(), 15)


if __name__ == '__main__':
    import logging
    import sys
    import argparse
    APPLICATION_NAME = sys.argv[0]
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="count", default=0)
    parser.add_argument("graylog_host", help="where to send logs")
    parser.add_argument("cluster_name", help="cluster name, will be used as field 'cluster'")
    args = parser.parse_args()
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose > 1:
        level = logging.DEBUG
    else:
        level = logging.WARN
    logging.basicConfig(
        level=level,
        format="%(filename)s:%(lineno)-4s %(levelname)5s %(funcName)s: %(message)s"
    )

    main(args)
