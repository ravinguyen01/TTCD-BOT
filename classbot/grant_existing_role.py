"""One-off, idempotent grant to the human member snapshot of a guild."""

import argparse
import asyncio
import os

import discord


async def run(role_id, apply=False, workers=5, remove=False):
    intents = discord.Intents.none()
    intents.members = True
    async with discord.Client(intents=intents) as client:
        await client.login(os.environ['BOT_TOKEN'])
        guild = await client.fetch_guild(int(os.environ['GUILD_ID']))
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError('Target role does not exist or cannot be assigned')
        me = await guild.fetch_member(client.user.id)
        if not me.guild_permissions.manage_roles or role >= me.top_role:
            raise ValueError('Bot needs Manage Roles and a role above the target')
        # Complete pagination before changing any roles.
        members = [member async for member in guild.fetch_members(limit=None)]
        humans = [member for member in members if not member.bot]
        pending = [member for member in humans if (role in member.roles) == remove]
        action = 'remove' if remove else 'grant'
        print(f'Snapshot: humans={len(humans)}, bots_skipped={len(members)-len(humans)}, '
              f'already={len(humans)-len(pending)}, need_{action}={len(pending)}', flush=True)
        if not apply:
            return
        granted = failed = processed = 0
        queue = asyncio.Queue()
        for member in pending:
            queue.put_nowait(member)

        async def worker():
            nonlocal granted, failed, processed
            while not queue.empty():
                member = queue.get_nowait()
                try:
                    # discord.py coordinates route/global rate limits across workers.
                    if remove:
                        await member.remove_roles(role, reason='Admin requested clearing verification role')
                    else:
                        await member.add_roles(role, reason='Admin requested role for existing server members')
                    granted += 1
                except (discord.HTTPException, OSError):
                    failed += 1
                finally:
                    processed += 1
                    queue.task_done()
                if processed % 50 == 0:
                    print(f'Progress: processed={processed}/{len(pending)}, {action}_success={granted}, failed={failed}', flush=True)

        await asyncio.gather(*(worker() for _ in range(max(1, min(workers, 10)))))
        print(f'Result: {action}_success={granted}, already={len(humans)-len(pending)}, failed={failed}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role_id', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    asyncio.run(run(args.role_id, args.apply, args.workers, args.remove))
