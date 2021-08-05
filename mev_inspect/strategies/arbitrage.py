from typing import Dict, List, Optional

from mev_inspect.schemas.arbitrage import Arbitrage
from mev_inspect.schemas.classified_traces import (
    ClassifiedTrace,
    Classification,
)
from mev_inspect.schemas.swaps import Swap
from mev_inspect.schemas.transfers import Transfer


UNISWAP_V2_PAIR_ABI_NAME = "UniswapV2Pair"
UNISWAP_V3_POOL_ABI_NAME = "UniswapV3Pool"


def get_arbitrages(traces: List[ClassifiedTrace]) -> List[Arbitrage]:
    all_arbitrages = []
    traces_by_transaction = _group_traces_by_transaction(traces)

    for transaction_traces in traces_by_transaction.values():
        all_arbitrages += _get_arbitrages_for_transaction(
            transaction_traces,
        )

    return all_arbitrages


def _group_traces_by_transaction(
    traces: List[ClassifiedTrace],
) -> Dict[str, List[ClassifiedTrace]]:
    grouped_traces: Dict[str, List[ClassifiedTrace]] = {}

    for trace in traces:
        hash = trace.transaction_hash
        existing_traces = grouped_traces.get(hash, [])
        grouped_traces[hash] = existing_traces + [trace]

    return grouped_traces


def _get_arbitrages_for_transaction(
    traces: List[ClassifiedTrace],
) -> List[Arbitrage]:
    swaps = _get_swaps(traces)

    if len(swaps) > 1:
        return _get_arbitrages_from_swaps(swaps)

    return []


def _get_arbitrages_from_swaps(swaps: List[Swap]) -> List[Arbitrage]:
    pool_addresses = {swap.pool_address for swap in swaps}

    all_arbitrages = []

    for index, first_swap in enumerate(swaps):
        other_swaps = swaps[:index] + swaps[index + 1 :]

        if first_swap.from_address not in pool_addresses:
            arbitrage = _get_arbitrage_starting_with_swap(first_swap, other_swaps)

            if arbitrage is not None:
                all_arbitrages.append(arbitrage)

    return all_arbitrages


def _get_arbitrage_starting_with_swap(
    start_swap: Swap,
    other_swaps: List[Swap],
) -> Optional[Arbitrage]:
    swap_path = [start_swap]

    current_address = start_swap.to_address
    current_token = start_swap.token_out_address

    while True:
        swaps_from_current_address = []

        for swap in other_swaps:
            if (
                swap.pool_address == current_address
                and swap.token_in_address == current_token
            ):
                swaps_from_current_address.append(swap)

        if len(swaps_from_current_address) == 0:
            return None

        if len(swaps_from_current_address) > 1:
            raise RuntimeError("todo")

        latest_swap = swaps_from_current_address[0]
        swap_path.append(latest_swap)

        current_address = latest_swap.to_address
        current_token = latest_swap.token_out_address

        if (
            current_address == start_swap.from_address
            and current_token == start_swap.token_in_address
        ):

            start_amount = start_swap.token_in_amount
            end_amount = latest_swap.token_out_amount
            profit_amount = end_amount - start_amount

            return Arbitrage(
                swaps=swap_path,
                account_address=start_swap.from_address,
                profit_token_address=start_swap.token_in_address,
                start_amount=start_amount,
                end_amount=end_amount,
                profit_amount=profit_amount,
            )

    return None


def _get_swaps(traces: List[ClassifiedTrace]) -> List[Swap]:
    ordered_traces = list(sorted(traces, key=lambda t: t.trace_address))

    swaps: List[Swap] = []
    prior_transfers: List[Transfer] = []

    for trace in ordered_traces:
        if trace.classification == Classification.transfer:
            prior_transfers.append(Transfer.from_trace(trace))

        elif trace.classification == Classification.swap:
            child_transfers = _get_child_transfers(trace.trace_address, traces)
            swap = _build_swap(
                trace,
                _remove_inner_transfers(prior_transfers),
                _remove_inner_transfers(child_transfers),
            )

            if swap is not None:
                swaps.append(swap)

    return swaps


def _build_swap(
    trace: ClassifiedTrace,
    prior_transfers: List[Transfer],
    child_transfers: List[Transfer],
) -> Optional[Swap]:
    if trace.abi_name == UNISWAP_V2_PAIR_ABI_NAME:
        return _parse_uniswap_v2_swap(trace, prior_transfers, child_transfers)
    elif trace.abi_name == UNISWAP_V3_POOL_ABI_NAME:
        return _parse_uniswap_v3_swap(trace, child_transfers)

    return None


