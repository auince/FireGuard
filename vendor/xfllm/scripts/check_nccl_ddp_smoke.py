#!/usr/bin/env python3
from __future__ import annotations

import os

import torch
import torch.distributed as dist


def main() -> None:
    rank = int(os.environ["RANK"])
    local_rank = int(os.environ["LOCAL_RANK"])
    world_size = int(os.environ["WORLD_SIZE"])

    torch.cuda.set_device(local_rank)
    dist.init_process_group("nccl")

    tensor = torch.ones(4, device="cuda") * (rank + 1)
    dist.all_reduce(tensor)
    print(f"rank={rank} world_size={world_size} all_reduce={tensor.tolist()}", flush=True)

    model = torch.nn.parallel.DistributedDataParallel(
        torch.nn.Linear(4, 4, bias=False).cuda(local_rank),
        device_ids=[local_rank],
    )
    loss = model(torch.ones(2, 4, device="cuda")).sum()
    loss.backward()
    print(f"rank={rank} backward_ok", flush=True)

    dist.destroy_process_group()


if __name__ == "__main__":
    main()
