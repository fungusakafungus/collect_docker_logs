#!/usr/bin/env python2

from kubernetes import client, config, watch
from multiprocessing import Process
from inotifyx import init, IN_MODIFY, add_watch, rm_watch, get_events


POD_WATCHES = {}

def pod_watch(pod):
    c0 = pod.status.container_statuses[0]
    container_id = c0.container_id.replace('docker://', '')
    print open('/var/lib/docker/containers/%s/%s-json.log' % (container_id, container_id)).read()


def start_pod_watch(pod):
    p = Process(target=pod_watch, args=(pod,))
    p.start()
    POD_WATCHES[pod.metadata.uid] = p


def stop_pod_watch(pod):
    p = POD_WATCHES[pod.metadata.uid]
    p.terminate()
    p.join(1)
    del POD_WATCHES[pod.metadata.uid]


def main():
    try:
        config.load_kube_config()
    except IOError:
        config.load_incluster_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    for i in w.stream(v1.list_pod_for_all_namespaces):
        type_ = i['type']
        i = i['object']
        print("%s\t%s\t%s\t%s" % (i.status.pod_ip, i.metadata.namespace, i.metadata.name, [s.container_id for s in i.status.container_statuses]))
        if type_ == 'ADDED':
            start_pod_watch(i)
        elif type_ == 'DELETED':
            stop_pod_watch(i)
        elif type_ == 'MODIFIED':
            pass
        else:
            raise RuntimeError('Unhandled type ' + type_)



if __name__ == '__main__':
    import sys
    sys.exit(main())
