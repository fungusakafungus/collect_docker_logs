Collect docker logs
===================

Watches logs of pods/containers discovered via kubernetes API via inotify.

Logs are enriched with kubernetes metadata and sent to Graylog via UDP. Graylog fields are set in [process_log_entry function](https://github.com/fungusakafungus/collect_docker_logs/blob/master/collect_docker_logs.py#L65).

It uses asyncio, so memory footprint is small, about 35k per pod.
