import random
import re
from datetime import datetime
from tinydb import TinyDB, Query
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 数据库文件路径
db_path = '/AstrBot/data/songs_db.json'
alias_csv_url = "https://cloud.s0tools.cn/d/Local/yrsk_arcaea_alias_1744887235.csv?sign=A_ahq15Halhw67ESE_QV3sDU7yU9AhcQfkS7FVeoQck=:0"


# 游戏状态存储
class Game:
    def __init__(self, group_id, song_data, aliases, max_attempts=10):
        self.group_id = group_id
        self.song_data = song_data
        self.aliases = aliases
        self.max_attempts = max_attempts
        self.attempts_left = max_attempts
        self.winner = None
        self.hint = []
        self.guessed_users = set()

        # 随机选取一首歌作为谜底
        self.answer = random.choice(song_data['songs'])
        self.answer_id = self.answer['id']
        self.answer_title = self.answer['title_localized'].get('en', '')
        self.answer_artist = self.answer.get('artist', '')
        self.answer_set = self.answer.get('set', '')
        self.answer_version = self.answer.get('version', '')

    def check_guess(self, guess):
        # 处理别名
        for alias in self.aliases:
            if alias[1] == guess:
                return True
        # 模糊匹配
        guess_song = next((song for song in self.song_data['songs'] if
                           re.search(guess, song['title_localized'].get('en', ''), re.IGNORECASE)), None)
        if not guess_song:
            return False

        # 比较谜底和猜测
        return self.compare_song(guess_song)

    def compare_song(self, guess_song):
        correct = True
        result = {}

        # 比较难度、版本等信息
        for key, value in {
            '难度分级': ['ratingClass', '难度分级'],
            'FTR难度': ['FTR难度', 'rating'],
            '版本': ['版本', 'version'],
        }.items():
            guess_value = guess_song.get(value[1], '')
            answer_value = getattr(self, value[0], '')
            if guess_value != answer_value:
                correct = False
                result[key] = (guess_value, answer_value)
            else:
                result[key] = (guess_value, guess_value)

        return correct, result

    def get_hint(self):
        return '\n'.join(self.hint)


# 数据库表格
def store_data_in_db(data, aliases):
    db = TinyDB(db_path)
    info_table = db.table('info')
    arc_data_table = db.table('arc_data')
    alias_table = db.table('aliases')

    current_hash = calculate_hash(data)
    info = info_table.all()
    if info and info[0].get('hash') == current_hash:
        logger.info("数据未变化，跳过执行。")
        db.close()
        return

    arc_data_table.truncate()
    alias_table.truncate()

    for song in data.get('songs', []):
        try:
            song_id = song['id']
            if 'title_localized' not in song:
                continue
            song_data = {
                '曲名': song['title_localized'].get('en', ''),
                '语言': ' '.join([lang for lang in song['title_localized'].keys()]),
                '曲包': song['set'],
                '曲师': song['artist'],
                '难度分级': ' '.join([
                    "PST" if diff.get('ratingClass') == 0 else
                    "PRS" if diff.get('ratingClass') == 1 else
                    "FTR" if diff.get('ratingClass') == 2 else
                    "BYD" if diff.get('ratingClass') == 3 else
                    "ETR" if diff.get('ratingClass') == 4 else ""
                    for diff in song.get('difficulties', [])
                ]),
                'id': song_id
            }
            arc_data_table.insert(song_data)

            for alias in aliases:
                song_alias, alias_name = alias
                if song_alias == song_id:
                    alias_table.insert({
                        'id': song_alias,
                        '别名': alias_name
                    })

        except Exception as e:
            logger.error(f"处理曲目 {song.get('title_localized', {}).get('en', '未知')} 时发生错误: {e}")
            continue

    info_table.truncate()
    info_table.insert({'hash': current_hash})
    db.close()


@register("mg-guessr", "Star0", "mg-guessr-extention", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.games = {}

    async def initialize(self):
        url = "https://arcwiki.mcd.blue/index.php?title=Template:Songlist.json&action=raw"
        song_data = await fetch_song_data(url)
        aliases = await fetch_aliases()
        if song_data:
            store_data_in_db(song_data, aliases)
            logger.info("数据初始化成功。")
        else:
            logger.error("无法获取有效的曲目信息，初始化失败。")

    @filter.command("mg start")
    async def start_game(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if group_id in self.games:
            await event.plain_result(f"当前群聊已有进行中的猜歌游戏，请先结束当前游戏。")
            return

        # 从 URL 获取曲目信息
        url = "https://arcwiki.mcd.blue/index.php?title=Template:Songlist.json&action=raw"
        song_data = await fetch_song_data(url)
        aliases = await fetch_aliases()

        game = Game(group_id, song_data, aliases, max_attempts=10)
        self.games[group_id] = game

        await event.plain_result(f"游戏开始！猜歌的曲目是：{game.answer_title}。你有{game.max_attempts}次机会。")

    @filter.command("mg stop")
    async def stop_game(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if group_id not in self.games:
            await event.plain_result("当前群聊没有进行中的猜歌游戏。")
            return

        game = self.games.pop(group_id)
        await event.plain_result(
            f"游戏结束！谜底是：{game.answer_title} ({game.answer_artist} - {game.answer_set}，版本：{game.answer_version})")

    @filter.command("mg")
    async def guess_song(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        message_str = event.message_str.lower().strip()

        if group_id not in self.games:
            await event.plain_result("当前群聊没有进行中的猜歌游戏。")
            return

        game = self.games[group_id]
        if message_str in game.guessed_users:
            await event.plain_result(f"{event.get_sender_name()}，你已经猜过了！")
            return

        correct, result = game.check_guess(message_str)
        if correct:
            game.winner = event.get_sender_name()
            game.guessed_users.add(event.get_sender_name())
            await event.plain_result(f"恭喜 {event.get_sender_name()} 猜对了！谜底就是：{game.answer_title}!")
        else:
            game.hint.append(f"猜测：{message_str} -> 提示：{result}")
            await event.plain_result(f"你猜的曲目不对，以下是部分提示：\n{game.get_hint()}")

    @filter.command("mg tip")
    async def tip(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if group_id not in self.games:
            await event.plain_result("当前群聊没有进行中的猜歌游戏。")
            return

        game = self.games[group_id]
        await event.plain_result(f"目前已知的线索：\n{game.get_hint()}")

    @filter.command("mg rank")
    async def rank(self, event: AstrMessageEvent):
        db = TinyDB(db_path)
        winner_table = db.table("winner")
        # 获取历史获胜的用户名排名前十
        winners = sorted(winner_table.all(), key=lambda x: x['count'], reverse=True)[:10]
        result = "\n".join([f"{winner['username']}: {winner['count']}次" for winner in winners])
        await event.plain_result(f"历史获胜排行榜：\n{result}")

    @filter.command("mg help")
    async def help(self, event: AstrMessageEvent):
        help_text = """
        /mg start [n] - 开始一个新的猜歌游戏，n为最大猜测次数，默认为10次。
        /mg stop - 停止当前游戏并公布谜底。
        /mg <曲名> - 猜测当前谜底的曲名，成功后会公布赢家。
        /mg tip - 返回目前为止的所有线索。
        /mg rank - 显示历史获胜用户排行榜。
        /mg help - 输出帮助信息。
        """
        await event.plain_result(help_text)

