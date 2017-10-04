Collect docker logs
===================

Watches logs of pods/containers discovered via kubernetes API via inotify.

I plan to enrich the logs with kubernetes metadata and send them to Graylog.

Currently it starts a multiprocessing.Process per container. Observed memory usage is around 5Mb per container. (100 containers result in about 500Mb used)
