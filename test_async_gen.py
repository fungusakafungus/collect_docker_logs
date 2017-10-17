#!/usr/bin/env python3

import asyncio
from time import sleep
import logging

def gen1():
    while True:
        sleep(1)
        logging.info('slept 1')

        yield 1

def gen2():
    while True:
        sleep(2)
        logging.info('slept 2')
        yield 2

async def aiter(loop, gen):
    next_ = gen().__next__
    while True:
        yield await loop.run_in_executor(None, next_)


async def coro1(loop):
    logging.info('coro1 start')
    async for i in aiter(loop, gen1):
        logging.info('coro1')
#        asyncio.sleep(0)


async def coro2(loop):
    logging.info('coro2 start')
    async for i in aiter(loop, gen2):
        logging.info('coro2')
#        asyncio.sleep(0)

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)-4s %(levelname)5s %(funcName)s: %(message)s"
)
loop = asyncio.get_event_loop()
loop.create_task(coro1(loop))
loop.create_task(coro2(loop))
loop.run_forever()
