from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
from data.plugins.astrbot_plugin_mg_guessr.initialize import initialize_data
from tinydb import TinyDB, Query
from datetime import datetime
import random
import re
import os

class GameManager:
    def __init__(self, db_path):
        self.songs_db = TinyDB(db_path)
        self.games = {}  # {group_id: game_state}
        self.winners_db = TinyDB('/AstrBot/data/winners.json')  # 用于存储排行榜

    def _get_song_by_id(self, song_id):
        ArcData = Query()
        return self.songs_db.table('arc_data').get(ArcData.id == song_id)

    def _find_song_by_alias(self, name):
        Aliases = Query()
        alias = self.songs_db.table('aliases').get(Aliases.别名.matches(name, flags=re.IGNORECASE))
        return self._get_song_by_id(alias['id']) if alias else None

    def _fuzzy_search(self, name):
        ArcData = Query()
        escaped_name = re.escape(name)
        return self.songs_db.table('arc_data').search(
            ArcData.曲名.matches(f'(?i).*{escaped_name}.*')
        )

    def start_game(self, group_id, max_attempts=10):
        all_songs = self.songs_db.table('arc_data').all()
        answer = random.choice(all_songs)
        logger.info(f"游戏开始，答案是：{answer['曲名']}")
        if(max_attempts < 1):
            return "尝试次数必须大于0"
        self.games[group_id] = {
            'answer': answer,
            'max_attempts': int(max_attempts),
            'remaining': int(max_attempts),
            'start_time': datetime.now(),
            'guesses': []
        }

        return f"游戏开始！请在{max_attempts}次尝试内猜出曲目！\n输入/mg tip可以获取提示。一局建议使用两次以内。"

    def stop_game(self, group_id):
        game = self.games.pop(group_id, None)
        if game:
            return f"游戏结束！正确答案是：{game['answer']['曲名']}"
        return "当前没有进行中的游戏"

    def handle_guess(self, group_id, user_name, song_name):
        game = self.games.get(group_id)
        if not game:
            return "当前没有进行中的游戏"

        guess = self._find_song_by_alias(song_name)
        if not guess:
            candidates = self._fuzzy_search(song_name)
            guess = candidates[0] if candidates else None

        if not guess:
            return "未找到相关曲目，请重新尝试"

        game['remaining'] -= 1
        game['guesses'].append((user_name, guess))

        if guess['id'] == game['answer']['id']:
            self._record_winner_and_runner_up(group_id, user_name, game['guesses'])
            self.games.pop(group_id)
            return f"恭喜 {user_name} 猜对了！正确答案是：{game['answer']['曲名']}"

        # Check if remaining attempts are 0
        if game['remaining'] == 0:
            self.games.pop(group_id)
            return f"游戏结束！你已用完所有尝试次数。正确答案是：{game['answer']['曲名']}"

        output = [f"❌ 猜错了！剩余尝试次数：{game['remaining']}\n你的猜测：{guess['曲名']}"]
        answer = game['answer']
        key_items = []

        fields_to_compare = [
            '曲师', 'FTR谱师', '难度分级', '语言', '背景', '侧', '曲包'
        ]

        for field in fields_to_compare:
            guess_value = guess.get(field)
            answer_value = answer.get(field)

            if field in ['曲师', 'FTR谱师', '曲包']:
                if guess_value == answer_value:
                    key_items.append(f"✅{field}: {guess_value}")
                continue

            if guess_value is None and answer_value is None:
                output.append(f"✅{field}: N/A")
            elif guess_value is None:
                output.append(f"🚫{field}: N/A")
            elif answer_value is None:
                output.append(f"🚫{field}: {guess_value}")
            elif guess_value == answer_value:
                output.append(f"✅{field}: {guess_value}")
            else:
                output.append(f"❌{field}: {guess_value}")

        def parse_difficulty(d):
            return float(d.replace('+', '.5').replace('?', '0')) if d else None

        guess_ftr = parse_difficulty(guess.get('FTR难度'))
        answer_ftr = parse_difficulty(answer.get('FTR难度'))
        if guess_ftr is not None and answer_ftr is not None:
            if guess_ftr < answer_ftr:
                output.append(f"⬆️FTR难度: {guess['FTR难度']}")
            elif guess_ftr > answer_ftr:
                output.append(f"⬇️FTR难度: {guess['FTR难度']}")
            else:
                output.append(f"✅FTR难度: {guess['FTR难度']}")
        elif guess_ftr is None and answer_ftr is None:
            output.append(f"✅FTR难度: N/A")
        else:
            output.append(f"🚫FTR难度: {guess.get('FTR难度', 'N/A')}")

        guess_byd = parse_difficulty(guess.get('BYD难度'))
        answer_byd = parse_difficulty(answer.get('BYD难度'))
        if guess_byd is not None and answer_byd is not None:
            if guess_byd < answer_byd:
                output.append(f"⬆️BYD难度: {guess['BYD难度']}")
            elif guess_byd > answer_byd:
                output.append(f"⬇️BYD难度: {guess['BYD难度']}")
            else:
                output.append(f"✅BYD难度: {guess['BYD难度']}")
        elif guess_byd is None and answer_byd is None:
            output.append(f"✅BYD难度: N/A")
        else:
            output.append(f"🚫BYD难度: {guess.get('BYD难度', 'N/A')}")

        guess_etr = parse_difficulty(guess.get('ETR难度'))
        answer_etr = parse_difficulty(answer.get('ETR难度'))
        if guess_etr is not None and answer_etr is not None:
            if guess_etr < answer_etr:
                output.append(f"⬆️ETR难度: {guess['ETR难度']}")
            elif guess_etr > answer_etr:
                output.append(f"⬇️ETR难度: {guess['ETR难度']}")
            else:
                output.append(f"✅ETR难度: {guess['ETR难度']}")
        elif guess_etr is None and answer_etr is None:
            output.append(f"✅ETR难度: N/A")
        else:
            output.append(f"🚫ETR难度: {guess.get('ETR难度', 'N/A')}")

        def parse_version(v):
            return float(v.replace('+', '.5').replace('?', '0')) if v else None

        guess_version = float(parse_version(guess.get('版本')))
        answer_version = float(parse_version(answer.get('版本')))
        if guess_version is not None and answer_version is not None:
            if guess_version < answer_version:
                output.append(f"⬆️版本: {guess['版本']}")
            elif guess_version > answer_version:
                output.append(f"⬇️版本: {guess['版本']}")
            else:
                output.append(f"✅版本: {guess['版本']}")
        elif guess_version is None and answer_version is None:
            output.append(f"✅版本: N/A")
        else:
            output.append(f"🚫版本: {guess.get('版本', 'N/A')}")

        if key_items:
            output.append("\n你发现了关键项！")
            output.extend(key_items)

        return "\n".join(output)

    def _record_winner_and_runner_up(self, group_id, winner_name, guesses):
        # 记录胜利者
        self.winners_db.insert({'group': group_id, 'winner': winner_name, 'time': datetime.now().isoformat()})

        # 找到最接近猜中者
        max_correct_fields = 0
        runner_up = None

        for user_name, guess in guesses:
            if user_name == winner_name:
                continue

            correct_fields = sum(
                1 for field in guess if guess.get(field) == self.games[group_id]['answer'].get(field)
            )

            if correct_fields > max_correct_fields:
                max_correct_fields = correct_fields
                runner_up = user_name

        if runner_up:
            self.winners_db.insert({'group': group_id, 'runner_up': runner_up, 'time': datetime.now().isoformat()})

    def get_leaderboard(self, top_n):
        winners = self.winners_db.search(Query().winner.exists())
        runners_up = self.winners_db.search(Query().runner_up.exists())

        winners_count = {}
        runners_up_count = {}

        for entry in winners:
            winners_count[entry['winner']] = winners_count.get(entry['winner'], 0) + 1

        for entry in runners_up:
            runners_up_count[entry['runner_up']] = runners_up_count.get(entry['runner_up'], 0) + 1

        top_winners = sorted(winners_count.items(), key=lambda x: x[1], reverse=True)[:top_n]
        top_runners_up = sorted(runners_up_count.items(), key=lambda x: x[1], reverse=True)[:top_n]

        winner_board = "冠军榜:\n" + "\n".join([f"{name}: {count}" for name, count in top_winners])
        runner_up_board = "亚军榜:\n" + "\n".join([f"{name}: {count}" for name, count in top_runners_up])

        return f"{winner_board}\n\n{runner_up_board}"

    def get_hint(self, group_id):
        game = self.games.get(group_id)
        if not game:
            return "当前没有进行中的游戏"

        answer = game['answer']
        song_name = answer['曲名']
        hint_options = []

        # 使用正则表达式查找所有匹配的文件
        hint_dir = "/AstrBot/data/image/"
        pattern = re.compile(rf"^{song_name}-(a|b)-\d+\.png$")  # 匹配类似song_name-a-1.png的文件

        for filename in os.listdir(hint_dir):
            if pattern.match(filename):  # 如果文件名符合正则表达式
                hint_options.append(os.path.join(hint_dir, filename))

        if hint_options:
            return random.choice(hint_options)

        return "提示生成失败"


