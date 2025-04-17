import json
import hashlib
import aiohttp  # 使用异步的 aiohttp 替代 requests
from tinydb import TinyDB, Query
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 数据库文件路径
db_path = '/AstrBot/data/songs_db.json'

# 从 URL 获取 JSON 数据（使用 aiohttp 进行异步请求）
async def fetch_song_data(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            # 强制将内容作为 JSON 进行解析，而不是依赖 MIME 类型
            try:
                return await response.json(content_type='application/json')  # 强制解析为 JSON
            except Exception as e:
                logger.error(f"请求解析失败，URL: {url}, 错误: {e}")
                raise

# 计算 JSON 数据的哈希值
def calculate_hash(data):
    # 将数据转换为 JSON 字符串后计算哈希值
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

# 存储数据到数据库
def store_data_in_db(data):
    # 创建数据库实例
    db = TinyDB(db_path)

    # 获取 info 表和 arc_data 表
    info_table = db.table('info')
    arc_data_table = db.table('arc_data')

    # 获取当前数据的哈希值
    current_hash = calculate_hash(data)

    # 查找 info 表中的哈希值
    info = info_table.all()
    if info and info[0].get('hash') == current_hash:
        print("数据未变化，跳过执行。")
        db.close()
        return

    # 如果哈希值不同或数据库为空，清空 arc_data 表并存储新数据
    print("数据变化，正在清空 arc_data 表并存储新数据...")
    arc_data_table.truncate()  # 清空 arc_data 表

    # 获取曲目难度的函数：考虑ratingPlus
    def get_rating(diff):
        rating = diff['rating']
        # 检查是否存在 ratingPlus 且为 True，若是，则加上 "+"
        if 'ratingPlus' in diff and diff['ratingPlus'] is True:
            return f"{rating}+"
        return str(rating)

    # 解析每个曲目信息并插入到 arc_data 表
    for song in data['songs']:
        if 'title_localized' not in song:
            continue
        
        song_data = {
            '曲名': song['title_localized'].get('en', ''),
            '语言': ' '.join([lang for lang in song['title_localized'].keys()]),
            '曲包': song['set'],
            '曲师': song['artist'],
            '难度分级': ' '.join(
                [
                    "PST" if diff['ratingClass'] == 0 else
                    "PRS" if diff['ratingClass'] == 1 else
                    "FTR" if diff['ratingClass'] == 2 else
                    "BYD" if diff['ratingClass'] == 3 else
                    "ETR" if diff['ratingClass'] == 4 else ""
                    for diff in song['difficulties']
                ]
            ),
            'FTR谱师': next((diff['chartDesigner'] for diff in song['difficulties'] if diff['ratingClass'] == 2), ''),
            '侧': '光芒侧' if song['side'] == 0 else
                  '纷争侧' if song['side'] == 1 else
                  '消色之侧' if song['side'] == 2 else
                  'Lephon侧',
            '背景': song['bg'],
            '版本': song['version'],
            'FTR难度': next((get_rating(diff) for diff in song['difficulties'] if diff['ratingClass'] == 2), ''),
            'BYD难度': next((get_rating(diff) for diff in song['difficulties'] if diff['ratingClass'] == 3), ''),
            'ETR难度': next((get_rating(diff) for diff in song['difficulties'] if diff['ratingClass'] == 4), '')
        }
        arc_data_table.insert(song_data)

    # 更新 info 表中的哈希值
    info_table.truncate()  # 清空 info 表
    info_table.insert({'hash': current_hash})

    # 关闭数据库
    db.close()

@register("mg-guessr", "Star0", "mg-guessr-extention", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化时会自动调用"""
        try:
            url = "https://arcwiki.mcd.blue/index.php?title=Template:Songlist.json&action=raw"
            # 异步获取曲目信息
            song_data = await fetch_song_data(url)
            # 存储数据到数据库
            store_data_in_db(song_data)
            logger.info("数据初始化并存储成功。")
        except Exception as e:
            logger.error(f"初始化插件时发生错误: {e}")

    @filter.command("mg")
    async def helloworld(self, event: AstrMessageEvent):
        """这是一个 hello world 指令"""
        user_name = event.get_sender_name()
        message_str = event.message_str
        message_chain = event.get_messages()
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!")

    async def terminate(self):
        """插件被卸载/停用时会调用"""
        pass
