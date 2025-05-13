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
        self.games_db = self.songs_db.table('games')
        self.winners_db = TinyDB('/AstrBot/data/winners.json')
        self.group_settings_db = self.songs_db.table('group_settings')
        self.games = self._load_games()

    def _load_games(self):
        games = {}
        for record in self.games_db.all():
            group_id = record['group_id']
            answer = self._get_song_by_id(record['answer']['id'])
            if not answer:
                continue
            games[group_id] = {
                'answer': answer,
                'max_attempts': record['max_attempts'],
                'remaining': record['remaining'],
                'start_time': datetime.fromisoformat(record['start_time']),
                'guesses': record['guesses'],
                'hints_used': set(record['hints_used'])
            }
        return games

    def is_group_enabled(self, group_id):
        record = self.group_settings_db.get(Query().group_id == int(group_id))
        return bool(record and record.get("enabled"))

    def enable_group(self, group_id):
        self.group_settings_db.upsert({'group_id': group_id, 'enabled': True}, Query().group_id == int(group_id))
        

    def disable_group(self, group_id):
        self.group_settings_db.upsert({'group_id': group_id, 'enabled': False}, Query().group_id == int(group_id))

    def _save_game(self, group_id):
        if group_id in self.games:
            game = self.games[group_id]
            self.games_db.upsert({
                'group_id': group_id,
                'answer': {'id': game['answer']['id']},
                'max_attempts': game['max_attempts'],
                'remaining': game['remaining'],
                'start_time': game['start_time'].isoformat(),
                'guesses': game['guesses'],
                'hints_used': list(game['hints_used'])
            }, Query().group_id == group_id)

    def _get_song_by_id(self, song_id):
        ArcData = Query()
        return self.songs_db.table('arc_data').get(ArcData.id == song_id)

    def _find_song_by_alias(self, name):
        Aliases = Query()
        alias = self.songs_db.table('aliases').get(
            Aliases.别名.matches(f'^{re.escape(name)}', flags=re.IGNORECASE)
        )
        return self._get_song_by_id(alias['id']) if alias else None

    def _exact_song_name(self, name):
        ArcData = Query()
        return self.songs_db.table('arc_data').get(
            ArcData.曲名.matches(f'^{re.escape(name)}', flags=re.IGNORECASE)
        )

    def _fuzzy_search(self, name):
        esc = re.sub(r"\s+", "", name)
        pattern = re.compile(rf"(?i).*{re.escape(esc)}.*")
        return [s for s in self.songs_db.table('arc_data').all()
                if pattern.match(re.sub(r"\s+", "", s.get('曲名', '')))]

    def _get_artwork_path(self, song_id):
        path = f"/AstrBot/data/songs/dl_{song_id}/1080_base_256.jpg"
        return path if os.path.isfile(path) else None

    def start_game(self, group_id, max_attempts=5):
        try:
            max_attempts = int(max_attempts)
        except ValueError:
            return "尝试次数必须为数字"
        if not (1 <= max_attempts <= 20):
            return "尝试次数必须在1到20之间"
        info = "已重新创建游戏，" if group_id in self.games else ""

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
        self._save_game(group_id)
        return f"{info}游戏开始！请在{max_attempts}次尝试内猜出曲目！\nID＞曲名＞俗名，/mg tip：获取提示，/mg guess 曲名：猜测曲目\n" \

    def stop_game(self, group_id):
        game = self.games.pop(group_id, None)
        self.games_db.remove(Query().group_id == group_id)
        if not game:
            return "当前没有进行中的游戏"
        text = f"游戏结束！正确答案是：{game['answer']['曲名']}"
        art = self._get_artwork_path(game['answer']['id'])
        if art:
            return text, art
        return text

    def _process_guess(self, song_name):
        guess = None
        if song_name.isdigit():
            guess = self._get_song_by_id(int(song_name))
        if not guess:
            guess = self._exact_song_name(song_name)
        if not guess:
            guess = self._find_song_by_alias(song_name)
        if not guess:
            candidates = self._fuzzy_search(song_name)
            guess = candidates[0] if candidates else None
        return guess

    def handle_guess(self, group_id, user_name, song_name, consume_attempt=True):
        if group_id not in self.games:
            return "当前没有进行中的游戏，请先输入/mg start 开始游戏"
        game = self.games[group_id]

        guess = self._process_guess(song_name)
        if not guess:
            return "未找到相关曲目，请重新尝试"

        if consume_attempt:
            game['remaining'] -= 1
            self._save_game(group_id)

        game['guesses'].append((user_name, guess))

        if guess['id'] == game['answer']['id']:
            self._record_winner_and_runner_up(group_id, user_name, game['guesses'])
            self.games.pop(group_id)
            self.games_db.remove(Query().group_id == group_id)
            text = f"恭喜 {user_name} 猜对了！正确答案是：{game['answer']['曲名']}"
            art = self._get_artwork_path(guess['id'])
            if art:
                return text, art
            return text

        if game['remaining'] == 0 and consume_attempt:
            self.games.pop(group_id)
            self.games_db.remove(Query().group_id == group_id)
            text = f"游戏结束！你已用完所有尝试次数。正确答案是：{game['answer']['曲名']}"
            art = self._get_artwork_path(game['answer']['id'])
            if art:
                return text, art
            return text

        if consume_attempt:
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
        return None

    def handle_non_command_guess(self, group_id, user_name, song_name):
        return self.handle_guess(group_id, user_name, song_name, consume_attempt=False)

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
        self._save_game(group_id)
        remain = len(files) - len(game['hints_used'])
        return os.path.join(hint_dir, choice), f"提示还剩 {remain} 条"

