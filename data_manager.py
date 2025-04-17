# data_manager.py

import csv
import json
import hashlib
import httpx
from tinydb import TinyDB
from astrbot.api import logger

# 数据库文件路径
db_path = '/AstrBot/data/songs_db.json'
alias_csv_url = "https://aya.yurisaki.top/fs/export/yrsk_arcaea_alias_1744887235.csv"

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
                'FTR谱师': next((diff.get('chartDesigner', '') for diff in song.get('difficulties', []) if diff.get('ratingClass') == 2), ''),
                '侧': '光芒侧' if song.get('side') == 0 else
                      '纷争侧' if song.get('side') == 1 else
                      '消色之侧' if song.get('side') == 2 else
                      'Lephon侧',
                '背景': song.get('bg', ''),
                '版本': song.get('version', ''),
                'FTR难度': next((get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 2), ''),
                'BYD难度': next((get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 3), ''),
                'ETR难度': next((get_rating(diff) for diff in song.get('difficulties', []) if diff.get('ratingClass') == 4), ''),
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
