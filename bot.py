from __future__ import annotations

import asyncio
import discord
from discord.ext import commands
import datetime
import time
import re
import threading
import emoji
from typing import *
from collections import defaultdict, deque
import concurrent
import concurrent.futures





token = ""
with open("automodtoken.txt", "r", encoding="utf-8") as f:
    token = f.read().strip()



loop = asyncio.new_event_loop()
executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
loop.set_default_executor(executor)



def is_smaller_repeat_of(chunk, sub):
    if len(chunk) % len(sub) != 0:
        return False
    return sub * (len(chunk) // len(sub)) == chunk

def find_smallest_repeat(chunk):
    for i in range(1, len(chunk)):
        candidate = chunk[:i]
        if is_smaller_repeat_of(chunk, candidate):
            return candidate
    return chunk


def find_repeating_blocks(text: str, min_chunk_len=4, max_chunk_len=100, min_repeats=2):
    n = len(text)
    used = [False] * n
    results = {}

    for size in range(max_chunk_len, min_chunk_len - 1, -1):
        seen = defaultdict(list)

        for i in range(n - size + 1):
            chunk = text[i:i + size]
            seen[chunk].append(i)

        for chunk, positions in seen.items():
            if len(positions) < 2:
                continue

            non_overlapping = []
            last_end = -1
            for pos in positions:
                if pos >= last_end and all(not used[j] for j in range(pos, pos + size)):
                    non_overlapping.append(pos)
                    last_end = pos + size

            if len(non_overlapping) < min_repeats:
                continue

            # Try to reduce to smallest repeating unit
            smallest_chunk = find_smallest_repeat(chunk)

            if smallest_chunk != chunk:
                sub_size = len(smallest_chunk)
                sub_positions = []
                for pos in non_overlapping:
                    for k in range(0, size, sub_size):
                        sub_start = pos + k
                        if all(not used[j] for j in range(sub_start, sub_start + sub_size)):
                            sub_positions.append(sub_start)
                            for j in range(sub_start, sub_start + sub_size):
                                used[j] = True
                if len(sub_positions) >= min_repeats:
                    results[smallest_chunk] = results.get(smallest_chunk, 0) + len(sub_positions)
            else:
                for pos in non_overlapping:
                    for j in range(pos, pos + size):
                        used[j] = True
                results[chunk] = results.get(chunk, 0) + len(non_overlapping)

    # Filter out chunks below min_repeats
    return {k: v for k, v in results.items() if v >= min_repeats}



_call_history_lock = threading.Lock()

_call_history: dict[Tuple[int, int], Tuple[deque, threading.Lock]] = {}

def is_rate_limited(identifier: int, cooldown: int, duration: int, group: int = 0) -> bool:
    now = time.time()
    key = (identifier, group)

    with _call_history_lock:
        if key not in _call_history:
            _call_history[key] = (deque(), threading.Lock())
        history, history_lock = _call_history[key]

    with history_lock:
        while history and now - history[0] > duration:
            history.popleft()

        if len(history) >= cooldown:
            return True

        history.append(now)
        return False




def convert_duration_to_seconds(value, unit):
    if unit == 's': return value
    elif unit == 'm': return value * 60
    elif unit == 'h': return value * 3600
    elif unit == 'd': return value * 86400
    else: return 0

def generate_unix_timestamp(seconds: int, stamp_type: str = "R"):
    mode = "R"
    if stamp_type == "short_time" or stamp_type == "short-time" or stamp_type == "short time" or stamp_type == "st" or stamp_type == "t":
        mode = "t"
    elif stamp_type == "long_time" or stamp_type == "long-time" or stamp_type == "long time" or stamp_type == "lt" or stamp_type == "T":
        mode = "T"
    elif stamp_type == "short_date" or stamp_type == "short-date" or stamp_type == "short date" or stamp_type == "sd" or stamp_type == "d":
        mode = "d"
    elif stamp_type == "long_date" or stamp_type == "long-date" or stamp_type == "long date" or stamp_type == "ld" or stamp_type == "D":
        mode = "D"
    elif stamp_type == "long_date_with_short_time" or stamp_type == "long-date-with-short-time" or stamp_type == "long date with short time" or stamp_type == "ldwst" or stamp_type == "ldst" or stamp_type == "f":
        mode = "f"
    elif stamp_type == "long_date_with_day_of_week_and_short_time" or stamp_type == "long-date-with-day-of-week-and-short-time" or stamp_type == "long date with day of week and short time" or stamp_type == "ldwdowst" or stamp_type == "lddwst" or stamp_type == "F":
        mode = "F"
    
    future_timestamp = datetime.datetime.now() + datetime.timedelta(seconds = seconds)
    return f"<t:{int(future_timestamp.timestamp())}:{mode}>"

def generate_autotimeout_moderation_timestamp():
    return generate_unix_timestamp(seconds=convert_duration_to_seconds(value=1, unit="h"), stamp_type='R')


async def purge_recent_messages(message: discord.Message):
    def check_author(m: discord.Message) -> bool:
        return m.author == message.author
    
    await message.channel.purge(limit=25, check=check_author)


async def execute_member_automod_timeout(message: discord.Message):
    loop.create_task(message.author.timeout(datetime.timedelta(hours=1)))
    loop.create_task(purge_recent_messages(message))
    embed = discord.Embed(
        title = "<a:warning_dotgg_femz:1196846652288422072> AutoMod",
        description = f"{message.author.mention} you have been timed out until {generate_autotimeout_moderation_timestamp()}!",
        color = discord.Color.red(),
        timestamp = datetime.datetime.now()
    )
    loop.create_task(message.author.send(message.author.mention, embed = embed))


rate_limit_groups: Dict[int, Tuple[int, int]] = {
    16: (2, 6),
    17: (5, 30),
    18: (8, 60),
    19: (13, 60 * 2),
    20: (20, 60 * 5)
}

async def do_automod_timeout_check(message: discord.Message):
    for group, config in rate_limit_groups.items():
        cooldown, duration = config
        if is_rate_limited(message.author.id, cooldown, duration, group):
            await execute_member_automod_timeout(message)
            return


att_timeframe_values: Dict[int, Tuple[int, int]] = {
    11: (4, 5),
    12: (8, 15),
    13: (16, 30),
    14: (24, 50),
    15: (30, 60)
}

def automod_att_spam_check(message: discord.Message) -> bool:
    attachments = len(message.attachments)
    if attachments == 0:
        return False
    
    for group, config in att_timeframe_values.items():
        cooldown, duration = config
        for i in range(attachments):
            result = is_rate_limited(message.author.id, cooldown, duration, group)
            if result:
                return True
    
    return False


link_timeframe_values: Dict[int, Tuple[int, int]] = {
    6: (2, 5),
    7: (4, 15),
    8: (8, 30),
    9: (15, 50),
    10: (25, 60)
}

def automod_link_spam_check(message: discord.Message) -> bool:
    link_count = len(re.findall(r'https?://[^\s)>\]}\'"]+', message.content))
    if link_count == 0:
        return False
    
    for group, config in link_timeframe_values.items():
        cooldown, duration = config
        for i in range(link_count):
            result = is_rate_limited(message.author.id, cooldown, duration, group)
            if result:
                return True
    
    return False


msg_timeframe_values: Dict[int, Tuple[int, int]] = {
    1: (5, 6),
    2: (10, 15),
    3: (20, 30),
    4: (30, 50),
    5: (40, 60)
}

def automod_msg_spam_check(message: discord.Message) -> bool:
    for group, config in msg_timeframe_values.items():
        cooldown, duration = config
        result = is_rate_limited(message.author.id, cooldown, duration, group)
        if result:
            return True
    
    return False


def analyze(text: str) -> Tuple[int, int, int]:
    upper = 0
    lower = 0

    for char in text:
        if char.isupper():
            upper += 1
        elif char.islower():
            lower += 1

    total = upper + lower

    return (int((upper / total * 100) if total > 0 else 0.0), upper, lower)

def automod_caps_spam_check(message: discord.Message) -> bool:
    percent, upper, lower = analyze(message.content)
    
    if (upper + lower > 20) and (percent >= 80):
        return True
    return False


repitition_config_values: Dict[int, int] = {
    3: 20,
    4: 15,
    5: 10,
    6: 5,
    7: 3
}
def automod_repitition_check(message: discord.Message) -> bool: # i made the repeating text checker behind this using chatgpt because i wouldnt know where to start on it myself, but as you can tell this here was made purely by me because of how shitty it is
    repitition_result_values: Dict[int, Dict[str, int]] = {}
    results_flagged: Dict[int, bool] = {}
    text = message.content.lower()
    
    flagged_overall = False
    
    for min_rep_len, min_rep_count in repitition_config_values.items():
        results = find_repeating_blocks(text, min_rep_len, 100, min_rep_count)
        repitition_result_values[min_rep_len] = results
        if results:
            results_flagged[min_rep_len] = True
    
    for rep_len, flagged in results_flagged.items():
        if flagged:
            flagged_overall = True
    
    return flagged_overall


def check_emoji_count(text: str) -> int:
    emojis = 0
    
    for i in re.finditer(r'<(?::|a:)(?P<name>\w+):(?P<id>\d+)>', text):
        emojis += 1
    
    emojis += sum(1 for char in text if char in emoji.EMOJI_DATA)
    
    return emojis

def automod_emojis_check(message: discord.Message) -> bool:
    emoji_count = check_emoji_count(message.content)
    if emoji_count >= 10:
        return True
    return False

def automod_newline_check(message: discord.Message) -> bool:
    times = 0
    for char in message.content:
        if char == "\n":
            times += 1
    if times >= 10:
        return True
    return False


async def moderate_message(message: discord.Message, moderation_rule: str, moderation_reason: str):
    loop.create_task(do_automod_timeout_check(message))
    loop.create_task(message.delete())
    
    embed = discord.Embed(
        title = "<a:warning_dotgg_femz:1196846652288422072> AutoMod",
        description = f"{message.author.mention} your message broke the rules for {moderation_rule}!",
        color = discord.Color.red(),
        timestamp = datetime.datetime.now()
    )
    embed.set_footer(text = f'Reason: {moderation_reason}')
    
    loop.create_task(message.channel.send(message.author.mention, embed = embed, delete_after = 5))
    loop.create_task(message.author.send(message.author.mention, embed = embed))
    



moderation_funcs_to_data: Dict[Callable[[discord.Message], bool], Tuple[str, str]] = {
    automod_att_spam_check: ("attachment spam", "Too many attachments in a short period of time"),
    automod_link_spam_check: ("link spam", "Too many links in a short period of time"),
    automod_msg_spam_check: ("message spam", "Too many messages in a short period of time"),
    automod_caps_spam_check: ("caps spam", "Message contained too many uppercase letters"),
    automod_repitition_check: ("repeating content", "Message contained text that repeated too many times"),
    automod_emojis_check: ("emoji spam", "Message contained too many emojis"),
    automod_newline_check: ("newline spam", "Message contained too many new lines")
}


async def message_automod_check_new(message: discord.Message):
    async def run_check(func, rule, reason):
        result = await loop.run_in_executor(executor, func, message)
        return (result, rule, reason)

    tasks = [run_check(func, rule, reason) for func, (rule, reason) in moderation_funcs_to_data.items()]

    for coro in asyncio.as_completed(tasks):
        result, rule, reason = await coro
        if result:
            await moderate_message(message, rule, reason)
            return



class FemboyServerModerationBot(commands.Bot):
    def __init__(self, token: str):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix = "a$", 
            intents = intents,
            case_insensitive = True,
            strip_after_prefix = True,
            help_command = None,
            activity = discord.Activity(
                name='.gg/femz', 
                type=discord.ActivityType.watching
            )
        )
        self.token = token

    async def on_ready(self):
        await self.register_commands()
        print("ready")
    
    async def startup(self):
        await self.start(self.token)

    async def on_message(self, message: discord.Message):
        if (not message.author.bot) and (not message.author.guild_permissions.moderate_members):
            await message_automod_check_new(message)
        ...

    async def register_commands(self):
        ...


loop.create_task(FemboyServerModerationBot(token).startup())
loop.run_forever()
