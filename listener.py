import asyncio
from inspect import trace
import logging
import os
import traceback

#from numpy import block

import aiohttp

import time
import datetime as dt
from mev_inspect.block import get_latest_block_number
from mev_inspect.concurrency import coro
from mev_inspect.crud.latest_block_update import (
    find_latest_block_update,
    update_latest_block,
    close_active_connections
)
from mev_inspect.db import get_inspect_session, get_trace_session
from mev_inspect.inspector import MEVInspector
from mev_inspect.provider import get_base_provider
from mev_inspect.signal_handler import GracefulKiller
from mev_inspect.utils import RPCType



logging.basicConfig(filename="listener.log", filemode="a", level=logging.INFO)
logger = logging.getLogger(__name__)

# lag to make sure the blocks we see are settled
BLOCK_NUMBER_LAG = 5


@coro
async def run():
    rpc = os.getenv("RPC_URL")
    print(rpc)
    if rpc is None:
        raise RuntimeError("Missing environment variable RPC_URL")

    healthcheck_url = os.getenv("LISTENER_HEALTHCHECK_URL")

    logger.info("Starting...")

    killer = GracefulKiller()

    inspect_db_session = get_inspect_session()
    trace_db_session = get_trace_session()

    inspector = MEVInspector(rpc, inspect_db_session, trace_db_session, type=RPCType.geth)
    base_provider = get_base_provider(rpc)
    
    while not killer.kill_now:
        #try:
        await inspect_next_block(
            inspector,
            inspect_db_session,
            trace_db_session,
            base_provider,
            healthcheck_url,
        )
        #except:
        #    logger.error(dt.datetime.now())
        #    logger.error(traceback.format_exc())
        #    await asyncio.sleep(5)


    logger.info("Stopping...")


async def inspect_next_block(
    inspector: MEVInspector,
    inspect_db_session,
    trace_db_session,
    base_provider,
    healthcheck_url,
):
    latest_block_number = await get_latest_block_number(base_provider)
    last_written_block = find_latest_block_update(inspect_db_session)

    logger.info(f"Latest block: {latest_block_number}")
    logger.info(f"Last written block: {last_written_block}")

    if last_written_block is None:
        # maintain lag if no blocks written yet
        last_written_block = latest_block_number - BLOCK_NUMBER_LAG - 1

    if last_written_block < (latest_block_number - BLOCK_NUMBER_LAG):

        block_number = last_written_block + 1

        logger.info(f"Writing block: {block_number}")
        print(f"Writing block: {block_number}")
        try:
            await inspector.inspect_single_block(
                inspect_db_session=inspect_db_session,
                trace_db_session=trace_db_session,
                block=block_number,
            )

            update_latest_block(inspect_db_session, block_number)

            if healthcheck_url: 
                await ping_healthcheck_url(healthcheck_url)
        except Exception as e:
            logger.error(traceback.format_exc())
            print(block_number)
            logger.info('Skipping block: ' + str(block_number))
            update_latest_block(inspect_db_session, block_number)
            close_active_connections(inspect_db_session)

        #logger.error(type(e))
        #update_latest_block(inspect_db_session, block_number)

    else:
        logger.warning('Sleeping 5 sec')
        await asyncio.sleep(5)


async def ping_healthcheck_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url):
            pass


if __name__ == "__main__":
    while True:
        try:
            print('Running')
            run()
        except Exception as e:
            traceback.print_exc()
            logger.error(traceback.format_exc())
            logger.error('Sleeping 5mins...')
            logger.error(dt.datetime.now())
            time.sleep(60*5)
        
