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
        alias = self.songs_db.table('aliases').get(
            Aliases.别名.matches(f'^{re.escape(name)}$', flags=re.IGNORECASE)
        )
        return self._get_song_by_id(alias['id']) if alias else None

    def _exact_song_name(self, name):
        ArcData = Query()
        return self.songs_db.table('arc_data').get(
            ArcData.曲名.matches(f'^{re.escape(name)}$', flags=re.IGNORECASE)
        )

    def _fuzzy_search(self, name):
        esc = re.sub(r"\s+", "", name)
        pattern = re.compile(rf"(?i).*{re.escape(esc)}.*")
        return [s for s in self.songs_db.table('arc_data').all()
                if pattern.match(re.sub(r"\s+", "", s.get('曲名', '')))]

    def _get_artwork_path(self, song_id):
        path = f"/AstrBot/data/songs/dl_{song_id}/1080_base_256.jpg"
        return path if os.path.isfile(path) else None

    def start_game(self, group_id, max_attempts=10):
        try:
            max_attempts = int(max_attempts)
        except ValueError:
            return "尝试次数必须为数字"
        if not (1 <= max_attempts <= 20):
            return "尝试次数必须在1到20之间"
        info = "已重新创建游戏，" if group_id in self.games else ""

        # 确保选的曲目至少有一张提示图
        hint_dir = "/AstrBot/data/image/"
        songs = self.songs_db.table('arc_data').all()
        answer = None
        for _ in range(100):
            candidate = random.choice(songs)
            pattern = re.compile(rf"^{re.escape(candidate['曲名'])}-(a|b)-\d+\.png$")
            if any(pattern.match(f) for f in os.listdir(hint_dir)):
                answer = candidate
                break
        if not answer:
            return "未能为本局找到可用提示，稍后再试"

        logger.warning(f"游戏开始，答案是：{answer['曲名']}")
        self.games[group_id] = {
            'answer': answer,
            'max_attempts': max_attempts,
            'remaining': max_attempts,
            'start_time': datetime.now(),
            'guesses': [],
            'hints_used': set()
        }
        return f"{info}游戏开始！请在{max_attempts}次尝试内猜出曲目！\n优先：ID完全匹配＞俗名＞曲名完全匹配＞模糊匹配\n输入/mg tip可以获取提示。一局建议使用两次以内。"

    def stop_game(self, group_id):
        game = self.games.pop(group_id, None)
        if not game:
            return "当前没有进行中的游戏"
        text = f"游戏结束！正确答案是：{game['answer']['曲名']}"
        # 如果有封面图，一并返回
        art = self._get_artwork_path(game['answer']['id'])
        if art:
            return text, art
        return text

    def handle_guess(self, group_id, user_name, song_name):
        if group_id not in self.games:
            return "当前没有进行中的游戏，请先输入/mg start 开始游戏"
        game = self.games[group_id]

        # ① 按 ID 精确查找
        guess = None
        if song_name.isdigit():
            guess = self._get_song_by_id(int(song_name))
        # ② 按俗名完全匹配
        if not guess:
            guess = self._find_song_by_alias(song_name)
        # ③ 按曲名完全匹配
        if not guess:
            guess = self._exact_song_name(song_name)
        # ④ 最后按模糊搜索
        if not guess:
            candidates = self._fuzzy_search(song_name)
            guess = candidates[0] if candidates else None

        if not guess:
            return "未找到相关曲目，请重新尝试"

        game['remaining'] -= 1
        game['guesses'].append((user_name, guess))

        # 猜对
        if guess['id'] == game['answer']['id']:
            self._record_winner_and_runner_up(group_id, user_name, game['guesses'])
            self.games.pop(group_id)
            text = f"恭喜 {user_name} 猜对了！正确答案是：{game['answer']['曲名']}"
            art = self._get_artwork_path(guess['id'])
            if art:
                return text, art
            return text

        # 用完尝试
        if game['remaining'] == 0:
            self.games.pop(group_id)
            text = f"游戏结束！你已用完所有尝试次数。正确答案是：{game['answer']['曲名']}"
            art = self._get_artwork_path(game['answer']['id'])
            if art:
                return text, art
            return text

        # 否则给出反馈
        output = [f"❌ 猜错了！剩余尝试次数：{game['remaining']}\n你的猜测：{guess['曲名']}"]
        answer = game['answer']
        key_items = []

        fields_to_compare = [
            '曲师', 'FTR谱师', '难度分级', '语言', '背景', '侧', '曲包'
        ]
        for field in fields_to_compare:
            gv = guess.get(field)
            av = answer.get(field)
            if field in ['曲师', 'FTR谱师', '曲包']:
                if gv == av:
                    key_items.append(f"✅{field}: {gv}")
                continue
            if gv is None and av is None:
                output.append(f"✅{field}: N/A")
            elif gv is None:
                output.append(f"🚫{field}: N/A")
            elif av is None:
                output.append(f"🚫{field}: {gv}")
            elif gv == av:
                output.append(f"✅{field}: {gv}")
            else:
                output.append(f"❌{field}: {gv}")

        def parse_d(d): return float(d.replace('+', '.5').replace('?', '0')) if d else None

        for short, label in [('FTR难度','FTR难度'), ('BYD难度','BYD难度'), ('ETR难度','ETR难度')]:
            gv = parse_d(guess.get(short))
            av = parse_d(answer.get(short))
            if gv is not None and av is not None:
                if gv < av:    output.append(f"⬆️{label}: {guess[short]}")
                elif gv > av:  output.append(f"⬇️{label}: {guess[short]}")
                else:          output.append(f"✅{label}: {guess[short]}")
            elif gv is None and av is None:
                output.append(f"✅{label}: N/A")
            else:
                output.append(f"🚫{label}: {guess.get(short, 'N/A')}")

        # 版本
        gv = parse_d(guess.get('版本'))
        av = parse_d(answer.get('版本'))
        if gv is not None and av is not None:
            if gv < av:    output.append(f"⬆️版本: {guess['版本']}")
            elif gv > av:  output.append(f"⬇️版本: {guess['版本']}")
            else:          output.append(f"✅版本: {guess['版本']}")
        elif gv is None and av is None:
            output.append(f"✅版本: N/A")
        else:
            output.append(f"🚫版本: {guess.get('版本', 'N/A')}")

        if key_items:
            output.append("\n你发现了关键项！")
            output.extend(key_items)

        return "\n".join(output)

    def _record_winner_and_runner_up(self, group_id, winner_name, guesses):
        self.winners_db.insert({'group': group_id, 'winner': winner_name, 'time': datetime.now().isoformat()})

    def get_leaderboard(self, group_id, top_n):
        winners = self.winners_db.search((Query().group == group_id) & Query().winner.exists())
        count = {}
        for e in winners:
            count[e['winner']] = count.get(e['winner'], 0) + 1
        top = sorted(count.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return "冠军榜:\n" + "\n".join(f"{n}: {c}" for n, c in top)

    def get_hint(self, group_id):
        game = self.games.get(group_id)
        if not game:
            return "当前没有进行中的游戏"
        base = game['answer']['曲名']
        hint_dir = "/AstrBot/data/image/"
        pattern = re.compile(rf"^{re.escape(base)}-(a|b)-\d+\.png$")
        files = [f for f in os.listdir(hint_dir) if pattern.match(f)]
        avail = [f for f in files if f not in game['hints_used']]
        if not avail:
            return "提示已用尽"
        choice = random.choice(avail)
        game['hints_used'].add(choice)
        remain = len(files) - len(game['hints_used'])
        return os.path.join(hint_dir, choice), f"提示还剩 {remain} 条"

@register("mg-guessr-test", "star0", "mg-guessr-test", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        self.game_manager = GameManager('/AstrBot/data/songs_db.json')

    @filter.command("mg start")
    async def start(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        parts = event.message_str.split(" ", 2)
        max_n = parts[2] if len(parts) > 2 else 10
        yield event.plain_result(self.game_manager.start_game(group_id, max_n))

        res = self.game_manager.get_hint(group_id)
        if isinstance(res, tuple):
            path, info = res
            chain = [Comp.Plain(info), Comp.Image.fromFileSystem(path)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @filter.command("mg stop")
    async def stop(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        res = self.game_manager.stop_game(group_id)
        if isinstance(res, tuple):
            text, img = res
            chain = [Comp.Plain(text), Comp.Image.fromFileSystem(img)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @filter.command("mg guess")
    async def guess(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        parts = event.message_str.split(" ", 2)
        title = parts[2] if len(parts) > 2 else ""
        res = self.game_manager.handle_guess(group_id, event.get_sender_name(), title)
        if isinstance(res, tuple):
            text, img = res
            chain = [Comp.Plain(text), Comp.Image.fromFileSystem(img)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @filter.command("mg rank")
    async def rank(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        parts = event.message_str.split(" ", 2)
        top_n = int(parts[2]) if len(parts) > 2 else 10
        yield event.plain_result(self.game_manager.get_leaderboard(group_id, top_n))

    @filter.command("mg tip")
    async def tip(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        res = self.game_manager.get_hint(group_id)
        if isinstance(res, tuple):
            path, info = res
            chain = [Comp.Plain(info), Comp.Image.fromFileSystem(path)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @filter.command("mg help")
    async def help_text(self, event: AstrMessageEvent):
        help_msg = (
            "/mg start [次数] 开始游戏\n"
            "/mg stop 停止游戏\n"
            "/mg guess 曲名 猜测曲目\n"
            "/mg tip 获取提示\n"
            "/mg rank [n] 查看排行榜\n"
            "/mg help 获取帮助信息\n"
            "感谢rosemoe提供俗名库\n"
            "Version: 1.2.0 修复若干bug，添加曲绘支持"
        )
        yield event.plain_result(help_msg)
