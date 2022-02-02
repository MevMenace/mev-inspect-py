import logging
import os
import sys
from datetime import datetime

import click

from mev_inspect.concurrency import coro
from mev_inspect.crud.prices import write_prices
from mev_inspect.db import get_inspect_session, get_trace_session
from mev_inspect.inspector import MEVInspector
from mev_inspect.prices import fetch_prices, fetch_prices_range
from mev_inspect.utils import RPCType
#from mev_inspect.prices import fetch_all_supported_prices

RPC_URL_ENV = "RPC_URL"

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("block_number", type=int)
@click.option("--rpc", default=lambda: os.environ.get(RPC_URL_ENV, ""))
@click.option(
    "--type",
    type=click.Choice(list(map(lambda x: x.name, RPCType)), case_sensitive=False),
    default=RPCType.parity.name,
)
@coro
async def inspect_block_command(block_number: int, rpc: str, type: str):
    type_e = convert_str_to_enum(type)
    inspect_db_session = get_inspect_session()
    trace_db_session = get_trace_session()

    #inspector = MEVInspector(rpc)
    inspector = MEVInspector(rpc, inspect_db_session, trace_db_session, type_e)


    await inspector.inspect_single_block(
        inspect_db_session=inspect_db_session,
        trace_db_session=trace_db_session,
        block=block_number,
    )
    #await inspector.inspect_single_block(block=block_number)


def convert_str_to_enum(type: str) -> RPCType:
    if type == "parity":
        return RPCType.parity
    elif type == "geth":
        return RPCType.geth
    raise ValueError


@cli.command()
@click.argument("block_number", type=int)
@click.option("--rpc", default=lambda: os.environ.get(RPC_URL_ENV, ""))
@coro
async def fetch_block_command(block_number: int, rpc: str):
    trace_db_session = get_trace_session()

    #inspector = MEVInspector(rpc)
    inspector = MEVInspector(rpc, inspect_db_session, trace_db_session, RPCType.parity)
    block = await inspector.create_from_block(
        block_number=block_number,
        trace_db_session=trace_db_session,
    )

    
    #block = await inspector.create_from_block(block_number=block_number)
    print(block.json())


@cli.command()
@click.argument("after_block", type=int)
@click.argument("before_block", type=int)
@click.option("--rpc", default=lambda: os.environ.get(RPC_URL_ENV, ""))
@click.option(
    "--type",
    type=click.Choice(list(map(lambda x: x.name, RPCType)), case_sensitive=False),
    default=RPCType.parity.name,
)
@click.option(
    "--max-concurrency",
    type=int,
    help="maximum number of concurrent connections",
    default=5,
)
@click.option(
    "--request-timeout", type=int, help="timeout for requests to nodes", default=500
)
@coro
async def inspect_many_blocks_command(
    after_block: int,
    before_block: int,
    rpc: str,
    max_concurrency: int,
    request_timeout: int,
    type: str,
):
    type_e = convert_str_to_enum(type)
    inspect_db_session = get_inspect_session()
    trace_db_session = get_trace_session()
    inspector = MEVInspector(
        rpc,
        inspect_db_session,
        trace_db_session,
        type_e,
        max_concurrency=max_concurrency,
        request_timeout=request_timeout,
    )
    await inspector.inspect_many_blocks(
        inspect_db_session=inspect_db_session,
        trace_db_session=trace_db_session,
        after_block=after_block,
        before_block=before_block,
    )


@cli.command()
@click.argument("after_block", type=int)
@click.argument("before_block", type=int)
@click.argument("batch_size", type=int, default=10)
def enqueue_many_blocks_command(after_block: int, before_block: int, batch_size: int):
    from worker import (  # pylint: disable=import-outside-toplevel
        inspect_many_blocks_task,
    )

    for batch_after_block in range(after_block, before_block, batch_size):
        batch_before_block = min(batch_after_block + batch_size, before_block)
        logger.info(f"Sending {batch_after_block} to {batch_before_block}")
        inspect_many_blocks_task.send(batch_after_block, batch_before_block)


@cli.command()
def fetch_all_prices():
    inspect_db_session = get_inspect_session()

    logger.info("Fetching prices")
    prices = fetch_prices()

    logger.info("Writing prices")
    write_prices(inspect_db_session, prices)


@cli.command()
@click.argument("after", type=click.DateTime(formats=["%Y-%m-%d", "%m-%d-%Y"]))
@click.argument("before", type=click.DateTime(formats=["%Y-%m-%d", "%m-%d-%Y"]))
def fetch_range(after: datetime, before: datetime):
    inspect_db_session = get_inspect_session()

    logger.info("Fetching prices")
    prices = fetch_prices_range(after, before)

    logger.info("Writing prices")
    write_prices(inspect_db_session, prices)


def get_rpc_url() -> str:
    return os.environ["RPC_URL"]


if __name__ == "__main__":
    cli()
