import csv
import json
import hashlib
import httpx
from tinydb import TinyDB, Query
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import difflib

# 数据库文件路径
db_path = '/AstrBot/data/songs_db.json'
alias_csv_url = "https://cloud.s0tools.cn/d/Local/yrsk_arcaea_alias_1744887235.csv?sign=A_ahq15Halhw67ESE_QV3sDU7yU9AhcQfkS7FVeoQck=:0"


# 从 URL 获取 JSON 数据
async def fetch_song_data(url):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)  # 异步请求
            response.raise_for_status()  # 如果返回的状态码不是2xx，会抛出异常
            return response.json()  # 尝试将响应解析为 JSON
    except httpx.RequestError as e:
        logger.error(f"获取远程数据失败: {e}")  # 记录请求失败的错误
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")  # 记录 HTTP 错误
    except ValueError as e:
        logger.error(f"响应内容不是有效的 JSON 格式: {e}")  # 记录 JSON 解析错误
    return None  # 返回 None 表示失败


# 从 CSV 获取别名数据
async def fetch_aliases():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(alias_csv_url)
            response.raise_for_status()
            csv_content = response.text
            # 解析 CSV 数据
            aliases = []
            reader = csv.reader(csv_content.splitlines(), delimiter=',')
            for row in reader:
                if len(row) > 3:
                    song_id = row[1]
                    alias = row[3]
                    aliases.append((song_id, alias))
            return aliases
    except httpx.RequestError as e:
        logger.error(f"获取别名数据失败: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
    except Exception as e:
        logger.error(f"解析 CSV 文件时发生错误: {e}")
    return []


# 计算 JSON 数据的哈希值
def calculate_hash(data):
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()


# 存储数据到数据库
def store_data_in_db(data, aliases):
    if not data:
        logger.error("没有有效的曲目信息，跳过存储。")
        return

    # 创建数据库实例
    db = TinyDB(db_path)

    # 获取 info 表、arc_data 表和 alias 表
    info_table = db.table('info')
    arc_data_table = db.table('arc_data')
    alias_table = db.table('aliases')

    # 获取当前数据的哈希值
    current_hash = calculate_hash(data)

    # 查找 info 表中的哈希值
    info = info_table.all()
    if info and info[0].get('hash') == current_hash:
        logger.info("数据未变化，跳过执行。")
        db.close()
        return

    # 清空 arc_data 表并存储新数据
    logger.info("数据变化，正在清空 arc_data 表并存储新数据...")
    arc_data_table.truncate()
    alias_table.truncate()

    # 获取曲目难度的函数：考虑ratingPlus
    def get_rating(diff):
        rating = diff.get('rating', 0)
        # 检查是否存在 ratingPlus 且为 True，若是，则加上 "+"
        if 'ratingPlus' in diff and diff['ratingPlus'] is True:
            return f"{rating}+"
        return str(rating)

    # 解析每个曲目信息并插入到 arc_data 表
    for song in data.get('songs', []):
        try:
            # 获取曲目的 id
            song_id = song['id']

            if 'title_localized' not in song or not isinstance(song['title_localized'], dict):
                continue

            song_data = {
                '曲名': song['title_localized'].get('en', ''),
                '语言': ' '.join([lang for lang in song['title_localized'].keys()]),
                '曲包': song['set'],
                '曲师': song['artist'],
                '难度分级': ' '.join(
                    [
                        "PST" if diff.get('ratingClass') == 0 else
                        "PRS" if diff.get('ratingClass') == 1 else
                        "FTR" if diff.get('ratingClass') == 2 else
                        "BYD" if diff.get('ratingClass') == 3 else
                        "ETR" if diff.get('ratingClass') == 4 else ""
                        for diff in song.get('difficulties', [])
                    ]
                ),
                'FTR谱师': next((diff.get('chartDesigner', '') for diff in song.get('difficulties', []) if
                                 diff.get('ratingClass') == 2), ''),
                '侧': '光芒侧' if song.get('side') == 0 else
                '纷争侧' if song.get('side') == 1 else
                '消色之侧' if song.get('side') == 2 else
                'Lephon侧',
                '背景': song.get('bg', ''),
                '版本': song.get('version', ''),
                'FTR难度': next(
                    (get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 2), ''),
                'BYD难度': next(
                    (get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 3), ''),
                'ETR难度': next(
                    (get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 4), ''),
                'id': song_id  # 添加曲目的 id
            }
            arc_data_table.insert(song_data)

            # 存储别名到别名表
            for alias in aliases:
                song_alias, alias_name = alias
                if song_alias == song_id:  # 匹配到曲目的 ID
                    alias_table.insert({
                        'id': song_alias,
                        '别名': alias_name
                    })

        except Exception as e:
            # 如果某个曲目出错，打印错误信息并跳过该曲目
            logger.error(f"处理曲目 {song.get('title_localized', {}).get('en', '未知')} 时发生错误: {e}")
            continue

    # 更新 info 表中的哈希值
    info_table.truncate()  # 清空 info 表
    info_table.insert({'hash': current_hash})

    # 关闭数据库
    db.close()


# 游戏状态管理
game_data = {}


def start_game(group_id, song_data):
    # 随机抽取一个曲目作为谜底
    import random
    song = random.choice(song_data)
    game_data[group_id] = {
        'song': song,
        'remaining_guesses': 10,
        'guessed_users': [],
        'winner': None,
        'history': [],
    }


def stop_game(group_id):
    game = game_data.get(group_id)
    if game:
        return f"游戏结束，谜底是：{game['song']['曲名']}。"
    return "没有进行中的游戏。"


def guess_song(group_id, user_name, guess):
    game = game_data.get(group_id)
    if not game:
        return "没有进行中的游戏。"

    if game['remaining_guesses'] <= 0:
        return "猜测次数已用完，游戏结束！"

    if user_name in game['guessed_users']:
        return "你已经猜过了！"

    # 检查是否猜中了
    correct_song = game['song']
    correct_title = correct_song['曲名']

    # 使用别名库和模糊匹配判断猜测
    alias_table = TinyDB(db_path).table('aliases')
    aliases = alias_table.search(Query().别名 == guess)

    if aliases:
        correct_title = aliases[0]['id']  # 如果通过别名找到ID，直接使用该ID进行匹配
    else:
        # 模糊匹配
        matches = difflib.get_close_matches(guess, [correct_title], n=1, cutoff=0.6)
        if matches:
            correct_title = matches[0]

    if correct_title == correct_song['曲名']:
        game['winner'] = user_name
        game_data[group_id]['remaining_guesses'] = 0  # 游戏结束
        return f"恭喜 {user_name} 猜对了！游戏结束，谜底是：{correct_song['曲名']}！"

    # 返回猜错的线索
    hints = []
    # 提供更多线索，比如难度，版本等
    hints.append(f"难度分级: {correct_song['难度分级']}")
    hints.append(f"FTR难度: {correct_song['FTR难度']}")
    hints.append(f"版本: {correct_song['版本']}")

    game['remaining_guesses'] -= 1
    game['guessed_users'].append(user_name)
    return f"猜错了！{user_name}，继续猜！\n{' '.join(hints)}"


def get_tip(group_id):
    game = game_data.get(group_id)
    if not game:
        return "没有进行中的游戏。"

    hints = [f"难度分级: {game['song']['难度分级']}",
             f"FTR难度: {game['song']['FTR难度']}",
             f"版本: {game['song']['版本']}"]
    return '\n'.join(hints)


def get_rank():
    # 返回历史获胜用户排名
    db = TinyDB(db_path)
    winner_table = db.table('winner')
    winners = winner_table.all()

    # 统计用户的胜利次数
    user_win_count = {}
    for winner in winners:
        user_name = winner['user_name']
        user_win_count[user_name] = user_win_count.get(user_name, 0) + 1

    # 排序并返回前十名
    sorted_users = sorted(user_win_count.items(), key=lambda x: x[1], reverse=True)
    top_users = sorted_users[:10]
    return '\n'.join([f"{user}: {count}次" for user, count in top_users])


def help_message():
    return """
    /mg start [次数]  开始猜歌游戏，次数默认为10
    /mg stop  停止游戏并公布谜底
    /mg [曲名]  猜歌
    /mg tip  获取线索
    /mg rank  查看历史排名
    /mg help  查看帮助
    """


# 处理指令
@register("mg-guessr", "Star0", "mg-guessr-extention", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    def initialize(self):
        """插件初始化时会自动调用这个方法"""

        @self.on_message(filters.text)
        def on_message(event: MessageEventResult):
            group_id = event.get_group_id()
            message = event.message.strip()
            user_name = event.get_user_name()

            # /mg start [次数]
            if message.startswith("/mg start"):
                try:
                    args = message.split()
                    guesses = int(args[1]) if len(args) > 1 else 10
                    start_game(group_id, song_data)
                    return f"游戏开始！你有 {guesses} 次猜测机会。"
                except Exception as e:
                    logger.error(f"Error starting game: {e}")
                    return "游戏启动失败！"

            # /mg stop
            if message == "/mg stop":
                return stop_game(group_id)

            # /mg [曲名] 进行猜测
            if message.startswith("/mg "):
                song_guess = message[4:].strip()
                return guess_song(group_id, user_name, song_guess)

            # /mg tip
            if message == "/mg tip":
                return get_tip(group_id)

            # /mg rank
            if message == "/mg rank":
                return get_rank()

            # /mg help
            if message == "/mg help":
                return help_message()

            return "未知指令，输入 '/mg help' 查看帮助信息。"

    # 插件启用时会调用此方法
    def enable(self):
        """插件启用时自动调用"""
        pass

    # 插件禁用时会调用此方法
    def disable(self):
        """插件禁用时自动调用"""
        pass
