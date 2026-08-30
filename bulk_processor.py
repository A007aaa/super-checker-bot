import asyncio
import logging
from typing import List
from blockchain_checker import check_seed_params
import aiohttp
import storage

logger = logging.getLogger(__name__)


async def _process_batch(session, seeds: List[str], accounts: int, indexes: int):
    results = []
    for seed in seeds:
        try:
            # skip if already processed
            if storage.is_processed(seed):
                logger.debug(f"Skipping already processed seed (fast check): {seed[:32]}...")
                continue

            res = await check_seed_params(session, seed, accounts, indexes)
            if res:
                # res is (seed, final_found)
                value, found = res
                logger.info(f"ALERT: seed has balances: {value} -> {found}")
                storage.mark_alerted('SEED', value)
                results.append((value, found))

            storage.mark_processed(seed)
        except Exception as e:
            logger.error(f"Error processing seed: {e}")
    return results


async def process_file(path: str, batch_size: int = 100, accounts: int = 1, indexes: int = 5, concurrency: int = 6):
    """
    Stream the file containing seed phrases (one per line), deduplicate, and process in batches.
    - batch_size: number of seeds per internal batch
    - accounts/indexes: stage0 parameters (small, fast)
    - concurrency: number of parallel batches
    """
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    loop = asyncio.get_event_loop()

    async with aiohttp.ClientSession() as session:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            batch = []
            for line in f:
                line = line.strip()
                if not line: continue
                # normalize
                seed = ' '.join(line.split())
                if storage.is_seen(seed):
                    continue
                storage.mark_seen(seed)
                batch.append(seed)
                if len(batch) >= batch_size:
                    # schedule processing of this batch under semaphore
                    async def _run(b):
                        async with sem:
                            return await _process_batch(session, b, accounts, indexes)
                    tasks.append(loop.create_task(_run(batch.copy())))
                    batch = []
            # last batch
            if batch:
                async def _run_last(b):
                    async with sem:
                        return await _process_batch(session, b, accounts, indexes)
                tasks.append(loop.create_task(_run_last(batch.copy())))

        # gather results
        all_results = []
        for t in asyncio.as_completed(tasks):
            try:
                r = await t
                if r:
                    all_results.extend(r)
            except Exception as e:
                logger.error(f"Batch task error: {e}")

    return all_results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Bulk process a seeds file (one seed per line)')
    parser.add_argument('file', help='Path to seeds file (one per line)')
    parser.add_argument('--batch-size', type=int, default=100)
    parser.add_argument('--accounts', type=int, default=1)
    parser.add_argument('--indexes', type=int, default=5)
    parser.add_argument('--concurrency', type=int, default=6)
    args = parser.parse_args()

    storage.init_db()
    results = asyncio.run(process_file(args.file, batch_size=args.batch_size, accounts=args.accounts, indexes=args.indexes, concurrency=args.concurrency))
    print(f"Processing completed. Found {len(results)} seeds with balances.")
