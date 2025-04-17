import random
import difflib
from datetime import datetime
from tinydb import TinyDB, Query
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 数据库路径
db_path = '/AstrBot/data/songs_db.json'

# 游戏状态
game_states = {}


# 获取别名表
def get_alias_table():
    db = TinyDB(db_path)
    alias_table = db.table('aliases')
    return alias_table


# 获取歌曲库
def get_song_data_table():
    db = TinyDB(db_path)
    arc_data_table = db.table('arc_data')
    return arc_data_table


# 获取历史排名
def get_winner_table():
    db = TinyDB(db_path)
    winner_table = db.table('winners')
    return winner_table


# 启动猜歌游戏
async def start_game(group_id, max_attempts=10):
    song_data_table = get_song_data_table()
    # 随机选择一个曲目作为谜底
    song = random.choice(song_data_table.all())
    game_states[group_id] = {
        'mystery_song': song,
        'attempts_left': max_attempts,
        'guesses': [],
        'start_time': datetime.now(),
        'winner': None
    }
    logger.info(f"游戏已开始，谜底为：{song['曲名']}（ID: {song['id']}）。")
    return song['曲名']


# 停止猜歌游戏
async def stop_game(group_id):
    game_state = game_states.get(group_id)
    if not game_state:
        return "游戏未开始或已结束。"

    mystery_song = game_state['mystery_song']
    del game_states[group_id]  # 清除游戏状态
    return f"游戏结束，谜底是：{mystery_song['曲名']}（ID: {mystery_song['id']}）"


# 进行猜歌
async def make_guess(group_id, user_name, guess):
    game_state = game_states.get(group_id)
    if not game_state:
        return "游戏未开始或已结束。"

    mystery_song = game_state['mystery_song']
    attempts_left = game_state['attempts_left']
    guesses = game_state['guesses']

    if attempts_left <= 0:
        return "猜测次数已用完，游戏结束。"

    # 从别名表查找
    alias_table = get_alias_table()
    alias_match = alias_table.search(Query().别名 == guess)

    if alias_match:
        song_id = alias_match[0]['id']
        guess_song = next((song for song in get_song_data_table().all() if song['id'] == song_id), None)
    else:
        # 模糊匹配
        song_data = get_song_data_table().all()
        guess_song = difflib.get_close_matches(guess, [song['曲名'] for song in song_data], n=1)

        if guess_song:
            guess_song = next((song for song in song_data if song['曲名'] == guess_song[0]), None)
        else:
            guess_song = None

    if not guess_song:
        return "没有找到匹配的曲目，请尝试其他名称。"

    # 记录猜测
    game_state['attempts_left'] -= 1
    game_state['guesses'].append({
        'user': user_name,
        'guess': guess,
        'correct': guess_song['id'] == mystery_song['id'],
        'time': datetime.now()
    })

    # 判断是否猜对
    if guess_song['id'] == mystery_song['id']:
        game_state['winner'] = user_name
        # 记录历史胜利者
        winner_table = get_winner_table()
        winner_entry = winner_table.search(Query().user == user_name)
        if winner_entry:
            winner_table.update({'count': winner_entry[0]['count'] + 1}, Query().user == user_name)
        else:
            winner_table.insert({'user': user_name, 'count': 1})
        return f"恭喜 {user_name} 猜对了！谜底是：{mystery_song['曲名']}"

    # 提示猜错信息
    comparison = []
    for key in ['难度分级', 'FTR难度', '版本']:
        if mystery_song[key] != guess_song[key]:
            comparison.append(f"{key}: {guess_song[key]} ❌（谜底不是这个）")

    # 返回与谜底的比较结果
    return f"你猜的曲目与谜底不完全匹配，以下是与谜底的对比：\n" + "\n".join(comparison)


# 获取线索
async def get_tip(group_id):
    game_state = game_states.get(group_id)
    if not game_state:
        return "游戏未开始或已结束。"

    mystery_song = game_state['mystery_song']
    known_info = []
    for key in ['曲名', '难度分级', 'FTR难度', '版本']:
        known_info.append(f"{key}: {mystery_song.get(key, '未知')}")
    return "\n".join(known_info)


# 获取排名
async def get_rank():
    winner_table = get_winner_table()
    winners = sorted(winner_table.all(), key=lambda x: x['count'], reverse=True)[:10]
    return "\n".join([f"{entry['user']}: {entry['count']} 次" for entry in winners])


# 帮助信息
async def help_info():
    return """游戏指令:
    /mg start [最大猜测次数] - 启动游戏，默认最大猜测次数为 10。
    /mg stop - 停止游戏并公布谜底。
    /mg [曲名] - 猜歌，猜对即获胜。
    /mg tip - 获取当前已知线索。
    /mg rank - 查看历史获胜排名前十的玩家。
    /mg help - 查看帮助信息。
    """


@register("mg-guessr", "Star0", "mg-guessr-extention", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化时会自动调用"""
        pass

    @filter.command("mg start")
    async def start_game_cmd(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        max_attempts = int(event.message_str.split()[1]) if len(event.message_str.split()) > 1 else 10
        mystery_song = await start_game(group_id, max_attempts)
        return f"游戏已开始！谜底是：{mystery_song}"

    @filter.command("mg stop")
    async def stop_game_cmd(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        result = await stop_game(group_id)
        return result

    @filter.command("mg")
    async def make_guess_cmd(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        user_name = event.get_sender_name()
        guess = event.message_str.split(" ", 1)[1] if len(event.message_str.split(" ", 1)) > 1 else ""
        result = await make_guess(group_id, user_name, guess)
        return result

    @filter.command("mg tip")
    async def tip_cmd(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        result = await get_tip(group_id)
        return result

    @filter.command("mg rank")
    async def rank_cmd(self, event: AstrMessageEvent):
        result = await get_rank()
        return result

    @filter.command("mg help")
    async def help_cmd(self, event: AstrMessageEvent):
        result = await help_info()
        return result
