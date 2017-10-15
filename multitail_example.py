#!/usr/bin/env python2

import os
from multiprocessing import Process, Queue
from queue import Empty
import logging

import inotifyx


ADD, REMOVE = 1, 2
log = logging.getLogger('')


class Bidict(dict):
    def __setitem__(self, k, v):
        dict.__setitem__(self, k, v)
        dict.__setitem__(self, v, k)

    def __delitem__(self, k):
        v = self[k]
        dict.__delitem__(self, k)
        dict.__delitem__(self, v)


def process_q_names(q_names, fd, watches, open_files):
    i = 0
    try:
        for i, (op, fname) in enumerate(iter(q_names.get_nowait, None)):
            if op == ADD:
                log.debug('op ADD %s', fname)
                if fname in watches:
                    log.debug('op ADD %s already added', fname)
                    continue
                watch_id = inotifyx.add_watch(fd, fname, inotifyx.IN_MODIFY)
                watches[watch_id] = fname
            elif op == REMOVE:
                log.debug('op REMOVE %s', fname)
                watch_id = watches[fname]
                if not watch_id:
                    log.debug('op REMOVE %s already removed', fname)
                    continue
                inotifyx.rm_watch(fd, watch_id)
                del watches[watch_id]
                open_file = open_files.get(fname)
                if open_file:
                    open_file.close()
                    del open_files[fname]
    except Empty:
        pass
    finally:
        log.debug('processed %d names' % i)
        log.debug('watches: %s', watches)


def process_events(fd, watches, open_files):
    for event in inotifyx.get_events(fd, 1):  # time out after one second
        if event.mask & inotifyx.IN_IGNORED:
            log.debug('event %s, should be ignored', event)
            continue
        fname = watches.get(event.wd)
        if not fname:  # file shouldn't be watched anymore
            log.warn('event %s, whats going on?', event)
            continue

        open_file = open_files.get(fname)
        if not open_file:
            log.debug('event for %s, opening file', fname)
            open_file = open_files[fname] = open(fname)
            open_file.seek(0, 2)  # seek to end
        process_file(open_file, fname)


def process_file(open_file, fname):
    log.debug('processing %s', fname)
    line = open_file.readline()
    while line:
        print((fname, line))
        line = open_file.readline()


def watch_thread(q_names):
    watches = Bidict()
    fd = inotifyx.init()
    open_files = {}
    try:
        while True:
            process_q_names(q_names, fd, watches, open_files)
            process_events(fd, watches, open_files)
    finally:
        log.debug('watches: %s', watches)
        for fname_or_watch_id in watches:
            log.debug('cleanup fname_or_watch_id %s', fname_or_watch_id)
            if isinstance(fname_or_watch_id, int):  # it's a watch_id!
                inotifyx.rm_watch(fd, fname_or_watch_id)
        for fname, open_file in open_files.items():
            log.debug('cleanup open_file %s', fname)
            open_file.close()
        os.close(fd)


def sigchld_handler(_1, _2):
    import sys
    log.info("Got SIGCHLD, exiting")
    sys.exit()


def main():
    from time import sleep
    from signal import signal, SIGCHLD
    signal(SIGCHLD, sigchld_handler)
    q_names = Queue()
    q_names.put((ADD, '/var/log/dpkg.log'))
    watch = Process(target=watch_thread, args=(q_names,))
    watch.daemon = True
    watch.start()
    while True:
        # sleep(0.1)
        q_names.put((ADD, '/var/log/dpkg.log'))
        q_names.put((ADD, 'log'))
        q_names.put((ADD, 'log2'))
        sleep(0.1)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(filename)s:%(lineno)-4s %(levelname)5s %(funcName)s: %(message)s"
    )
    main()
