Collect docker logs
===================

Forwards logs of kubernetes pods to Graylog. This script is a smaller replacement for [Fluentd](https://docs.fluentd.org/v0.12/articles/kubernetes-fluentd).

In the same way as fluentd, `collect_docker_logs` runs in your kubernetes cluster as a DaemonSet and tails logs produced by the default Docker `json-file` driver.

Logs are enriched with kubernetes metadata, like pod name, namespace etc. and sent to Graylog via UDP.

Graylog fields are set in [process_log_entry function](https://github.com/fungusakafungus/collect_docker_logs/blob/master/collect_docker_logs.py).

It uses python3 for asyncio magic and pyinotify for log tailing. It does not talk to docker API. It is not a logging layer or infrastructure solution, it is a python script.