@register("mg-guessr", "star0", "mg-guessr", "1.0.0")
class MyPlugin(Star):
    def init(self, context: Context):
        super().init(context)

    async def initialize(self):
        self.game_manager = GameManager('/AstrBot/data/songs_db.json')

    @filter.command_group("mg", alias={'猜歌'})
    async def mg(self, event: AstrMessageEvent):
        pass
        # parts = event.message_str.split(" ", 2)
        # logger.error(len(parts))
        # if(len(parts) <= 1):
        #     yield event.plain_result("输入/mg 查询使用方法")

    @mg.command("start", alias={'开始'})
    async def start(self, event: AstrMessageEvent, max_n: int = 5):
        session_id = event.get_session_id()
        if not event.is_private_chat():
            if not self.game_manager.is_group_enabled(session_id):
                yield event.plain_result("该群未启用猜曲功能，请管理员使用/mg enable启用")
                return
        
        res = self.game_manager.start_game(session_id, max_n)
        yield event.plain_result(res)
        
        res = self.game_manager.get_hint(session_id)
        if isinstance(res, tuple):
            path, info = res
            chain = [Comp.Plain(info), Comp.Image.fromFileSystem(path)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)


    @mg.command("stop", alias={'结束'})
    async def stop(self, event: AstrMessageEvent):
        session_id = event.get_session_id()
        res = self.game_manager.stop_game(session_id)
        if isinstance(res, tuple):
            text, img = res
            chain = [Comp.Plain(text), Comp.Image.fromFileSystem(img)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @mg.command("guess", alias={'猜'})
    async def guess(self, event: AstrMessageEvent, title: str):
        session_id = event.get_session_id()
        if not event.is_private_chat() and not self.game_manager.is_group_enabled(session_id):
            yield event.plain_result("该群未启用猜曲功能")
            return
        
        res = self.game_manager.handle_guess(session_id, event.get_sender_name(), title)
        if isinstance(res, tuple):
            text, img = res
            chain = [Comp.Plain(text), Comp.Image.fromFileSystem(img)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @mg.command("rank", alias={'排行榜'})
    async def rank(self, event: AstrMessageEvent, top_n: int = 10):
        session_id = event.get_session_id()
        yield event.plain_result(self.game_manager.get_leaderboard(session_id, top_n))

    @mg.command("tip", alias={'提示'})
    async def tip(self, event: AstrMessageEvent):
        session_id = event.get_session_id()
        if not event.is_private_chat() and not self.game_manager.is_group_enabled(session_id):
            yield event.plain_result("该群未启用猜曲功能")
            return
        
        res = self.game_manager.get_hint(session_id)
        if isinstance(res, tuple):
            path, info = res
            chain = [Comp.Plain(info), Comp.Image.fromFileSystem(path)]
            yield event.chain_result(chain)
        else:
            yield event.plain_result(res)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_all_messages(self, event: AstrMessageEvent):
        session_id = event.get_session_id()
        if not self.game_manager or not self.game_manager.games:
            return

        if session_id not in self.game_manager.games:
            return
        message_str = event.message_str.strip()

        # 调用猜测逻辑，但不消耗次数
        res = self.game_manager.handle_non_command_guess(session_id, event.get_sender_name(), message_str)
        
        # 如果猜对，返回结果；如果没猜中，res 为 None，自动静默
        if not(res) or res[0].startswith("恭喜"):
            if isinstance(res, tuple):
                text, img = res
                chain = [Comp.Plain(text), Comp.Image.fromFileSystem(img)]
                yield event.chain_result(chain)
            else:
                yield event.plain_result(res)


    @mg.command("enable", alias={'启用'})
    async def enable(self, event: AstrMessageEvent):
        if event.is_private_chat():
            yield event.plain_result("该命令只能在群聊中使用")
            return
        
        if event.get_platform_name() == "aiocqhttp":
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot
            group_id = int(event.get_group_id())
            user_id = int(event.get_sender_id())
            try:
                ret = await client.api.call_action(
                    "get_group_member_info",
                    group_id=group_id,
                    user_id=user_id,
                    no_cache=True
                )
                if ret['role'] not in ['owner', 'admin']:
                    yield event.plain_result("权限不足，需要群主或管理员")
                    return
                self.game_manager.enable_group(group_id)
                yield event.plain_result("已启用该群的猜曲功能")
            except Exception as e:
                yield event.plain_result(f"操作失败: {e}")
        else:
            yield event.plain_result("该平台暂不支持此命令")

    @mg.command("disable", alias={'禁用'})
    async def disable(self, event: AstrMessageEvent):
        if event.is_private_chat():
            yield event.plain_result("该命令只能在群聊中使用")
            return
        
        if event.get_platform_name() == "aiocqhttp":
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot
            group_id = int(event.get_group_id())
            user_id = int(event.get_sender_id())
            try:
                ret = await client.api.call_action(
                    "get_group_member_info",
                    group_id=group_id,
                    user_id=user_id,
                    no_cache=True
                )
                if ret['role'] not in ['owner', 'admin']:
                    yield event.plain_result("权限不足，需要群主或管理员")
                    return
                self.game_manager.disable_group(group_id)
                yield event.plain_result("已禁用该群的猜曲功能")
            except Exception as e:
                yield event.plain_result(f"操作失败: {e}")
        else:
            yield event.plain_result("该平台暂不支持此命令")

    @mg.command("help", alias={'帮助'})
    async def help_text(self, event: AstrMessageEvent):
        help_msg = (
            "/mg start [次数] 开始游戏 如使用提示不多可调整次数\n"
            "/mg stop 停止游戏\n"
            "/mg guess 曲名 猜测曲目\n"
            "/mg tip 获取提示\n"
            "/mg rank [n] 查看排行榜\n"
            "/mg enable 启用本群功能（管理员）\n"
            "/mg disable 禁用本群功能（管理员）\n"
            "/mg help 获取帮助信息\n"
            "感谢rosemoe提供俗名库\n"
            "Version: 1.4.0 新增持久化、支持私聊、全局开关和[?未知特性]"
        )
        yield event.plain_result(help_msg)
