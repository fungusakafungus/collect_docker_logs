# coding: utf-8
import pyinotify
import asyncio
import kubernetes
wm=pyinotify.WatchManager()
mask = pyinotify.IN_MODIFY
print(wm.add_watch('log', pyinotify.IN_MODIFY))
print(wm.add_watch('log', pyinotify.IN_MODIFY))
print(wm.add_watch('log2', pyinotify.IN_MODIFY))
print(wm.add_watch('log', pyinotify.IN_MODIFY))
loop = asyncio.get_event_loop()
def process_IN_MODIFY(event):
    print("IN_MODIFY %s" % event.pathname)

notifier = pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=process_IN_MODIFY)
async def sleep_print():
    while True:
        await asyncio.sleep(0.2)
        print('slept')
loop.create_task(sleep_print())
loop.run_forever()