@register("mg-guessr", "star0", "mg-guessr", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        # 更新数据
        # await initialize_data()
        self.game_manager = GameManager('/AstrBot/data/songs_db.json')
    
    @filter.command("mg start")
    async def start(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        group_id = event.get_group_id()
        
        # 切分消息并确保第二个元素后的所有内容保留
        message_parts = message_str.split(" ", 2)  # 只分割前两次
        if len(message_parts) > 2:
            # 如果有多于两个部分，保留从第三部分开始的内容
            yield event.plain_result(self.game_manager.start_game(group_id, message_parts[2]))
        else:
            # 如果没有超过两个部分，默认使用10作为参数
            yield event.plain_result(self.game_manager.start_game(group_id, 10))

    @filter.command("mg stop")
    async def stop(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        group_id = event.get_group_id()
        yield event.plain_result(self.game_manager.stop_game(group_id))

    @filter.command("mg guess")
    async def guess(self, event: AstrMessageEvent):
        try:
            user_name = event.get_sender_name()
            message_str = event.message_str
            group_id = event.get_group_id()
            message_parts = message_str.split(" ", 2)
            if len(message_parts) > 2:
                input_title = message_parts[2]
            else:
                input_title = ""
            # 捕获异常，如果发生异常什么也不做
            yield event.plain_result(self.game_manager.handle_guess(group_id, user_name, input_title))
        except Exception:
            pass

    @filter.command("mg rank")
    async def rank(self, event: AstrMessageEvent):
        message_str = event.message_str
        group_id = event.get_group_id()
        message_parts = message_str.split(" ", 2)
        if len(message_parts) > 2:
            top_n = int(message_parts[2])
        else:
            top_n = 10
        leaderboard = self.game_manager.get_leaderboard(top_n)
        yield event.plain_result(leaderboard)

    @filter.command("mg help")
    async def help_text(self, event: AstrMessageEvent):
        yield event.plain_result("/mg start 开始游戏\n/mg stop 停止游戏\n/mg guess 曲名 猜测曲目\n/mg tip 曲目提示\n/mg rank 排行榜\n/mg help 获取帮助信息\n感谢rosemoe提供俗名库")

    @filter.command("mg tip")
    async def tip(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        hint_path = self.game_manager.get_hint(group_id)

        if hint_path == "提示生成失败":
            yield event.plain_result(hint_path)
        else:
            chain = [
                Comp.Plain("这是你的提示："),
                Comp.Image.fromFileSystem(hint_path)
            ]
            yield event.chain_result(chain)