def _parse_uniswap_v3_swap(
    trace: ClassifiedTrace,
    child_transfers: List[Transfer],
) -> Optional[Swap]:
    pool_address = trace.to_address
    recipient_address = (
        trace.inputs["recipient"]
        if trace.inputs is not None and "recipient" in trace.inputs
        else trace.from_address
    )

    transfers_to_pool = _filter_transfers(child_transfers, to_address=pool_address)
    transfers_from_pool_to_recipient = _filter_transfers(
        child_transfers, to_address=recipient_address, from_address=pool_address
    )

    if len(transfers_to_pool) == 0:
        return None

    if len(transfers_from_pool_to_recipient) != 1:
        return None

    transfer_in = transfers_to_pool[-1]
    transfer_out = transfers_from_pool_to_recipient[0]

    return Swap(
        abi_name=UNISWAP_V3_POOL_ABI_NAME,
        transaction_hash=trace.transaction_hash,
        trace_address=trace.trace_address,
        pool_address=pool_address,
        from_address=transfer_in.from_address,
        to_address=transfer_out.to_address,
        token_in_address=transfer_in.token_address,
        token_in_amount=transfer_in.amount,
        token_out_address=transfer_out.token_address,
        token_out_amount=transfer_out.amount,
    )


def _parse_uniswap_v2_swap(
    trace: ClassifiedTrace,
    prior_transfers: List[Transfer],
    child_transfers: List[Transfer],
) -> Optional[Swap]:

    pool_address = trace.to_address
    recipient_address = (
        trace.inputs["to"]
        if trace.inputs is not None and "to" in trace.inputs
        else trace.from_address
    )

    transfers_to_pool = _filter_transfers(prior_transfers, to_address=pool_address)
    transfers_from_pool_to_recipient = _filter_transfers(
        child_transfers, to_address=recipient_address, from_address=pool_address
    )

    if len(transfers_to_pool) == 0:
        return None

    if len(transfers_from_pool_to_recipient) != 1:
        return None

    transfer_in = transfers_to_pool[-1]
    transfer_out = transfers_from_pool_to_recipient[0]

    return Swap(
        abi_name=UNISWAP_V2_PAIR_ABI_NAME,
        transaction_hash=trace.transaction_hash,
        trace_address=trace.trace_address,
        pool_address=pool_address,
        from_address=transfer_in.from_address,
        to_address=transfer_out.to_address,
        token_in_address=transfer_in.token_address,
        token_in_amount=transfer_in.amount,
        token_out_address=transfer_out.token_address,
        token_out_amount=transfer_out.amount,
    )


def _get_child_transfers(
    parent_trace_address: List[int],
    traces: List[ClassifiedTrace],
) -> List[Transfer]:
    child_transfers = []

    for child_trace in _get_child_traces(parent_trace_address, traces):
        if child_trace.classification == Classification.transfer:
            child_transfers.append(Transfer.from_trace(child_trace))

    return child_transfers


def _get_child_traces(
    parent_trace_address: List[int],
    traces: List[ClassifiedTrace],
) -> List[ClassifiedTrace]:
    ordered_traces = sorted(traces, key=lambda t: t.trace_address)
    child_traces = []

    for trace in ordered_traces:
        if _is_child_trace_address(
            parent_trace_address,
            trace.trace_address,
        ):
            child_traces.append(trace)

    return child_traces


def _is_child_trace_address(
    parent_trace_address: List[int],
    maybe_child_trace_address: List[int],
) -> bool:
    parent_trace_length = len(parent_trace_address)
    return (len(maybe_child_trace_address) > parent_trace_length) and (
        maybe_child_trace_address[:parent_trace_length] == parent_trace_address
    )


def _remove_inner_transfers(transfers: List[Transfer]) -> List[Transfer]:
    updated_transfers = []
    transfer_trace_addresses: List[List[int]] = []

    sorted_transfers = sorted(transfers, key=lambda t: t.trace_address)

    for transfer in sorted_transfers:
        if not any(
            _is_subtrace(parent_address, transfer.trace_address)
            for parent_address in transfer_trace_addresses
        ):
            updated_transfers.append(transfer)

        transfer_trace_addresses.append(transfer.trace_address)

    return updated_transfers


def _is_subtrace(parent_trace_address, child_trace_address) -> bool:
    return (
        len(child_trace_address) > len(parent_trace_address)
        and child_trace_address[: len(parent_trace_address)] == parent_trace_address
    )


def _filter_transfers(
    transfers: List[Transfer],
    to_address: Optional[str] = None,
    from_address: Optional[str] = None,
) -> List[Transfer]:
    filtered_transfers = []

    for transfer in transfers:
        if to_address is not None and transfer.to_address != to_address:
            continue

        if from_address is not None and transfer.from_address != from_address:
            continue

        filtered_transfers.append(transfer)

    return filtered_transfers
